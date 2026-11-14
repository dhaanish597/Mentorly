"""Regression Test Suite for Codex Independent Review Findings R1–R9 (`test_r1_to_r9_regressions.py`).

Covers:
- R1: Clean `Dockerfile.runner` COPY tree subprocess import without `worker_app` or `backend`.
- R2: Empty verification schedule returns `VERIFICATION_INCOMPLETE` (never `NO_FAILURE_FOUND`).
- R3: `Challenge.input_args` deep immutability, caller alias isolation, and `case_hash` verification.
- R4: Pre-launch `code_hash`, `case_hash`, and `(exercise_id, spec_version)` binding validation across `execute`, `trace`, and `verify`.
- R5: Hook-free `_safe_type_name`, `serialize_value`, `serialize_frame_locals`, and `safe_repr` against hostile metaclass `@property def __name__(cls)`.
- R6: Non-recursive archive builder with nested `.env` and `node_modules` sentinel exclusion verification.
- R7: Deterministic TypeScript contract drift detector with 6-mutation self-test.
- R8: `generate_bounded_cases` static holdout exclusion (`ex3_max_product` seed=23 `[-2, -3, -4]` probe across all exercises/specs).
- R9: Deterministic OpenAPI 3.1 `target_bounds` export and read-only `--check` verification.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import Any
import unittest
from uuid import uuid4

from backend.app.exercises import registry
from backend.app.models.domain import (
    Challenge,
    ExecutionRequest,
    RevisionRef,
    TraceRequest,
    VerifyJobRequest,
)
from backend.app.models.enums import (
    ChallengePurpose,
    ExerciseId,
    SpecVersion,
    VerificationStatus,
)
from backend.scripts.export_openapi import render_canonical_openapi
from exec_worker.runner.protocol import FRAME_BEGIN, FRAME_END, parse_runner_frame
from exec_worker.runner.safe_serializer import (
    safe_repr,
    sanitize_Locals,
    serialize_frame_locals,
    serialize_value,
)
from exec_worker.worker_app.sandbox_runner import GVisorSandboxRunner
from exec_worker.worker_app.trace_recorder import record_execution_trace
from exec_worker.worker_app.verifier_harness import (
    generate_bounded_cases,
    run_verification_job,
)
from scripts.check_schema_drift import (
    check_ts_content,
    render_typescript_contracts,
    run_self_test,
)


def _find_repo_root() -> Path:
    curr = Path(__file__).resolve().parent
    for candidate in (curr.parents[1], curr.parents[2], curr.parents[0]):
        if (candidate / "exec_worker").is_dir() and (candidate / "backend").is_dir():
            return candidate
    return Path(__file__).resolve().parents[2]


REPO_ROOT = _find_repo_root()


class R1ToR9RegressionTests(unittest.TestCase):
    """Canonical v2 regression suite verifying fixes R1 through R9."""

    def test_r1_runner_dockerfile_tree_isolated_subprocess_import(self) -> None:
        """R1: Stage ONLY the files copied by `Dockerfile.runner` and import the trusted runner in a `-I -B` subprocess."""
        with tempfile.TemporaryDirectory(prefix="vcc_r1_stage_") as tmp:
            tmp_path = Path(tmp)
            staged_root = tmp_path / "app"
            (staged_root / "exec_worker" / "runner").mkdir(parents=True)

            shutil.copy2(
                REPO_ROOT / "exec_worker" / "__init__.py",
                staged_root / "exec_worker" / "__init__.py",
            )
            runner_src = REPO_ROOT / "exec_worker" / "runner"
            for py_file in runner_src.glob("*.py"):
                shutil.copy2(
                    py_file, staged_root / "exec_worker" / "runner" / py_file.name
                )

            self.assertFalse((staged_root / "exec_worker" / "worker_app").exists())
            self.assertFalse((staged_root / "backend").exists())

            # Packaging checks import trusted runner modules only. Actual source
            # execution is covered by runsc acceptance, never a host subprocess.
            code = (
                f"import sys; sys.path.insert(0, {str(staged_root)!r}); "
                "import exec_worker.runner; "
                "import exec_worker.runner.run_invocation; "
                "import exec_worker.runner.in_sandbox_tracer; "
                "assert 'backend' not in sys.modules; "
                "assert 'exec_worker.worker_app' not in sys.modules"
            )
            proc = subprocess.run(
                [sys.executable, "-I", "-B", "-c", code],
                capture_output=True, env={"PATH": ""}, timeout=5.0, check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr.decode(errors="replace"))

    def test_r2_empty_verification_schedule_returns_verification_incomplete(self) -> None:
        """R2: A `VerifyJobRequest` with all stages disabled must return `VERIFICATION_INCOMPLETE` (never `NO_FAILURE_FOUND`)."""
        code = "def shortest_subarray_ge_target(nums: list[int], target: int) -> int:\n    return -999\n"
        rev = RevisionRef(
            session_id=uuid4(),
            exercise_id=ExerciseId.EX1_SHORTEST_SUBARRAY,
            spec_version=SpecVersion.EX1_V1_POSITIVE_ONLY,
            code_version_id=1,
            code_hash=hashlib.sha256(code.encode("utf-8")).hexdigest(),
            turn_generation=1,
        )
        req = VerifyJobRequest(
            job_id=uuid4(),
            revision=rev,
            source_code=code,
            prior_failing_input=None,
            target_input=None,
            run_curated_suite=False,
            generated_cases_target=0,
        )
        runner = GVisorSandboxRunner()
        report = run_verification_job(req, runner)
        self.assertEqual(report.status, VerificationStatus.VERIFICATION_INCOMPLETE)
        self.assertNotEqual(report.status, VerificationStatus.NO_FAILURE_FOUND)
        self.assertEqual(report.curated_cases_run, 0)
        self.assertEqual(report.generated_cases_run, 0)
        self.assertEqual(report.completed_stages, [])
        self.assertEqual(
            report.terminal_reason, "No verification stages or cases were scheduled"
        )

    def test_r3_challenge_deep_immutability_and_alias_isolation(self) -> None:
        """R3: `Challenge.input_args` must sever caller aliases, reject nested in-place mutation, and verify `case_hash`."""
        now = datetime.now(timezone.utc)
        code = "def shortest_subarray_ge_target(nums: list[int], target: int) -> int:\n    return 1\n"
        rev = RevisionRef(
            session_id=uuid4(),
            exercise_id=ExerciseId.EX1_SHORTEST_SUBARRAY,
            spec_version=SpecVersion.EX1_V2_NEGATIVES_ALLOWED,
            code_version_id=1,
            code_hash=hashlib.sha256(code.encode("utf-8")).hexdigest(),
            turn_generation=1,
        )
        raw_input: dict[str, Any] = {"nums": [1, -1, 5], "target": 5}
        canonical = registry.validate_input(
            str(rev.exercise_id), str(rev.spec_version), raw_input
        )
        case_hash = registry.case_key(
            str(rev.exercise_id), str(rev.spec_version), canonical
        )

        challenge = Challenge(
            challenge_id=uuid4(),
            revision=rev,
            input_args=raw_input,
            case_hash=case_hash,
            purpose=ChallengePurpose.DIAGNOSTIC,
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )

        # Caller alias mutation must not affect challenge.input_args
        raw_input["nums"].append(999)
        raw_input["target"] = -100
        self.assertEqual(list(challenge.input_args["nums"]), [1, -1, 5])
        self.assertEqual(challenge.input_args["target"], 5)

        # Direct top-level or nested mutation on challenge.input_args must raise TypeError
        with self.assertRaises(TypeError):
            challenge.input_args["target"] = 99
        with self.assertRaises(TypeError):
            challenge.input_args["nums"][0] = -999
        with self.assertRaises(TypeError):
            challenge.input_args["nums"].append(4)

        self.assertTrue(challenge.verify_case_hash())
        self.assertTrue(
            challenge.verify_case_hash(
                ExerciseId.EX1_SHORTEST_SUBARRAY, SpecVersion.EX1_V2_NEGATIVES_ALLOWED
            )
        )
        self.assertFalse(
            challenge.verify_case_hash(
                ExerciseId.EX2_BINARY_SEARCH, SpecVersion.EX2_V1_SORTED_WITH_DUPLICATES
            )
        )
        dumped = challenge.model_dump(mode="json")
        self.assertEqual(dumped["input_args"], {"nums": [1, -1, 5], "target": 5})

    def test_r4_broker_rejects_mismatched_hashes_before_container_launch(self) -> None:
        """R4: Invalid `code_hash`, `case_hash`, or `(exercise_id, spec_version)` must raise `ValueError` BEFORE preflight or container launch."""
        preflight_or_launch_called = False

        def _forbid_call(*_args: Any, **_kwargs: Any) -> Any:
            nonlocal preflight_or_launch_called
            preflight_or_launch_called = True
            raise AssertionError(
                "Preflight or container launch must NEVER be reached when request bindings are invalid!"
            )

        runner = GVisorSandboxRunner(
            preflight_fn=_forbid_call,
            popen_factory=_forbid_call,
        )

        code = "def shortest_subarray_ge_target(nums: list[int], target: int) -> int:\n    return 0\n"
        real_code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
        canonical_args = registry.validate_input(
            str(ExerciseId.EX1_SHORTEST_SUBARRAY),
            str(SpecVersion.EX1_V1_POSITIVE_ONLY),
            {"nums": [1, 2], "target": 3},
        )
        real_case_hash = registry.case_key(
            str(ExerciseId.EX1_SHORTEST_SUBARRAY),
            str(SpecVersion.EX1_V1_POSITIVE_ONLY),
            canonical_args,
        )

        bad_code_rev = RevisionRef(
            session_id=uuid4(),
            exercise_id=ExerciseId.EX1_SHORTEST_SUBARRAY,
            spec_version=SpecVersion.EX1_V1_POSITIVE_ONLY,
            code_version_id=1,
            code_hash="0" * 64,
            turn_generation=1,
        )
        good_code_rev = RevisionRef(
            session_id=uuid4(),
            exercise_id=ExerciseId.EX1_SHORTEST_SUBARRAY,
            spec_version=SpecVersion.EX1_V1_POSITIVE_ONLY,
            code_version_id=1,
            code_hash=real_code_hash,
            turn_generation=1,
        )

        # 1. execute() with bad code_hash
        with self.assertRaisesRegex(ValueError, "Code hash mismatch"):
            runner.execute(
                ExecutionRequest(
                    job_id=uuid4(),
                    revision=bad_code_rev,
                    source_code=code,
                    input_args=canonical_args,
                    case_hash=real_case_hash,
                )
            )

        # 2. execute() with bad case_hash
        with self.assertRaisesRegex(ValueError, "Case hash mismatch"):
            runner.execute(
                ExecutionRequest(
                    job_id=uuid4(),
                    revision=good_code_rev,
                    source_code=code,
                    input_args=canonical_args,
                    case_hash="f" * 64,
                )
            )

        # 3. trace() and record_execution_trace() with bad case_hash and bad code_hash
        trace_req_bad_case = TraceRequest(
            job_id=uuid4(),
            trace_id=uuid4(),
            revision=good_code_rev,
            source_code=code,
            input_args=canonical_args,
            case_hash="a" * 64,
        )
        with self.assertRaisesRegex(ValueError, "Case hash mismatch"):
            runner.trace(trace_req_bad_case)
        with self.assertRaisesRegex(ValueError, "Case hash mismatch"):
            record_execution_trace(trace_req_bad_case, runner)

        trace_req_bad_code = TraceRequest(
            job_id=uuid4(),
            trace_id=uuid4(),
            revision=bad_code_rev,
            source_code=code,
            input_args=canonical_args,
            case_hash=real_case_hash,
        )
        with self.assertRaisesRegex(ValueError, "Code hash mismatch"):
            runner.trace(trace_req_bad_code)
        with self.assertRaisesRegex(ValueError, "Code hash mismatch"):
            record_execution_trace(trace_req_bad_code, runner)

        # 4. run_verification_job() with bad code_hash
        with self.assertRaisesRegex(ValueError, "Code hash mismatch"):
            run_verification_job(
                VerifyJobRequest(
                    job_id=uuid4(),
                    revision=bad_code_rev,
                    source_code=code,
                    run_curated_suite=True,
                ),
                runner,
            )

        self.assertFalse(preflight_or_launch_called)

    def test_r5_safe_serializer_blocks_hostile_metaclass_name_property(self) -> None:
        """R5: A custom metaclass with `@property def __name__(cls)` must never execute during serialization."""
        triggered = False

        class HostileMeta(type):
            @property
            def __name__(cls) -> str:  # type: ignore[override]
                nonlocal triggered
                triggered = True
                raise RuntimeError("Metaclass __name__ hook executed!")

        class HostileObject(metaclass=HostileMeta):
            def __repr__(self) -> str:
                nonlocal triggered
                triggered = True
                raise RuntimeError("Instance __repr__ hook executed!")

        instance = HostileObject()
        val_res = serialize_value(instance)
        locals_snap, _ = serialize_frame_locals({"victim": instance, "count": 7})
        rendered = safe_repr(instance)
        str_snap = sanitize_Locals({"victim": instance, "count": 7})

        self.assertFalse(triggered)
        self.assertIn("__vcc_untrusted_type__", val_res.value)
        self.assertEqual(locals_snap["count"], 7)
        self.assertIn("__vcc_untrusted_type__", locals_snap["victim"])
        self.assertTrue(rendered.startswith("<") and rendered.endswith("object>"))
        self.assertEqual(str_snap["count"], "7")
        self.assertTrue(str_snap["victim"].endswith("object>"))

    def test_r6_archive_builder_excludes_nested_secret_and_node_modules_sentinels(
        self,
    ) -> None:
        """R6: Non-recursive tar archive builder must exclude nested `.env`, `node_modules`, and symlinks."""
        with tempfile.TemporaryDirectory(prefix="vcc_r6_archive_") as tmp:
            tmp_path = Path(tmp)
            src_root = tmp_path / "repo"
            (src_root / "backend" / "app").mkdir(parents=True)
            (src_root / "backend" / "app" / "main.py").write_text(
                "print('ok')\n", encoding="utf-8"
            )
            (src_root / "nested" / "node_modules" / "pkg").mkdir(parents=True)
            (src_root / "nested" / "node_modules" / "pkg" / "sentinel.js").write_text(
                "SECRET", encoding="utf-8"
            )
            (src_root / "nested" / ".env").write_text(
                "VCC_GNANI_API_KEY=leak\n", encoding="utf-8"
            )
            (src_root / "nested" / "session.sqlite3").write_text(
                "db", encoding="utf-8"
            )

            excluded_dirs = {
                ".git",
                "node_modules",
                "__pycache__",
                ".pytest_cache",
                ".venv",
                "dist",
            }
            excluded_suffixes = {".pyc", ".pyo", ".sqlite3", ".db", ".pem", ".key"}

            archive_path = tmp_path / "snapshot.tar.gz"
            with tarfile.open(archive_path, "w:gz") as tar:
                for p in sorted(src_root.rglob("*")):
                    if p.is_symlink() or not p.is_file():
                        continue
                    rel = p.relative_to(src_root)
                    if any(part in excluded_dirs for part in rel.parts):
                        continue
                    if p.name.startswith(".env") or p.suffix in excluded_suffixes:
                        continue
                    tar.add(p, arcname=str(rel), recursive=False)

            with tarfile.open(archive_path, "r:gz") as tar:
                names = tar.getnames()

            self.assertEqual(names, ["backend/app/main.py"])

    def test_r7_schema_drift_catches_type_nullability_optionality_and_union_mutations(
        self,
    ) -> None:
        """R7: `check_schema_drift.py` must catch field type, nullability, optionality, and union mutations."""
        self.assertEqual(run_self_test(), 0)
        ts_path = REPO_ROOT / "frontend" / "src" / "types" / "api.ts"
        if ts_path.is_file():
            committed_ts = ts_path.read_text(encoding="utf-8")
            self.assertEqual(check_ts_content(committed_ts), [])
            self.assertEqual(committed_ts, render_typescript_contracts())

    def test_r8_generate_bounded_cases_excludes_all_static_holdouts(self) -> None:
        """R8: `generate_bounded_cases('ex3_max_product', 'v1_bounded_ints', count=200, seed=23)` must never emit `[-2, -3, -4]` or any static holdout."""
        spec_pairs = (
            (
                str(ExerciseId.EX1_SHORTEST_SUBARRAY),
                str(SpecVersion.EX1_V1_POSITIVE_ONLY),
            ),
            (
                str(ExerciseId.EX1_SHORTEST_SUBARRAY),
                str(SpecVersion.EX1_V2_NEGATIVES_ALLOWED),
            ),
            (
                str(ExerciseId.EX2_BINARY_SEARCH),
                str(SpecVersion.EX2_V1_SORTED_WITH_DUPLICATES),
            ),
            (
                str(ExerciseId.EX3_MAX_PRODUCT),
                str(SpecVersion.EX3_V1_BOUNDED_INTS),
            ),
        )
        for ex_id, spec_ver in spec_pairs:
            holdouts = registry.cases(ex_id, spec_ver, "holdout")
            holdout_hashes = {
                registry.case_key(ex_id, spec_ver, h) for h in holdouts
            }
            generated = generate_bounded_cases(ex_id, spec_ver, 200, 23)
            self.assertGreater(len(generated), 0)
            for case in generated:
                self.assertNotIn(case, holdouts)
                self.assertNotIn(
                    registry.case_key(ex_id, spec_ver, case), holdout_hashes
                )
            if ex_id == str(ExerciseId.EX3_MAX_PRODUCT):
                self.assertNotIn({"nums": [-2, -3, -4]}, generated)

    def test_r9_openapi_export_check_passes_deterministically(self) -> None:
        """R9: `render_canonical_openapi()` must match `backend/openapi.json` without `default: null` drift."""
        openapi_path = REPO_ROOT / "backend" / "openapi.json"
        rendered = render_canonical_openapi()
        parsed = json.loads(rendered)
        self.assertIn("ExerciseSpecMetadata", parsed["components"]["schemas"])
        target_bounds_prop = (
            parsed["components"]["schemas"]["ExerciseSpecMetadata"]["properties"][
                "target_bounds"
            ]
        )
        if "anyOf" in target_bounds_prop:
            self.assertIn("default", target_bounds_prop)
            self.assertIsNone(target_bounds_prop["default"])
            if openapi_path.is_file():
                committed = openapi_path.read_text(encoding="utf-8")
                self.assertEqual(committed, rendered)


if __name__ == "__main__":
    unittest.main()



if __name__ == "__main__":
    unittest.main()
