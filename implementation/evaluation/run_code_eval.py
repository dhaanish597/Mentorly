"""P8 code evaluation through accepted runsc only; source fixtures are inert data.

Generic execution errors, protocol errors and timeouts never count as successful
bug detections. Correct alternatives require completed curated/generated suites.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.models.domain import RevisionRef, VerifyJobRequest  # noqa: E402
from backend.app.models.enums import (  # noqa: E402
    ExecutionObservationKind, ExerciseId, SpecVersion, VerificationStatus,
)
from exec_worker.worker_app.sandbox_runner import GVisorSandboxRunner  # noqa: E402
from exec_worker.worker_app.verifier_harness import run_verification_job  # noqa: E402

GENERATED_TARGET = 40
SEED = 42


def _request(item: dict[str, Any]) -> VerifyJobRequest:
    code = item["source_code"]
    return VerifyJobRequest(
        job_id=uuid4(),
        revision=RevisionRef(
            session_id=uuid4(), exercise_id=ExerciseId(item["exercise_id"]),
            spec_version=SpecVersion(item["spec_version"]), code_version_id=1,
            code_hash=hashlib.sha256(code.encode()).hexdigest(), turn_generation=1,
        ),
        source_code=code, run_curated_suite=True,
        generated_cases_target=GENERATED_TARGET, seed=SEED,
    )


def _detected(report: Any) -> bool:
    observation = report.student_observation
    if report.status != VerificationStatus.COUNTEREXAMPLE_CONFIRMED or observation is None or report.counterexample_input is None:
        return False
    if observation.kind == ExecutionObservationKind.EXCEPTION:
        return True
    return (
        observation.kind == ExecutionObservationKind.RETURN
        and report.reference_output is not None
        and type(observation.return_value) is type(report.reference_output)
        and observation.return_value != report.reference_output
    )


def _complete_pass(report: Any) -> bool:
    return (
        report.status == VerificationStatus.NO_FAILURE_FOUND
        and report.student_observation is None
        and report.counterexample_input is None
        and report.curated_cases_total > 0
        and report.curated_cases_run == report.curated_cases_total
        and report.generated_cases_target == GENERATED_TARGET
        and report.generated_cases_run == GENERATED_TARGET
        and {"curated_suite", "generated_suite"}.issubset(report.completed_stages)
    )


def _observed(item: dict[str, Any], report: Any, id_key: str) -> dict[str, Any]:
    return {
        id_key: item[id_key], "status": report.status.value,
        "code_hash": hashlib.sha256(item["source_code"].encode()).hexdigest(),
        "exercise_id": item["exercise_id"], "spec_version": item["spec_version"],
        "counterexample_input": report.counterexample_input,
        "reference_output": report.reference_output,
        "observation_kind": report.student_observation.kind.value if report.student_observation else None,
        "student_output": getattr(report.student_observation, "return_value", None),
        "curated_cases_run": report.curated_cases_run,
        "curated_cases_total": report.curated_cases_total,
        "generated_cases_run": report.generated_cases_run,
        "generated_cases_target": report.generated_cases_target,
        "completed_stages": list(report.completed_stages),
        "runtime_version": report.runtime_version, "seed": report.seed,
        "terminal_reason": report.terminal_reason,
        "localization": "NOT_MEASURED_ABSTAIN",
    }


def _run_items(items: list[dict[str, Any]], runner: Any, id_key: str) -> list[dict[str, Any]]:
    results = []
    for item in items:
        try:
            report = run_verification_job(_request(item), runner)
        except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
            results.append({id_key: item[id_key], "status": "EVALUATOR_ERROR", "error_type": type(exc).__name__, "detected" if id_key == "fixture_id" else "passed": False, "report_observed": False})
            continue
        flag = "detected" if id_key == "fixture_id" else "passed"
        results.append(_observed(item, report, id_key) | {flag: _detected(report) if flag == "detected" else _complete_pass(report), "report_observed": True})
    return results


def run_evaluation_suite(fixtures_dir: Path | None = None) -> dict[str, Any]:
    directory = fixtures_dir or Path(__file__).parent / "corpora"
    buggy = json.loads((directory / "buggy_implementations.json").read_text())["fixtures"]
    correct = json.loads((directory / "correct_alternatives.json").read_text())["implementations"]
    if len(buggy) != 12 or len(correct) < 6:
        raise ValueError("Evaluation requires exactly 12 buggy cases and at least six alternatives")
    base = {
        "overall_pass": False, "buggy_total": len(buggy), "correct_total": len(correct),
        "buggy_reports_observed": 0, "correct_reports_observed": 0,
        "buggy_detected_count": 0, "correct_passed_count": 0,
        "buggy_cases_observed": 0, "correct_cases_observed": 0,
        "correct_counterexample_count": 0,
        "buggy_results": [], "correct_results": [], "seed": SEED,
        "run_date": datetime.now(timezone.utc).isoformat(),
        "command": list(sys.argv),
        "limitations": "Counts are observed evidence, not targets. Timeout/resource/protocol/infrastructure failures are not detections. Localization and speech not measured.",
    }
    runner = GVisorSandboxRunner()
    preflight = runner.check_preflight()
    if not preflight.ready or not preflight.acceptance_verified:
        return base | {"status": "BLOCKED_EXTERNAL", "reason": preflight.summary}
    bug_results = _run_items(buggy, runner, "fixture_id")
    correct_results = _run_items(correct, runner, "impl_id")
    bugs_detected = sum(r["detected"] for r in bug_results)
    correct_passed = sum(r["passed"] for r in correct_results)
    passed = bugs_detected == len(buggy) and correct_passed == len(correct)
    return base | {
        "status": "PASS" if passed else "NOT_ACCEPTED", "overall_pass": passed,
        "buggy_detected_count": bugs_detected, "correct_passed_count": correct_passed,
        "buggy_reports_observed": sum(r["report_observed"] for r in bug_results),
        "correct_reports_observed": sum(r["report_observed"] for r in correct_results),
        "buggy_cases_observed": sum(r.get("curated_cases_run", 0) + r.get("generated_cases_run", 0) for r in bug_results),
        "correct_cases_observed": sum(r.get("curated_cases_run", 0) + r.get("generated_cases_run", 0) for r in correct_results),
        "correct_counterexample_count": sum(r["status"] == VerificationStatus.COUNTEREXAMPLE_CONFIRMED for r in correct_results),
        "buggy_results": bug_results, "correct_results": correct_results,
    }


if __name__ == "__main__":
    summary = run_evaluation_suite()
    print(json.dumps(summary, indent=2))
    raise SystemExit(2 if summary["status"] == "BLOCKED_EXTERNAL" else (0 if summary["overall_pass"] else 1))
