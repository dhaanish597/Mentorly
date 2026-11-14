"""Unit tests for disposable runner protocol, safe serializer, and trace recorder (Phase 1 / T-02)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
from typing import Any
import unittest
from uuid import uuid4

from backend.app.exercises import registry
from backend.app.models.domain import (
    ExecutionBudgetConfig,
    RevisionRef,
    TraceRequest,
)
from backend.app.models.enums import (
    ExecutionObservationKind,
    ExerciseId,
    SpecVersion,
    TraceAttributionStatus,
    TraceEventKind,
    TraceExecutionStatus,
)
from exec_worker.runner.protocol import (
    FORBIDDEN_LEARNER_KEYS,
    FRAME_BEGIN,
    FRAME_END,
    PROTOCOL_VERSION,
    ProtocolViolationError,
    build_execute_envelope,
    emit_runner_frame,
    parse_runner_frame,
)
from exec_worker.runner.run_invocation import (
    BoundedTextStream,
)
from exec_worker.tests.sandbox_acceptance import execute_payload_in_gvisor
from exec_worker.runner.safe_serializer import (
    serialize_frame_locals,
    serialize_value,
)
from exec_worker.worker_app.trace_recorder import (
    RawSandboxResult,
    record_execution_trace,
)


class HostileObject:
    """Adversarial learner object that raises if any dunder hook is called."""

    def __repr__(self) -> str:
        raise RuntimeError("hook called: __repr__!")

    def __str__(self) -> str:
        raise RuntimeError("hook called: __str__!")

    def __iter__(self) -> Any:
        raise RuntimeError("hook called: __iter__!")

    def __getattr__(self, name: str) -> Any:
        raise RuntimeError(f"hook called: __getattr__({name})!")

    def __getattribute__(self, name: str) -> Any:
        raise RuntimeError(f"hook called: __getattribute__({name})!")

    def __eq__(self, other: object) -> bool:
        raise RuntimeError("hook called: __eq__!")

    def __hash__(self) -> int:
        raise RuntimeError("hook called: __hash__!")

    def __len__(self) -> int:
        raise RuntimeError("hook called: __len__!")

    def __bool__(self) -> bool:
        raise RuntimeError("hook called: __bool__!")


class HostileKeyWithPrecomputedHash:
    def __init__(self, armed: bool = False) -> None:
        object.__setattr__(self, "_armed", armed)

    def arm(self) -> None:
        object.__setattr__(self, "_armed", True)

    def __hash__(self) -> int:
        if object.__getattribute__(self, "_armed"):
            raise RuntimeError("hook called: __hash__!")
        return 424242

    def __eq__(self, other: object) -> bool:
        if object.__getattribute__(self, "_armed"):
            raise RuntimeError("hook called: __eq__!")
        return self is other

    def __str__(self) -> str:
        raise RuntimeError("hook called: __str__!")

    def __repr__(self) -> str:
        raise RuntimeError("hook called: __repr__!")


class EvilListSubclass(list):  # type: ignore[type-arg]
    def __iter__(self) -> Any:
        raise RuntimeError("hook called on list subclass!")

    def __len__(self) -> int:
        raise RuntimeError("hook called on list subclass!")


class EvilIntSubclass(int):
    def __repr__(self) -> str:
        raise RuntimeError("hook called on int subclass!")

    def __str__(self) -> str:
        raise RuntimeError("hook called on int subclass!")


class _GVisorAcceptanceRunner:
    def __init__(self) -> None:
        from exec_worker.worker_app.sandbox_runner import GVisorSandboxRunner
        preflight = GVisorSandboxRunner().check_preflight()
        if not preflight.ready:
            raise unittest.SkipTest('BLOCKED_EXTERNAL: genuine gVisor acceptance: '+preflight.summary)

    def run_sandbox(
        self, payload: dict[str, Any], budget: ExecutionBudgetConfig
    ) -> RawSandboxResult:
        envelope = execute_payload_in_gvisor(payload, apply_rlimits=False)
        max_bytes = (
            budget.max_trace_bytes
            if payload.get("mode") == "trace"
            else budget.max_result_bytes
        )
        framed = emit_runner_frame(envelope, max_payload_bytes=max_bytes)
        return RawSandboxResult(
            stdout=framed.encode("utf-8"),
            stderr=b"",
            exit_code=0,
            duration_ms=envelope["duration_ms"],
        )


class ProtocolTests(unittest.TestCase):
    def test_valid_return_frame_roundtrip(self) -> None:
        env = build_execute_envelope(
            kind="RETURN",
            return_value=-42,
            stdout_text="debug line\n",
            stderr_text="",
            duration_ms=17,
        )
        framed = emit_runner_frame(env)
        parsed = parse_runner_frame(framed, expected_mode="execute")
        self.assertEqual(parsed.kind, "RETURN")
        self.assertIs(type(parsed.return_value), int)
        self.assertEqual(parsed.return_value, -42)
        self.assertEqual(parsed.stdout_excerpt, "debug line\n")
        self.assertEqual(parsed.duration_ms, 17)

    def test_float_null_object_and_nested_return_rejected_as_invalid_result(self) -> None:
        for non_int_val in (1.0, 0.0, None, {"a": 1}, [[1]], 2**53):
            with self.subTest(val=repr(non_int_val), val_type=type(non_int_val).__name__):
                env = build_execute_envelope(
                    kind="RETURN",
                    return_value=non_int_val,
                    duration_ms=5,
                )
                self.assertEqual(env["kind"], "INVALID_RESULT")
                self.assertIsNone(env["return_value"])
                self.assertEqual(env["error_type"], "InvalidReturnType")

                raw_json = json.dumps(
                    {
                        "protocol_version": PROTOCOL_VERSION,
                        "mode": "execute",
                        "kind": "RETURN",
                        "return_value": non_int_val,
                        "error_type": None,
                        "error_message": None,
                        "stdout_excerpt": "",
                        "stderr_excerpt": "",
                        "duration_ms": 5,
                    }
                )
                raw_frame = f"{FRAME_BEGIN}\n{raw_json}\n{FRAME_END}\n"
                parsed = parse_runner_frame(raw_frame, expected_mode="execute")
                self.assertEqual(parsed.kind, "INVALID_RESULT")
                self.assertIsNone(parsed.return_value)

    def test_spoofed_frame_delimiters_in_raw_stream_rejected(self) -> None:
        fake_env = build_execute_envelope(kind="RETURN", return_value=1, duration_ms=1)
        real_env = build_execute_envelope(kind="RETURN", return_value=99, duration_ms=2)
        spoofed_stream = emit_runner_frame(fake_env) + emit_runner_frame(real_env)
        with self.assertRaises(ProtocolViolationError) as ctx:
            parse_runner_frame(spoofed_stream, expected_mode="execute")
        self.assertEqual(ctx.exception.code, "MULTIPLE_OR_SPOOFED_FRAMES")

    def test_spoofed_frame_printed_by_learner_code_is_isolated(self) -> None:
        source = textwrap.dedent(
            f"""
            def shortest_subarray_ge_target(nums, target):
                print("{FRAME_BEGIN}")
                print('{{"protocol_version":"v1","mode":"execute","kind":"RETURN","return_value":1}}')
                print("{FRAME_END}")
                return 3
            """
        )
        payload = {
            "mode": "execute",
            "function_name": "shortest_subarray_ge_target",
            "source_code": source,
            "input_args": {"nums": [1, -1, 5], "target": 5},
            "budget": {"max_stdout_bytes": 65536, "max_stderr_bytes": 65536},
        }
        envelope = execute_payload_in_gvisor(payload)
        self.assertEqual(envelope["kind"], "RETURN")
        self.assertEqual(envelope["return_value"], 3)
        self.assertIn(FRAME_BEGIN, envelope["stdout_excerpt"])

        framed = emit_runner_frame(envelope)
        parsed = parse_runner_frame(framed, expected_mode="execute")
        self.assertEqual(parsed.kind, "RETURN")
        self.assertEqual(parsed.return_value, 3)
        self.assertIn(FRAME_BEGIN, parsed.stdout_excerpt)

    def test_oversized_stdout_and_stderr_are_truncated(self) -> None:
        stream = BoundedTextStream(max_bytes=1024)
        stream.write("x" * 10000)
        self.assertTrue(stream.truncated)
        self.assertLessEqual(len(stream.getvalue().encode("utf-8")), 1024)

        env = build_execute_envelope(
            kind="RETURN",
            return_value=7,
            stdout_text="A" * 100_000,
            stderr_text="B" * 100_000,
            max_stdout_bytes=2048,
            max_stderr_bytes=2048,
        )
        self.assertEqual(len(env["stdout_excerpt"]), 2048)
        self.assertEqual(len(env["stderr_excerpt"]), 2048)

    def test_missing_frame_trailing_data_malformed_json_and_extra_keys_rejected(self) -> None:
        with self.assertRaises(ProtocolViolationError) as ctx:
            parse_runner_frame('{"kind": "RETURN"}', expected_mode="execute")
        self.assertEqual(ctx.exception.code, "MISSING_FRAME")

        valid_env = build_execute_envelope(kind="RETURN", return_value=10)
        framed = emit_runner_frame(valid_env) + "trailing_garbage"
        with self.assertRaises(ProtocolViolationError) as ctx:
            parse_runner_frame(framed, expected_mode="execute")
        self.assertEqual(ctx.exception.code, "TRAILING_DATA_AFTER_FRAME_END")

        with self.assertRaises(ProtocolViolationError) as ctx:
            parse_runner_frame("leading_garbage\n" + emit_runner_frame(valid_env))
        self.assertEqual(ctx.exception.code, "UNFRAMED_LEADING_DATA")

        with self.assertRaises(ProtocolViolationError) as ctx:
            parse_runner_frame(f"{FRAME_BEGIN}\n{{not_valid_json}}\n{FRAME_END}\n")
        self.assertEqual(ctx.exception.code, "MALFORMED_JSON")

        bad_dict = dict(valid_env)
        bad_dict["unexpected_extra_field"] = 123
        bad_frame = f"{FRAME_BEGIN}\n{json.dumps(bad_dict)}\n{FRAME_END}\n"
        with self.assertRaises(ProtocolViolationError) as ctx:
            parse_runner_frame(bad_frame, expected_mode="execute")
        self.assertEqual(ctx.exception.code, "UNEXPECTED_KEYS")

        for forbidden_key in FORBIDDEN_LEARNER_KEYS:
            with self.subTest(forbidden_key=forbidden_key):
                poisoned = dict(valid_env)
                poisoned[forbidden_key] = "spoofed"
                with self.assertRaises(ProtocolViolationError) as ctx:
                    emit_runner_frame(poisoned)
                self.assertEqual(ctx.exception.code, "FORBIDDEN_KEY")

                raw_poisoned = f"{FRAME_BEGIN}\n{json.dumps(poisoned)}\n{FRAME_END}\n"
                with self.assertRaises(ProtocolViolationError) as ctx2:
                    parse_runner_frame(raw_poisoned, expected_mode="execute")
                self.assertEqual(ctx2.exception.code, "FORBIDDEN_KEY")

        with self.assertRaises(ProtocolViolationError) as ctx:
            parse_runner_frame(
                emit_runner_frame(valid_env),
                expected_mode="execute",
                max_result_bytes=16,
            )
        self.assertIn(
            ctx.exception.code,
            ("FRAME_BYTE_CAP_EXCEEDED", "PAYLOAD_BYTE_CAP_EXCEEDED"),
        )


class SafeSerializerTests(unittest.TestCase):
    def test_hostile_objects_never_trigger_dunder_hooks(self) -> None:
        hostile = HostileObject()
        hostile_key = HostileKeyWithPrecomputedHash(armed=False)
        container_with_hostile = {
            "obj": hostile,
            "nested": [hostile, (1, hostile)],
            "set_val": {hostile_key},
        }
        hostile_dict: dict[Any, Any] = {hostile_key: hostile}
        hostile_key.arm()

        locals_map = {
            "x": 10,
            "hostile": hostile,
            "container": container_with_hostile,
            "hostile_dict": hostile_dict,
            "evil_list": EvilListSubclass([1, 2, 3]),
            "evil_int": EvilIntSubclass(99),
        }

        snapshot, _ = serialize_frame_locals(locals_map)
        self.assertEqual(snapshot["x"], 10)
        self.assertEqual(
            snapshot["hostile"], {"__vcc_untrusted_type__": "HostileObject"}
        )
        self.assertEqual(
            snapshot["evil_list"], {"__vcc_untrusted_type__": "EvilListSubclass"}
        )
        self.assertEqual(
            snapshot["evil_int"], {"__vcc_untrusted_type__": "EvilIntSubclass"}
        )
        self.assertEqual(
            snapshot["container"]["obj"],
            {"__vcc_untrusted_type__": "HostileObject"},
        )
        self.assertEqual(
            snapshot["hostile_dict"]["<untrusted_key:HostileKeyWithPrecomputedHash>"],
            {"__vcc_untrusted_type__": "HostileObject"},
        )

    def test_cycle_detection_in_list_and_dict(self) -> None:
        cyclic_list: list[Any] = [1, 2]
        cyclic_list.append(cyclic_list)

        cyclic_dict: dict[str, Any] = {"a": 1}
        cyclic_dict["self"] = cyclic_dict

        res_list = serialize_value(cyclic_list, root_path="cyclic_list")
        self.assertEqual(res_list.value[0], 1)
        self.assertEqual(res_list.value[1], 2)
        self.assertEqual(res_list.value[2], {"__vcc_cycle__": "list"})
        self.assertIn("cyclic_list[2]:cycle", res_list.truncated_values)

        res_dict = serialize_value(cyclic_dict, root_path="cyclic_dict")
        self.assertEqual(res_dict.value["a"], 1)
        self.assertEqual(res_dict.value["self"], {"__vcc_cycle__": "dict"})
        self.assertIn("cyclic_dict.self:cycle", res_dict.truncated_values)

    def test_depth_items_string_int_bits_and_nodes_truncation(self) -> None:
        deep: Any = 42
        for _ in range(6):
            deep = [deep]
        res_deep = serialize_value(deep, max_depth=4, root_path="deep")
        self.assertTrue(any("max_depth" in t for t in res_deep.truncated_values))

        many_items = list(range(35))
        res_items = serialize_value(many_items, max_items=20, root_path="nums")
        self.assertEqual(len(res_items.value), 20)
        self.assertIn("nums:max_items", res_items.truncated_values)

        long_str = "abcd" * 50
        res_str = serialize_value(long_str, max_str_len=128, root_path="s")
        self.assertIn("s:max_str_len", res_str.truncated_values)
        self.assertTrue(res_str.value.endswith("...[truncated]"))

        huge_int = 1 << 300
        res_int = serialize_value(huge_int, max_int_bits=256, root_path="big")
        self.assertIn("big:max_int_bits", res_int.truncated_values)
        self.assertEqual(res_int.value["__vcc_truncated__"], "max_int_bits")

        wide_tree = [[i, i + 1, i + 2] for i in range(10)]
        res_nodes = serialize_value(wide_tree, max_nodes=15, root_path="tree")
        self.assertTrue(any("max_nodes" in t for t in res_nodes.truncated_values))


class TraceRecorderAndRunnerTests(unittest.TestCase):
    def test_post_line_variable_mutation_accuracy_on_ex3_bug(self) -> None:
        source = textwrap.dedent(
            """\
            def max_product_subarray(nums: list[int]) -> int:
                hi = nums[0]
                lo = nums[0]
                ans = nums[0]
                for x in nums[1:]:
                    hi = max(x, hi * x, lo * x)
                    lo = min(x, hi * x, lo * x)
                    ans = max(ans, hi)
                return ans
            """
        )
        source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        payload = {
            "mode": "trace",
            "function_name": "max_product_subarray",
            "source_code": source,
            "source_hash": source_hash,
            "input_args": {"nums": [-3, -3, -3]},
            "budget": {
                "max_trace_steps": 250,
                "max_trace_snapshots_work": 2000,
            },
        }
        envelope = execute_payload_in_gvisor(payload)
        self.assertEqual(envelope["kind"], "RETURN")
        self.assertEqual(envelope["return_value"], 81)
        self.assertEqual(envelope["trace_status"], "COMPLETED")

        steps = envelope["steps"]
        line_steps = [s for s in steps if s["event_kind"] == "LINE"]

        line2_step = next(s for s in line_steps if s["source_line"] == 2)
        self.assertEqual(line2_step["locals_snapshot"].get("hi"), -3)
        self.assertNotIn("lo", line2_step["locals_snapshot"])

        line6_first = next(s for s in line_steps if s["source_line"] == 6)
        self.assertEqual(line6_first["locals_snapshot"]["hi"], 9)
        self.assertEqual(line6_first["locals_snapshot"]["lo"], -3)

        line7_first = next(s for s in line_steps if s["source_line"] == 7)
        self.assertEqual(line7_first["locals_snapshot"]["hi"], 9)
        self.assertEqual(line7_first["locals_snapshot"]["lo"], -27)

    def test_recursion_frame_ids_and_call_depth(self) -> None:
        source = textwrap.dedent(
            """\
            def first_at_least(nums: list[int], target: int) -> int:
                def helper(idx: int) -> int:
                    if idx >= len(nums):
                        return -1
                    if nums[idx] >= target:
                        return idx
                    return helper(idx + 1)
                return helper(0)
            """
        )
        payload = {
            "mode": "trace",
            "function_name": "first_at_least",
            "source_code": source,
            "input_args": {"nums": [1, 3, 5], "target": 5},
            "budget": {"max_trace_steps": 250, "max_trace_snapshots_work": 2000},
        }
        envelope = execute_payload_in_gvisor(payload)
        self.assertEqual(envelope["kind"], "RETURN")
        self.assertEqual(envelope["return_value"], 2)

        call_steps = [s for s in envelope["steps"] if s["event_kind"] == "CALL"]
        self.assertEqual(len(call_steps), 4)
        self.assertEqual(call_steps[0]["frame_id"], "f1")
        self.assertIsNone(call_steps[0]["parent_frame_id"])
        self.assertEqual(call_steps[0]["call_depth"], 1)

        self.assertEqual(call_steps[1]["frame_id"], "f2")
        self.assertEqual(call_steps[1]["parent_frame_id"], "f1")
        self.assertEqual(call_steps[1]["call_depth"], 2)

        self.assertEqual(call_steps[2]["frame_id"], "f3")
        self.assertEqual(call_steps[2]["parent_frame_id"], "f2")
        self.assertEqual(call_steps[2]["call_depth"], 3)

        self.assertEqual(call_steps[3]["frame_id"], "f4")
        self.assertEqual(call_steps[3]["parent_frame_id"], "f3")
        self.assertEqual(call_steps[3]["call_depth"], 4)

    def test_ring_buffer_truncation_at_250_steps(self) -> None:
        source = textwrap.dedent(
            """\
            def shortest_subarray_ge_target(nums: list[int], target: int) -> int:
                acc = 0
                for i in range(180):
                    acc += 1
                return acc
            """
        )
        payload = {
            "mode": "trace",
            "function_name": "shortest_subarray_ge_target",
            "source_code": source,
            "input_args": {"nums": [1], "target": 1},
            "budget": {
                "max_trace_steps": 250,
                "max_trace_snapshots_work": 2000,
            },
        }
        envelope = execute_payload_in_gvisor(payload)
        self.assertEqual(envelope["kind"], "RETURN")
        self.assertEqual(envelope["return_value"], 180)
        self.assertEqual(envelope["trace_status"], "PARTIAL")
        self.assertTrue(envelope["trace_truncated"])
        self.assertGreater(envelope["total_observed"], 250)

        steps = envelope["steps"]
        self.assertEqual(len(steps), 250)
        self.assertEqual([s["event_id"] for s in steps[:200]], list(range(200)))
        total = envelope["total_observed"]
        self.assertEqual(
            [s["event_id"] for s in steps[200:]],
            list(range(total - 50, total)),
        )

    def test_snapshot_work_cap_stops_trace_cleanly_without_killing_function(self) -> None:
        source = textwrap.dedent(
            """\
            def shortest_subarray_ge_target(nums: list[int], target: int) -> int:
                total = 0
                for i in range(1500):
                    total += 1
                return 1 if total == 1500 else 0
            """
        )
        payload = {
            "mode": "trace",
            "function_name": "shortest_subarray_ge_target",
            "source_code": source,
            "input_args": {"nums": [5], "target": 5},
            "budget": {
                "max_trace_steps": 250,
                "max_trace_snapshots_work": 2000,
            },
        }
        envelope = execute_payload_in_gvisor(payload)
        self.assertEqual(envelope["kind"], "RETURN")
        self.assertEqual(envelope["return_value"], 1)
        self.assertEqual(envelope["trace_status"], "PARTIAL")
        self.assertTrue(envelope["trace_truncated"])
        self.assertEqual(envelope["total_observed"], 2000)
        self.assertEqual(len(envelope["steps"]), 250)
        self.assertIn("max_trace_snapshots_work", envelope["termination_reason"])

    def test_trace_tampering_detection_via_sys_settrace_none(self) -> None:
        source = textwrap.dedent(
            """\
            import sys

            def shortest_subarray_ge_target(nums: list[int], target: int) -> int:
                x = 1
                sys.settrace(None)
                x = 2
                return x
            """
        )
        code_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        input_args = {"nums": [1, -1, 5], "target": 5}
        case_hash = registry.case_key(
            "ex1_shortest_subarray", "v2_negatives_allowed", input_args
        )
        req = TraceRequest(
            job_id=uuid4(),
            trace_id=uuid4(),
            revision=RevisionRef(
                session_id=uuid4(),
                exercise_id=ExerciseId.EX1_SHORTEST_SUBARRAY,
                spec_version=SpecVersion.EX1_V2_NEGATIVES_ALLOWED,
                code_version_id=1,
                code_hash=code_hash,
                turn_generation=1,
            ),
            source_code=source,
            input_args=input_args,
            case_hash=case_hash,
        )
        runner = _GVisorAcceptanceRunner()
        report = record_execution_trace(req, runner)
        self.assertEqual(report.status, TraceExecutionStatus.TRACE_TAMPERED)
        self.assertTrue(
            any(
                s.attribution_status == TraceAttributionStatus.TAMPERED
                for s in report.steps
            )
        )

    def test_exception_in_learner_code_labels_step_ambiguous(self) -> None:
        source = textwrap.dedent(
            """\
            def shortest_subarray_ge_target(nums: list[int], target: int) -> int:
                a = 10
                b = 0
                return a // b
            """
        )
        code_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        input_args = {"nums": [1, -1, 5], "target": 5}
        case_hash = registry.case_key(
            "ex1_shortest_subarray", "v2_negatives_allowed", input_args
        )
        req = TraceRequest(
            job_id=uuid4(),
            trace_id=uuid4(),
            revision=RevisionRef(
                session_id=uuid4(),
                exercise_id=ExerciseId.EX1_SHORTEST_SUBARRAY,
                spec_version=SpecVersion.EX1_V2_NEGATIVES_ALLOWED,
                code_version_id=1,
                code_hash=code_hash,
                turn_generation=1,
            ),
            source_code=source,
            input_args=input_args,
            case_hash=case_hash,
        )
        runner = _GVisorAcceptanceRunner()
        report = record_execution_trace(req, runner)
        self.assertEqual(report.status, TraceExecutionStatus.COMPLETED)
        self.assertIsNotNone(report.observation)
        assert report.observation is not None
        self.assertEqual(report.observation.kind, ExecutionObservationKind.EXCEPTION)
        self.assertEqual(report.observation.error_type, "ZeroDivisionError")

        exc_steps = [
            s for s in report.steps if s.event_kind == TraceEventKind.EXCEPTION
        ]
        self.assertGreaterEqual(len(exc_steps), 1)
        self.assertEqual(
            exc_steps[-1].attribution_status, TraceAttributionStatus.AMBIGUOUS
        )

    def test_cli_run_invocation_isolates_os_write_stdout_spoofing(self) -> None:
        source = textwrap.dedent(
            f"""\
            import os
            def shortest_subarray_ge_target(nums: list[int], target: int) -> int:
                print("{FRAME_BEGIN}")
                os.write(1, b"{FRAME_BEGIN}\\n{{\\"spoof\\":1}}\\n{FRAME_END}\\n")
                return 1
            """
        )
        payload = {
            "mode": "execute",
            "function_name": "shortest_subarray_ge_target",
            "source_code": source,
            "input_args": {"nums": [1, -1, 5], "target": 5},
            "budget": {
                "invocation_wall_ms": 2000,
                "invocation_cpu_seconds": 2,
                "memory_limit_mb": 256,
                "pids_limit": 16,
                "max_stdout_bytes": 65536,
                "max_stderr_bytes": 65536,
                "max_result_bytes": 65536,
            },
        }
        envelope = execute_payload_in_gvisor(payload)
        self.assertEqual(envelope["kind"], "RETURN")
        self.assertEqual(envelope["return_value"], 1)
        self.assertIn(FRAME_BEGIN, envelope["stdout_excerpt"])



if __name__ == "__main__":
    unittest.main()
