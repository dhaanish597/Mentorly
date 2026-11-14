"""Unit tests for Phase 1 (T-02) Safe Execution Broker, gVisor Sandbox Runner, Verifier Harness, and WorkerClient."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import subprocess
from typing import Any, Callable
import unittest
import uuid

from fastapi.testclient import TestClient

try:
    from backend.app.db.repository import SessionRecord
    from backend.app.exercises import registry as exercise_registry
    from backend.app.models.domain import (
        ExecutionBudgetConfig,
        ExecutionObservation,
        ExecutionRequest,
        RevisionRef,
        TraceExecutionReport,
        TraceRequest,
        VerifyJobRequest,
    )
    from backend.app.models.enums import (
        ExecutionObservationKind,
        ExerciseId,
        JobStatus,
        SpecVersion,
        TraceAttributionStatus,
        TraceEventKind,
        TraceExecutionStatus,
        VerificationStatus,
    )
    from backend.app.orchestration.worker_client import (
        BrokerAuthenticationError,
        PublicCustomCodeDisabledError,
        WorkerClient,
    )
except ImportError:  # pragma: no cover
    from app.db.repository import SessionRecord  # type: ignore[no-redef]
    from app.exercises import registry as exercise_registry  # type: ignore[no-redef]
    from app.models.domain import (  # type: ignore[no-redef]
        ExecutionBudgetConfig,
        ExecutionObservation,
        ExecutionRequest,
        RevisionRef,
        TraceExecutionReport,
        TraceRequest,
        VerifyJobRequest,
    )
    from app.models.enums import (  # type: ignore[no-redef]
        ExecutionObservationKind,
        ExerciseId,
        JobStatus,
        SpecVersion,
        TraceAttributionStatus,
        TraceEventKind,
        TraceExecutionStatus,
        VerificationStatus,
    )
    from app.orchestration.worker_client import (  # type: ignore[no-redef]
        BrokerAuthenticationError,
        PublicCustomCodeDisabledError,
        WorkerClient,
    )

from exec_worker.worker_app.main import (
    ActiveJobRegistry,
    BrokerConfig,
    create_broker_app,
)
from exec_worker.worker_app.sandbox_runner import (
    DEFAULT_FRAME_PREFIX,
    DEFAULT_RUNNER_IMAGE,
    FrameParseError,
    GVisorSandboxRunner,
    SandboxRuntimePreflight,
    build_docker_run_command,
    check_runtime_preflight,
    parse_runner_frame,
)
from exec_worker.worker_app.verifier_harness import run_verification_job


def _make_revision(
    *,
    session_id: uuid.UUID | None = None,
    exercise_id: ExerciseId = ExerciseId.EX1_SHORTEST_SUBARRAY,
    spec_version: SpecVersion = SpecVersion.EX1_V1_POSITIVE_ONLY,
    code_version_id: int = 1,
    source_code: str = "def shortest_subarray_ge_target(nums, target):\n    return 0\n",
    turn_generation: int = 1,
) -> RevisionRef:
    code_hash = hashlib.sha256(source_code.encode("utf-8")).hexdigest()
    return RevisionRef(
        session_id=session_id or uuid.uuid4(),
        exercise_id=exercise_id,
        spec_version=spec_version,
        code_version_id=code_version_id,
        code_hash=code_hash,
        turn_generation=turn_generation,
    )


class _FakePopenProcess:
    def __init__(
        self,
        *,
        stdout_bytes: bytes = b"",
        stderr_bytes: bytes = b"",
        returncode: int = 0,
        raise_timeout: bool = False,
        on_wait: Callable[[], None] | None = None,
    ) -> None:
        self.stdout = io.BytesIO(stdout_bytes)
        self.stderr = io.BytesIO(stderr_bytes)
        self.returncode: int | None = None if raise_timeout else returncode
        self._final_returncode = returncode
        self._raise_timeout = raise_timeout
        self._on_wait = on_wait
        self.killed = False

    def wait(self, timeout: float | None = None) -> int:
        if self._on_wait is not None:
            self._on_wait()
        if self._raise_timeout:
            raise subprocess.TimeoutExpired(cmd=["docker", "run"], timeout=timeout or 1.0)
        self.returncode = self._final_returncode
        return self._final_returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class _ControlledSandboxRunner:
    def __init__(
        self,
        *,
        execute_fn: Callable[[ExecutionRequest, int], ExecutionObservation] | None = None,
        preflight: SandboxRuntimePreflight | None = None,
        runtime_version: str = "runsc-test-1.0",
    ) -> None:
        self._execute_fn = execute_fn
        self._preflight = preflight or SandboxRuntimePreflight(
            ready=True,
            platform_system="Linux",
            docker_available=True,
            runsc_registered=True,
            runsc_binary_available=True,
            runner_image_present=True,
            runner_image=DEFAULT_RUNNER_IMAGE,
            runtime_version=runtime_version,
            failure_reasons=(),
        )
        self._runtime_version = runtime_version
        self.execute_calls: list[ExecutionRequest] = []
        self.trace_calls: list[TraceRequest] = []
        self.cancelled_jobs: list[uuid.UUID] = []

    @property
    def runtime_version(self) -> str:
        return self._runtime_version

    def check_preflight(self) -> SandboxRuntimePreflight:
        return self._preflight

    def execute(self, req: ExecutionRequest) -> ExecutionObservation:
        call_index = len(self.execute_calls)
        self.execute_calls.append(req)
        if self._execute_fn is not None:
            return self._execute_fn(req, call_index)
        ans = exercise_registry.evaluate(
            str(req.revision.exercise_id),
            str(req.revision.spec_version),
            deepcopy(req.input_args),
        )
        return ExecutionObservation(
            kind=ExecutionObservationKind.RETURN,
            return_value=ans,
            duration_ms=5,
        )

    def trace(self, req: TraceRequest) -> TraceExecutionReport:
        self.trace_calls.append(req)
        obs = self.execute(
            ExecutionRequest(
                job_id=req.job_id,
                revision=req.revision,
                challenge_id=req.challenge_id,
                source_code=req.source_code,
                input_args=req.input_args,
                case_hash=req.case_hash,
                budget=req.budget,
            )
        )
        return TraceExecutionReport(
            trace_id=req.trace_id,
            revision=req.revision,
            case_hash=req.case_hash,
            status=TraceExecutionStatus.COMPLETED,
            steps=[],
            total_observed=0,
            trace_truncated=False,
            termination_reason="Trace completed",
            observation=obs,
            runtime_version=self._runtime_version,
        )

    def cancel_invocation(self, job_id: uuid.UUID) -> bool:
        self.cancelled_jobs.append(job_id)
        return True


class _FakeSessionRepository:
    def __init__(self, session: SessionRecord | None, *, code_hash: str | None = None) -> None:
        self.session = session
        self.code_hash = code_hash

    def get_session(
        self, session_id: str, *, include_deleted: bool = False
    ) -> SessionRecord | None:
        if self.session is None or self.session.id != session_id:
            return None
        if not include_deleted and self.session.deleted_at is not None:
            return None
        return self.session

    def get_code_version(self, session_id: str, code_version_id: int) -> Any:
        if self.session is None or self.code_hash is None:
            return None

        class _CV:
            def __init__(self, ch: str) -> None:
                self.code_hash = ch

        return _CV(self.code_hash)


class DockerCommandAndPreflightTests(unittest.TestCase):
    def test_build_docker_run_command_enforces_all_gvisor_and_isolation_flags(self) -> None:
        budget = ExecutionBudgetConfig(
            pids_limit=16,
            memory_limit_mb=256,
            tmpfs_size_mb=8,
        )
        cmd = build_docker_run_command(
            container_name="vcc-sbx-test1234",
            job_input_dir="/tmp/vcc_ipc_job1",
            budget=budget,
            runner_image="vcc-runner:phase1",
        )
        assert cmd[:3] == ["docker", "run", "--rm"]
        assert "--runtime=runsc" in cmd
        assert "--network=none" in cmd
        assert "--read-only" in cmd
        assert "--cap-drop=ALL" in cmd
        assert "--security-opt=no-new-privileges" in cmd
        assert f"--pids-limit={budget.pids_limit}" in cmd
        assert f"--memory={budget.memory_limit_mb}m" in cmd
        assert f"--memory-swap={budget.memory_limit_mb}m" in cmd
        assert "--cpus=1.0" in cmd

        user_idx = cmd.index("--user")
        assert cmd[user_idx + 1] == "65534:65534"

        tmpfs_idx = cmd.index("--tmpfs")
        assert cmd[tmpfs_idx + 1] == f"/tmp:rw,noexec,nosuid,nodev,size={budget.tmpfs_size_mb}m"

        vol_idx = cmd.index("-v")
        mount_spec = cmd[vol_idx + 1]
        assert mount_spec.endswith(":/ipc_in:ro")
        assert "docker.sock" not in " ".join(cmd)
        assert "-e" not in cmd
        assert "vcc-runner:phase1" in cmd
        assert cmd[-1] == "/ipc_in/payload.json"

    def test_preflight_succeeds_only_when_linux_docker_runsc_and_image_verified(self) -> None:
        def fake_cmd(cmd: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            if cmd[:2] == ["docker", "info"]:
                return subprocess.CompletedProcess(
                    cmd, 0, stdout='{"runc":{"path":"runc"},"runsc":{"path":"/usr/bin/runsc"}}', stderr=""
                )
            if cmd[:2] == ["runsc", "--version"]:
                return subprocess.CompletedProcess(
                    cmd, 0, stdout="runsc version release-20261028.0\n", stderr=""
                )
            if cmd[:3] == ["docker", "image", "inspect"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="sha256:abcdef\n", stderr="")
            raise AssertionError(f"Unexpected command: {cmd}")

        preflight = check_runtime_preflight(
            runner_image="vcc-runner:phase1",
            platform_system_fn=lambda: "Linux",
            which_fn=lambda binary: f"/usr/bin/{binary}",
            command_runner=fake_cmd,
        )
        assert preflight.ready is True
        assert preflight.docker_available is True
        assert preflight.runsc_registered is True
        assert preflight.runsc_binary_available is True
        assert preflight.runner_image_present is True
        assert "runsc" in preflight.runtime_version
        assert len(preflight.failure_reasons) == 0

    def test_preflight_fails_closed_when_not_linux_or_runsc_missing(self) -> None:
        def fake_cmd_no_runsc(cmd: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            if cmd[:2] == ["docker", "info"]:
                return subprocess.CompletedProcess(
                    cmd, 0, stdout='{"runc":{"path":"runc"}}', stderr=""
                )
            if cmd[:3] == ["docker", "image", "inspect"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="sha256:abcdef\n", stderr="")
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="not found")

        preflight = check_runtime_preflight(
            runner_image="vcc-runner:phase1",
            platform_system_fn=lambda: "Darwin",
            which_fn=lambda binary: "/usr/bin/docker" if binary == "docker" else None,
            command_runner=fake_cmd_no_runsc,
        )
        assert preflight.ready is False
        assert preflight.runsc_registered is False
        assert preflight.runsc_binary_available is False
        assert any("Linux" in r for r in preflight.failure_reasons)
        assert any("runsc" in r for r in preflight.failure_reasons)

    def test_runner_fails_closed_without_invoking_popen_when_preflight_fails(self) -> None:
        popen_called = False

        def forbidden_popen(*_args: Any, **_kwargs: Any) -> Any:
            nonlocal popen_called
            popen_called = True
            raise AssertionError("Popen must never be called when preflight fails")

        unavail_preflight = SandboxRuntimePreflight(
            ready=False,
            platform_system="Darwin",
            docker_available=False,
            runsc_registered=False,
            runsc_binary_available=False,
            runner_image_present=False,
            runner_image=DEFAULT_RUNNER_IMAGE,
            runtime_version="runsc-unavailable",
            failure_reasons=("Host OS must be Linux", "runsc missing"),
        )
        runner = GVisorSandboxRunner(
            preflight_fn=lambda: unavail_preflight,
            popen_factory=forbidden_popen,
        )
        rev = _make_revision(source_code="def shortest_subarray_ge_target(nums, target):\n    import os; os.system('id')\n")
        c_hash = exercise_registry.case_key(
            str(rev.exercise_id), str(rev.spec_version), {"nums": [5], "target": 5}
        )
        exec_req = ExecutionRequest(
            job_id=uuid.uuid4(),
            revision=rev,
            source_code="def shortest_subarray_ge_target(nums, target):\n    import os; os.system('id')\n",
            input_args={"nums": [5], "target": 5},
            case_hash=c_hash,
        )
        obs = runner.execute(exec_req)
        assert obs.kind == ExecutionObservationKind.UNAVAILABLE
        assert obs.return_value is None
        assert popen_called is False

        trace_req = TraceRequest(
            job_id=uuid.uuid4(),
            trace_id=uuid.uuid4(),
            revision=rev,
            source_code=exec_req.source_code,
            input_args=exec_req.input_args,
            case_hash=c_hash,
        )
        trace_rep = runner.trace(trace_req)
        assert trace_rep.status == TraceExecutionStatus.TRACE_UNAVAILABLE
        assert popen_called is False


class SandboxRunnerFramingAndLifecycleTests(unittest.TestCase):
    def test_parse_runner_frame_accepts_valid_single_frame_and_rejects_spoofed_frames(self) -> None:
        raw = f'user debug line\n{DEFAULT_FRAME_PREFIX}{{"kind":"RETURN","return_value":3}}\n'
        user_out, frame = parse_runner_frame(raw)
        assert user_out == "user debug line"
        assert frame["kind"] == "RETURN"
        assert frame["return_value"] == 3

        spoofed = (
            f'{DEFAULT_FRAME_PREFIX}{{"kind":"RETURN","return_value":999}}\n'
            f'{DEFAULT_FRAME_PREFIX}{{"kind":"RETURN","return_value":1}}\n'
        )
        with self.assertRaises(FrameParseError):
            parse_runner_frame(spoofed)

    def test_runner_maps_exit_137_timeout_bool_return_and_valid_int_return(self) -> None:
        ready_preflight = SandboxRuntimePreflight(
            ready=True,
            platform_system="Linux",
            docker_available=True,
            runsc_registered=True,
            runsc_binary_available=True,
            runner_image_present=True,
            runner_image=DEFAULT_RUNNER_IMAGE,
            runtime_version="runsc-release-1",
        )
        rev = _make_revision()
        c_hash = exercise_registry.case_key(
            str(rev.exercise_id), str(rev.spec_version), {"nums": [5], "target": 5}
        )
        base_req = ExecutionRequest(
            job_id=uuid.uuid4(),
            revision=rev,
            source_code="def shortest_subarray_ge_target(nums, target):\n    return 1\n",
            input_args={"nums": [5], "target": 5},
            case_hash=c_hash,
        )

        captured_payloads: list[dict[str, Any]] = []
        captured_dirs: list[Path] = []

        def popen_valid(cmd: list[str], **_kwargs: Any) -> _FakePopenProcess:
            vol_arg = cmd[cmd.index("-v") + 1]
            host_dir = Path(vol_arg.split(":")[0])
            captured_dirs.append(host_dir)
            captured_payloads.append(
                json.loads((host_dir / "payload.json").read_text(encoding="utf-8"))
            )
            out = f'hello\n{DEFAULT_FRAME_PREFIX}{{"kind":"RETURN","return_value":1}}\n'.encode("utf-8")
            return _FakePopenProcess(stdout_bytes=out, returncode=0)

        runner_ok = GVisorSandboxRunner(
            preflight_fn=lambda: ready_preflight,
            popen_factory=popen_valid,
        )
        obs_ok = runner_ok.execute(base_req)
        assert obs_ok.kind == ExecutionObservationKind.RETURN
        assert obs_ok.return_value == 1
        assert obs_ok.stdout_excerpt == "hello"
        assert len(captured_payloads) == 1
        assert captured_payloads[0]["mode"] == "execute"
        assert captured_payloads[0]["function_name"] == "shortest_subarray_ge_target"
        assert not captured_dirs[0].exists()

        runner_oom = GVisorSandboxRunner(
            preflight_fn=lambda: ready_preflight,
            popen_factory=lambda *_a, **_kw: _FakePopenProcess(
                stdout_bytes=b"", stderr_bytes=b"Killed", returncode=137
            ),
        )
        obs_oom = runner_oom.execute(base_req)
        assert obs_oom.kind == ExecutionObservationKind.RESOURCE_LIMIT
        assert obs_oom.return_value is None

        removed_containers: list[str] = []

        def spy_cmd_runner(cmd: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            if cmd[:3] == ["docker", "rm", "-f"]:
                removed_containers.append(cmd[3])
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        runner_timeout = GVisorSandboxRunner(
            preflight_fn=lambda: ready_preflight,
            popen_factory=lambda *_a, **_kw: _FakePopenProcess(raise_timeout=True),
            command_runner=spy_cmd_runner,
        )
        obs_timeout = runner_timeout.execute(base_req)
        assert obs_timeout.kind == ExecutionObservationKind.TIMEOUT
        assert len(removed_containers) == 1
        assert removed_containers[0].startswith("vcc-sbx-")

        bool_out = f'{DEFAULT_FRAME_PREFIX}{{"kind":"RETURN","return_value":true}}\n'.encode("utf-8")
        runner_bool = GVisorSandboxRunner(
            preflight_fn=lambda: ready_preflight,
            popen_factory=lambda *_a, **_kw: _FakePopenProcess(stdout_bytes=bool_out, returncode=0),
        )
        obs_bool = runner_bool.execute(base_req)
        assert obs_bool.kind == ExecutionObservationKind.INVALID_RESULT
        assert obs_bool.return_value is None

    def test_trace_detects_tampered_source_hash(self) -> None:
        ready_preflight = SandboxRuntimePreflight(
            ready=True,
            platform_system="Linux",
            docker_available=True,
            runsc_registered=True,
            runsc_binary_available=True,
            runner_image_present=True,
            runner_image=DEFAULT_RUNNER_IMAGE,
            runtime_version="runsc-release-1",
        )
        rev = _make_revision()
        c_hash = exercise_registry.case_key(
            str(rev.exercise_id), str(rev.spec_version), {"nums": [5], "target": 5}
        )
        tampered_frame = {
            "status": "COMPLETED",
            "steps": [
                {
                    "event_id": 0,
                    "frame_id": "f1",
                    "parent_frame_id": None,
                    "call_depth": 1,
                    "source_hash": "0" * 64,
                    "source_line": 1,
                    "event_kind": TraceEventKind.CALL,
                    "attribution_status": TraceAttributionStatus.ATTRIBUTED,
                    "locals_snapshot": {"target": 5},
                    "truncated_values": [],
                }
            ],
            "total_observed": 1,
            "trace_truncated": False,
            "termination_reason": "Completed",
        }
        stdout_bytes = f"{DEFAULT_FRAME_PREFIX}{json.dumps(tampered_frame)}\n".encode("utf-8")
        runner = GVisorSandboxRunner(
            preflight_fn=lambda: ready_preflight,
            popen_factory=lambda *_a, **_kw: _FakePopenProcess(
                stdout_bytes=stdout_bytes, returncode=0
            ),
        )
        t_req = TraceRequest(
            job_id=uuid.uuid4(),
            trace_id=uuid.uuid4(),
            revision=rev,
            source_code="def shortest_subarray_ge_target(nums, target):\n    return 1\n",
            input_args={"nums": [5], "target": 5},
            case_hash=c_hash,
        )
        report = runner.trace(t_req)
        assert report.status == TraceExecutionStatus.TRACE_TAMPERED


class VerifierHarnessTests(unittest.TestCase):
    def test_syntax_error_detected_via_ast_parse_without_calling_runner(self) -> None:
        bad_code = "def shortest_subarray_ge_target(nums, target)\n    return 1\n"
        rev = _make_revision(source_code=bad_code)
        runner = _ControlledSandboxRunner()
        req = VerifyJobRequest(
            job_id=uuid.uuid4(),
            revision=rev,
            source_code=bad_code,
            run_curated_suite=True,
        )
        report = run_verification_job(req, runner)
        assert report.status == VerificationStatus.SYNTAX_ERROR
        assert report.curated_cases_run == 0
        assert report.curated_cases_total == 10
        assert len(runner.execute_calls) == 0

    def test_curated_suite_pass_returns_no_failure_found(self) -> None:
        good_code = "def shortest_subarray_ge_target(nums, target):\n    return 1\n"
        rev = _make_revision(source_code=good_code)
        runner = _ControlledSandboxRunner()
        req = VerifyJobRequest(
            job_id=uuid.uuid4(),
            revision=rev,
            source_code=good_code,
            run_curated_suite=True,
            generated_cases_target=3,
            seed=42,
        )
        report = run_verification_job(req, runner)
        assert report.status == VerificationStatus.NO_FAILURE_FOUND
        assert report.curated_cases_run == 10
        assert report.curated_cases_total == 10
        assert report.generated_cases_run == 3
        assert report.completed_stages == ["curated_suite", "generated_suite"]
        assert report.counterexample_input is None

    def test_confirmed_counterexample_requires_fresh_replay_and_checks_prior_failing_first(self) -> None:
        buggy_code = "def shortest_subarray_ge_target(nums, target):\n    return 999\n"
        rev = _make_revision(source_code=buggy_code)

        def always_wrong(_req: ExecutionRequest, _idx: int) -> ExecutionObservation:
            return ExecutionObservation(
                kind=ExecutionObservationKind.RETURN,
                return_value=999,
                duration_ms=4,
            )

        runner = _ControlledSandboxRunner(execute_fn=always_wrong)
        prior_case = {"nums": [2, 3, 1], "target": 6}
        req = VerifyJobRequest(
            job_id=uuid.uuid4(),
            revision=rev,
            source_code=buggy_code,
            prior_failing_input=prior_case,
            run_curated_suite=True,
            budget=ExecutionBudgetConfig(shrink_wall_ms=0),
        )
        report = run_verification_job(req, runner)
        assert report.status == VerificationStatus.COUNTEREXAMPLE_CONFIRMED
        assert len(runner.execute_calls) == 2
        assert runner.execute_calls[0].job_id == runner.execute_calls[1].job_id
        assert report.counterexample_input == prior_case
        assert report.reference_output == 3
        assert report.student_observation is not None
        assert report.student_observation.return_value == 999

    def test_non_deterministic_replay_returns_replay_unconfirmed(self) -> None:
        flaky_code = "def shortest_subarray_ge_target(nums, target):\n    return 0\n"
        rev = _make_revision(source_code=flaky_code)

        def flaky_exec(req: ExecutionRequest, call_idx: int) -> ExecutionObservation:
            oracle_ans = exercise_registry.evaluate(
                str(req.revision.exercise_id),
                str(req.revision.spec_version),
                req.input_args,
            )
            if call_idx == 0:
                return ExecutionObservation(
                    kind=ExecutionObservationKind.RETURN,
                    return_value=oracle_ans + 100,
                    duration_ms=3,
                )
            return ExecutionObservation(
                kind=ExecutionObservationKind.RETURN,
                return_value=oracle_ans,
                duration_ms=3,
            )

        runner = _ControlledSandboxRunner(execute_fn=flaky_exec)
        req = VerifyJobRequest(
            job_id=uuid.uuid4(),
            revision=rev,
            source_code=flaky_code,
            target_input={"nums": [5], "target": 5},
            run_curated_suite=False,
        )
        report = run_verification_job(req, runner)
        assert report.status == VerificationStatus.REPLAY_UNCONFIRMED
        assert len(runner.execute_calls) == 2

    def test_budget_exhaustion_returns_verification_incomplete_never_no_failure_found(self) -> None:
        code = "def shortest_subarray_ge_target(nums, target):\n    return 1\n"
        rev = _make_revision(source_code=code)
        fake_time = [0.0]

        def advancing_clock() -> float:
            return fake_time[0]

        def slow_exec(req: ExecutionRequest, _idx: int) -> ExecutionObservation:
            fake_time[0] += 0.6
            ans = exercise_registry.evaluate(
                str(req.revision.exercise_id),
                str(req.revision.spec_version),
                req.input_args,
            )
            return ExecutionObservation(
                kind=ExecutionObservationKind.RETURN,
                return_value=ans,
                duration_ms=600,
            )

        runner = _ControlledSandboxRunner(execute_fn=slow_exec)
        budget = ExecutionBudgetConfig(
            job_wall_ms=2500,
            replay_reserve_ms=1000,
        )
        req = VerifyJobRequest(
            job_id=uuid.uuid4(),
            revision=rev,
            source_code=code,
            run_curated_suite=True,
            budget=budget,
        )
        report = run_verification_job(req, runner, clock_fn=advancing_clock)
        assert report.status == VerificationStatus.VERIFICATION_INCOMPLETE
        assert report.status != VerificationStatus.NO_FAILURE_FOUND
        assert 0 < report.curated_cases_run < report.curated_cases_total

    def test_oracle_input_is_never_mutated_by_runner(self) -> None:
        code = "def shortest_subarray_ge_target(nums, target):\n    nums.clear()\n    return 99\n"
        rev = _make_revision(source_code=code)

        def mutating_runner(req: ExecutionRequest, _idx: int) -> ExecutionObservation:
            req.input_args["nums"].clear()
            req.input_args["nums"].append(999999)
            req.input_args["target"] = -999
            return ExecutionObservation(
                kind=ExecutionObservationKind.RETURN,
                return_value=99,
                duration_ms=2,
            )

        runner = _ControlledSandboxRunner(execute_fn=mutating_runner)
        caller_input = {"nums": [2, 3, 1], "target": 6}
        req = VerifyJobRequest(
            job_id=uuid.uuid4(),
            revision=rev,
            source_code=code,
            target_input=caller_input,
            run_curated_suite=False,
            budget=ExecutionBudgetConfig(shrink_wall_ms=0),        )
        report = run_verification_job(req, runner)
        assert report.status == VerificationStatus.COUNTEREXAMPLE_CONFIRMED
        assert caller_input == {"nums": [2, 3, 1], "target": 6}
        assert report.counterexample_input == {"nums": [2, 3, 1], "target": 6}
        assert report.reference_output == 3

    def test_unavailable_runner_returns_execution_unavailable_immediately(self) -> None:
        code = "def shortest_subarray_ge_target(nums, target):\n    return 1\n"
        rev = _make_revision(source_code=code)
        runner = _ControlledSandboxRunner(
            execute_fn=lambda _req, _idx: ExecutionObservation(
                kind=ExecutionObservationKind.UNAVAILABLE,
                error_type="SandboxUnavailableError",
                error_message="runsc runtime unavailable",
                duration_ms=1,
            )
        )
        req = VerifyJobRequest(
            job_id=uuid.uuid4(),
            revision=rev,
            source_code=code,
            run_curated_suite=True,
        )
        report = run_verification_job(req, runner)
        assert report.status == VerificationStatus.EXECUTION_UNAVAILABLE
        assert len(runner.execute_calls) == 1


class BrokerEndpointsAndWorkerClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.secret = "test-internal-worker-secret-987654"
        self.runner = _ControlledSandboxRunner()
        self.registry = ActiveJobRegistry()
        self.app = create_broker_app(
            config=BrokerConfig(
                internal_worker_secret=self.secret,
                runner_image=DEFAULT_RUNNER_IMAGE,
                max_concurrency=2,
            ),
            runner=self.runner,
            job_registry=self.registry,
        )
        self.test_client = TestClient(self.app)

    def test_broker_rejects_missing_or_invalid_secret_and_never_leaks_secret_in_health(self) -> None:
        r_missing = self.test_client.get("/internal/health")
        assert r_missing.status_code == 401

        r_wrong = self.test_client.get(
            "/internal/health",
            headers={"X-Internal-Worker-Secret": "wrong-secret"},
        )
        assert r_wrong.status_code == 401

        r_ok = self.test_client.get(
            "/internal/health",
            headers={"X-Internal-Worker-Secret": self.secret},
        )
        assert r_ok.status_code == 200
        body = r_ok.json()
        assert body["sandbox_ready"] is True
        assert self.secret not in r_ok.text

    def test_broker_cancel_endpoint_marks_job_cancelled_and_invokes_runner_cancel(self) -> None:
        job_id = uuid.uuid4()
        r_cancel = self.test_client.post(
            f"/internal/cancel/{job_id}",
            headers={"X-Internal-Worker-Secret": self.secret},
        )
        assert r_cancel.status_code == 200
        data = r_cancel.json()
        assert data["cancelled"] is True
        assert data["status"] == JobStatus.CANCELLED
        assert job_id in self.runner.cancelled_jobs

        code = "def shortest_subarray_ge_target(nums, target):\n    return 1\n"
        rev = _make_revision(source_code=code)
        v_req = VerifyJobRequest(
            job_id=job_id,
            revision=rev,
            source_code=code,
            run_curated_suite=True,
        )
        r_verify = self.test_client.post(
            "/internal/verify",
            json=v_req.model_dump(mode="json"),
            headers={"X-Internal-Worker-Secret": self.secret},
        )
        assert r_verify.status_code == 200
        assert r_verify.json()["status"] == VerificationStatus.SUPERSEDED
        assert len(self.runner.execute_calls) == 0

    def test_worker_client_enforces_public_custom_code_gate_and_secret(self) -> None:
        code = "def shortest_subarray_ge_target(nums, target):\n    return 1\n"
        rev = _make_revision(source_code=code)
        c_hash = exercise_registry.case_key(
            str(rev.exercise_id), str(rev.spec_version), {"nums": [5], "target": 5}
        )
        exec_req = ExecutionRequest(
            job_id=uuid.uuid4(),
            revision=rev,
            source_code=code,
            input_args={"nums": [5], "target": 5},
            case_hash=c_hash,
        )

        client_locked = WorkerClient(
            base_url="http://testserver",
            internal_worker_secret=self.secret,
            allow_public_custom_code=False,
            http_client=self.test_client,  # type: ignore[arg-type]
        )
        with self.assertRaises(PublicCustomCodeDisabledError):
            client_locked.submit_execution(exec_req, is_public_custom_code=True)

        client_bad_secret = WorkerClient(
            base_url="http://testserver",
            internal_worker_secret="bad-secret",
            allow_public_custom_code=True,
            http_client=self.test_client,  # type: ignore[arg-type]
        )
        with self.assertRaises(BrokerAuthenticationError):
            client_bad_secret.submit_execution(exec_req, is_public_custom_code=True)

    def test_worker_client_rejects_stale_revision_and_tombstoned_session_pre_and_post_submit(self) -> None:
        code = "def shortest_subarray_ge_target(nums, target):\n    return 1\n"
        session_id = uuid.uuid4()
        rev_v1 = _make_revision(
            session_id=session_id,
            code_version_id=1,
            source_code=code,
            turn_generation=1,
        )

        active_session_v2 = SessionRecord(
            id=str(session_id),
            token_hash="th",
            exercise_id=str(rev_v1.exercise_id),
            spec_version=str(rev_v1.spec_version),
            spec_acknowledged=True,
            language_mode="en-IN",
            interaction_mode="VOICE",
            active_code_version_id=2,
            active_turn_generation=1,
            state="READY",
            learning_state="VERIFYING",
            created_at="2026-11-13T00:00:00+00:00",
            updated_at="2026-11-13T00:00:00+00:00",
            expires_at="2026-11-14T00:00:00+00:00",
            deleted_at=None,
        )
        repo_stale = _FakeSessionRepository(active_session_v2)
        wc_stale = WorkerClient(
            base_url="http://testserver",
            internal_worker_secret=self.secret,
            session_repository=repo_stale,  # type: ignore[arg-type]
            http_client=self.test_client,  # type: ignore[arg-type]
        )
        v_req = VerifyJobRequest(
            job_id=uuid.uuid4(),
            revision=rev_v1,
            source_code=code,
            run_curated_suite=True,
        )
        handle_stale = wc_stale.submit_verify(v_req)
        assert handle_stale.status == JobStatus.SUPERSEDED
        assert handle_stale.verification_report is None
        assert len(self.runner.execute_calls) == 0

        tombstoned_session = SessionRecord(
            id=str(session_id),
            token_hash="th",
            exercise_id=str(rev_v1.exercise_id),
            spec_version=str(rev_v1.spec_version),
            spec_acknowledged=True,
            language_mode="en-IN",
            interaction_mode="VOICE",
            active_code_version_id=1,
            active_turn_generation=1,
            state="DELETED",
            learning_state="VERIFYING",
            created_at="2026-11-13T00:00:00+00:00",
            updated_at="2026-11-13T00:00:00+00:00",
            expires_at="2026-11-14T00:00:00+00:00",
            deleted_at="2026-11-13T01:00:00+00:00",
        )
        repo_tomb = _FakeSessionRepository(tombstoned_session)
        wc_tomb = WorkerClient(
            base_url="http://testserver",
            internal_worker_secret=self.secret,
            session_repository=repo_tomb,  # type: ignore[arg-type]
            http_client=self.test_client,  # type: ignore[arg-type]
        )
        handle_tomb = wc_tomb.submit_verify(v_req)
        assert handle_tomb.status == JobStatus.CANCELLED
        assert handle_tomb.verification_report is None
        assert len(self.runner.execute_calls) == 0

        fresh_session_v1 = SessionRecord(
            id=str(session_id),
            token_hash="th",
            exercise_id=str(rev_v1.exercise_id),
            spec_version=str(rev_v1.spec_version),
            spec_acknowledged=True,
            language_mode="en-IN",
            interaction_mode="VOICE",
            active_code_version_id=1,
            active_turn_generation=1,
            state="READY",
            learning_state="VERIFYING",
            created_at="2026-11-13T00:00:00+00:00",
            updated_at="2026-11-13T00:00:00+00:00",
            expires_at="2026-11-14T00:00:00+00:00",
            deleted_at=None,
        )
        repo_midflight = _FakeSessionRepository(fresh_session_v1, code_hash=rev_v1.code_hash)

        def advance_session_during_exec(req: ExecutionRequest, _idx: int) -> ExecutionObservation:
            repo_midflight.session = active_session_v2
            ans = exercise_registry.evaluate(
                str(req.revision.exercise_id),
                str(req.revision.spec_version),
                req.input_args,
            )
            return ExecutionObservation(
                kind=ExecutionObservationKind.RETURN,
                return_value=ans,
                duration_ms=3,
            )

        self.runner._execute_fn = advance_session_during_exec
        wc_midflight = WorkerClient(
            base_url="http://testserver",
            internal_worker_secret=self.secret,
            session_repository=repo_midflight,  # type: ignore[arg-type]
            http_client=self.test_client,  # type: ignore[arg-type]
        )
        mid_job_id = uuid.uuid4()
        handle_mid = wc_midflight.submit_verify(
            VerifyJobRequest(
                job_id=mid_job_id,
                revision=rev_v1,
                source_code=code,
                run_curated_suite=True,
            )
        )
        assert handle_mid.status == JobStatus.SUPERSEDED
        assert handle_mid.verification_report is None
        assert mid_job_id in self.runner.cancelled_jobs


if __name__ == "__main__":
    unittest.main()
