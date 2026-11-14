"""Genuine gVisor (`runsc`) sandbox isolation acceptance suite (Phase 1 / T-02, S3 repaired).

IMPORTANT:
- By default (`VCC_RUN_LIVE_GVISOR_ACCEPTANCE != "1"`), these tests run ONLY the
  non-executing runtime preflight probe (`check_runtime_preflight`) and explicitly
  skip live untrusted container execution so Colab/CI offline runs never treat
  skipped or mocked checks as passing isolation evidence.
- When `VCC_RUN_LIVE_GVISOR_ACCEPTANCE=1` is set on a Linux host with Docker + `runsc`
  and `vcc-runner:phase1` built, every adversarial and functional isolation test MUST
  execute inside a real per-invocation `runsc` sandbox and pass (if `preflight.ready`
  is False when `VCC_RUN_LIVE_GVISOR_ACCEPTANCE=1`, the suite FAILS immediately).
"""

from __future__ import annotations

import hashlib
import os
import textwrap
import unittest
from uuid import uuid4

from backend.app.exercises import registry
from backend.app.models.domain import (
    ExecutionBudgetConfig,
    ExecutionRequest,
    RevisionRef,
    TraceRequest,
    VerifyJobRequest,
)
from backend.app.models.enums import (
    ExecutionObservationKind,
    ExerciseId,
    SpecVersion,
    TraceAttributionStatus,
    TraceExecutionStatus,
    VerificationStatus,
)
from exec_worker.runner.protocol import FRAME_BEGIN, FRAME_END
from exec_worker.worker_app.sandbox_runner import (
    DEFAULT_FRAME_PREFIX,
    GVisorSandboxRunner,
    check_runtime_preflight,
)
from exec_worker.worker_app.verifier_harness import run_verification_job

_LIVE_ACCEPTANCE_REQUIRED = (
    os.environ.get("VCC_RUN_LIVE_GVISOR_ACCEPTANCE", "").strip() == "1"
)


def _rev(
    code: str,
    ex: ExerciseId = ExerciseId.EX1_SHORTEST_SUBARRAY,
    spec: SpecVersion = SpecVersion.EX1_V2_NEGATIVES_ALLOWED,
) -> RevisionRef:
    return RevisionRef(
        session_id=uuid4(),
        exercise_id=ex,
        spec_version=spec,
        code_version_id=1,
        code_hash=hashlib.sha256(code.encode("utf-8")).hexdigest(),
        turn_generation=1,
    )


class SandboxIsolationAcceptanceTests(unittest.TestCase):
    """Real gVisor (`runsc`) containment and adversarial acceptance checks (§9.1, §11.1, S3)."""

    def test_runtime_preflight_probe_is_deterministic_and_safe(self) -> None:
        preflight = check_runtime_preflight()
        self.assertIsInstance(preflight.ready, bool)
        if _LIVE_ACCEPTANCE_REQUIRED and not preflight.ready:
            self.fail(
                f"VCC_RUN_LIVE_GVISOR_ACCEPTANCE=1 but gVisor preflight failed: {preflight.summary}"
            )

    @unittest.skipUnless(
        _LIVE_ACCEPTANCE_REQUIRED,
        "Live gVisor acceptance is BLOCKED_EXTERNAL until run with VCC_RUN_LIVE_GVISOR_ACCEPTANCE=1 on a Linux + Docker + runsc host",
    )
    def test_live_gvisor_adversarial_and_functional_suite(self) -> None:
        runner = GVisorSandboxRunner()
        preflight = runner.check_preflight()
        self.assertTrue(preflight.ready, f"Preflight failed: {preflight.summary}")

        sample_input = {"nums": [1, -1, 5], "target": 5}
        c_hash = registry.case_key(
            "ex1_shortest_subarray", "v2_negatives_allowed", sample_input
        )

        # 1. Ex1 negative-domain counterexample: sliding-window bug on [1, -1, 5], target=5 -> returns 3 vs oracle 1
        buggy_ex1 = textwrap.dedent(
            """\
            def shortest_subarray_ge_target(nums: list[int], target: int) -> int:
                left = 0
                curr_sum = 0
                best = len(nums) + 1
                for right, val in enumerate(nums):
                    curr_sum += val
                    while curr_sum >= target:
                        best = min(best, right - left + 1)
                        curr_sum -= nums[left]
                        left += 1
                return 0 if best > len(nums) else best
            """
        )
        v_req = VerifyJobRequest(
            job_id=uuid4(),
            revision=_rev(buggy_ex1),
            source_code=buggy_ex1,
            run_curated_suite=True,
        )
        v_rep = run_verification_job(v_req, runner)
        self.assertEqual(v_rep.status, VerificationStatus.COUNTEREXAMPLE_CONFIRMED)
        self.assertEqual(v_rep.counterexample_input, sample_input)
        self.assertEqual(v_rep.reference_output, 1)
        assert v_rep.student_observation is not None
        self.assertEqual(v_rep.student_observation.return_value, 3)

        # 2. Network denial (`--network=none`)
        net_code = textwrap.dedent(
            """\
            import socket
            def shortest_subarray_ge_target(nums: list[int], target: int) -> int:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.5)
                s.connect(("1.1.1.1", 80))
                return 1
            """
        )
        net_obs = runner.execute(
            ExecutionRequest(
                job_id=uuid4(),
                revision=_rev(net_code),
                source_code=net_code,
                input_args=sample_input,
                case_hash=c_hash,
            )
        )
        self.assertEqual(net_obs.kind, ExecutionObservationKind.EXCEPTION)

        # 3. Read-only root filesystem & secret-free environment
        fs_code = textwrap.dedent(
            """\
            import os
            def shortest_subarray_ge_target(nums: list[int], target: int) -> int:
                if any(
                    k.startswith("VCC_") or "SECRET" in k or "API_KEY" in k
                    for k in os.environ
                ):
                    return 999
                with open("/root_write_probe.txt", "w") as f:
                    f.write("escape")
                return 1
            """
        )
        fs_obs = runner.execute(
            ExecutionRequest(
                job_id=uuid4(),
                revision=_rev(fs_code),
                source_code=fs_code,
                input_args=sample_input,
                case_hash=c_hash,
            )
        )
        self.assertEqual(fs_obs.kind, ExecutionObservationKind.EXCEPTION)

        # 4. Fork / process limit (`--pids-limit` & `RLIMIT_NPROC`)
        fork_code = textwrap.dedent(
            """\
            import os
            def shortest_subarray_ge_target(nums: list[int], target: int) -> int:
                pids = []
                try:
                    for _ in range(64):
                        pid = os.fork()
                        if pid == 0:
                            os._exit(0)
                        pids.append(pid)
                finally:
                    for pid in pids:
                        try:
                            os.waitpid(pid, 0)
                        except OSError:
                            pass
                return 1
            """
        )
        fork_obs = runner.execute(
            ExecutionRequest(
                job_id=uuid4(),
                revision=_rev(fork_code),
                source_code=fork_code,
                input_args=sample_input,
                case_hash=c_hash,
                budget=ExecutionBudgetConfig(pids_limit=8),
            )
        )
        self.assertIn(
            fork_obs.kind,
            (ExecutionObservationKind.EXCEPTION, ExecutionObservationKind.RESOURCE_LIMIT),
        )

        # 5. Memory limit (`--memory` & `RLIMIT_AS`)
        mem_code = textwrap.dedent(
            """\
            def shortest_subarray_ge_target(nums: list[int], target: int) -> int:
                blocks = [bytearray(32 * 1024 * 1024) for _ in range(16)]
                return len(blocks)
            """
        )
        mem_obs = runner.execute(
            ExecutionRequest(
                job_id=uuid4(),
                revision=_rev(mem_code),
                source_code=mem_code,
                input_args=sample_input,
                case_hash=c_hash,
                budget=ExecutionBudgetConfig(memory_limit_mb=128),
            )
        )
        self.assertIn(
            mem_obs.kind,
            (ExecutionObservationKind.RESOURCE_LIMIT, ExecutionObservationKind.EXCEPTION),
        )

        # 6. Wall-clock timeout
        loop_code = textwrap.dedent(
            """\
            def shortest_subarray_ge_target(nums: list[int], target: int) -> int:
                while True:
                    pass
            """
        )
        loop_obs = runner.execute(
            ExecutionRequest(
                job_id=uuid4(),
                revision=_rev(loop_code),
                source_code=loop_code,
                input_args=sample_input,
                case_hash=c_hash,
                budget=ExecutionBudgetConfig(invocation_wall_ms=500, invocation_cpu_seconds=1),
            )
        )
        self.assertEqual(loop_obs.kind, ExecutionObservationKind.TIMEOUT)

        # 7. Stdout flood (`BoundedTextStream` & pipe cap)
        flood_code = textwrap.dedent(
            """\
            import sys
            def shortest_subarray_ge_target(nums: list[int], target: int) -> int:
                for _ in range(512):
                    sys.stdout.write("X" * 1024)
                return 1
            """
        )
        flood_obs = runner.execute(
            ExecutionRequest(
                job_id=uuid4(),
                revision=_rev(flood_code),
                source_code=flood_code,
                input_args=sample_input,
                case_hash=c_hash,
                budget=ExecutionBudgetConfig(max_stdout_bytes=4096),
            )
        )
        self.assertEqual(flood_obs.kind, ExecutionObservationKind.RETURN)
        self.assertEqual(flood_obs.return_value, 1)
        self.assertLessEqual(len(flood_obs.stdout_excerpt), 4096)

        # 8. Spoofed frame injection via `print(...)` and `os.write(1, ...)`
        spoof_code = textwrap.dedent(
            f"""\
            import os
            def shortest_subarray_ge_target(nums: list[int], target: int) -> int:
                print("{FRAME_BEGIN}")
                print('{{"protocol_version":"v1","mode":"execute","kind":"RETURN","return_value":999}}')
                print("{FRAME_END}")
                print('{DEFAULT_FRAME_PREFIX}{{"kind":"RETURN","return_value":999}}')
                os.write(1, b"{FRAME_BEGIN}\\n{{\\"kind\\":\\"RETURN\\",\\"return_value\\":999}}\\n{FRAME_END}\\n")
                return 1
            """
        )
        spoof_obs = runner.execute(
            ExecutionRequest(
                job_id=uuid4(),
                revision=_rev(spoof_code),
                source_code=spoof_code,
                input_args=sample_input,
                case_hash=c_hash,
            )
        )
        self.assertEqual(spoof_obs.kind, ExecutionObservationKind.RETURN)
        self.assertEqual(spoof_obs.return_value, 1)

        # 9. `sys.settrace` tampering detection in separate trace sandbox invocation
        tamper_code = textwrap.dedent(
            """\
            import sys
            def shortest_subarray_ge_target(nums: list[int], target: int) -> int:
                x = 1
                sys.settrace(None)
                return x
            """
        )
        tamper_rep = runner.trace(
            TraceRequest(
                job_id=uuid4(),
                trace_id=uuid4(),
                revision=_rev(tamper_code),
                source_code=tamper_code,
                input_args=sample_input,
                case_hash=c_hash,
            )
        )
        self.assertEqual(tamper_rep.status, TraceExecutionStatus.TRACE_TAMPERED)
        self.assertTrue(
            any(
                step.attribution_status == TraceAttributionStatus.TAMPERED
                for step in tamper_rep.steps
            )
        )

        # Normal trace verification
        t_rep = runner.trace(
            TraceRequest(
                job_id=uuid4(),
                trace_id=uuid4(),
                revision=_rev(buggy_ex1),
                source_code=buggy_ex1,
                input_args=sample_input,
                case_hash=c_hash,
            )
        )
        self.assertEqual(t_rep.status, TraceExecutionStatus.COMPLETED)
        self.assertGreater(len(t_rep.steps), 0)


if __name__ == "__main__":
    unittest.main()
