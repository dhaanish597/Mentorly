"""Broker-side trace recorder and re-exported in-sandbox tracer (§9.4, R1 & R4 repaired)."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import inspect
import sys
from typing import Any, Callable, Protocol, runtime_checkable

from exec_worker.runner.in_sandbox_tracer import (
    InSandboxTraceOutput,
    InSandboxTracer,
    LEARNER_FILENAME,
)
from exec_worker.runner.protocol import (
    ParsedRunnerOutput,
    ProtocolViolationError,
    parse_runner_frame,
)

try:
    from backend.app.exercises import registry
    from backend.app.models.domain import (
        ExecutionBudgetConfig,
        ExecutionObservation,
        TraceExecutionReport,
        TraceRequest,
        TraceStep,
    )
    from backend.app.models.enums import (
        ExecutionObservationKind,
        TraceAttributionStatus,
        TraceEventKind,
        TraceExecutionStatus,
    )
except ImportError:  # pragma: no cover
    from app.exercises import registry  # type: ignore[no-redef]
    from app.models.domain import (  # type: ignore[no-redef]
        ExecutionBudgetConfig,
        ExecutionObservation,
        TraceExecutionReport,
        TraceRequest,
        TraceStep,
    )
    from app.models.enums import (  # type: ignore[no-redef]
        ExecutionObservationKind,
        TraceAttributionStatus,
        TraceEventKind,
        TraceExecutionStatus,
    )


DEFAULT_RUNTIME_VERSION = (
    f"python-{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
)


@dataclass(frozen=True)
class RawSandboxResult:
    stdout: bytes | str = b""
    stderr: bytes | str = b""
    exit_code: int = 0
    timed_out: bool = False
    resource_exceeded: bool = False
    unavailable: bool = False
    unavailable_reason: str | None = None
    duration_ms: int = 0
    runtime_version: str = DEFAULT_RUNTIME_VERSION


@runtime_checkable
class SandboxRunnerProtocol(Protocol):
    def run_sandbox(
        self, payload: dict[str, Any], budget: ExecutionBudgetConfig
    ) -> RawSandboxResult | ParsedRunnerOutput | dict[str, Any]:
        ...


def _coerce_runner_result(
    raw_result: RawSandboxResult | ParsedRunnerOutput | dict[str, Any],
    *,
    budget: ExecutionBudgetConfig,
) -> tuple[ParsedRunnerOutput | None, str | None, str, int]:
    if isinstance(raw_result, ParsedRunnerOutput):
        return raw_result, None, DEFAULT_RUNTIME_VERSION, raw_result.duration_ms

    if isinstance(raw_result, RawSandboxResult):
        runtime_ver = raw_result.runtime_version or DEFAULT_RUNTIME_VERSION
        if raw_result.unavailable:
            return (
                None,
                "UNAVAILABLE",
                raw_result.unavailable_reason or "Sandbox runtime is unavailable",
                raw_result.duration_ms,
            )
        if raw_result.timed_out:
            try:
                parsed = parse_runner_frame(
                    raw_result.stdout,
                    expected_mode="trace",
                    max_result_bytes=budget.max_result_bytes,
                    max_trace_bytes=budget.max_trace_bytes,
                    max_stdout_bytes=budget.max_stdout_bytes,
                    max_stderr_bytes=budget.max_stderr_bytes,
                    max_trace_steps=budget.max_trace_steps,
                )
                return parsed, "TIMEOUT", runtime_ver, raw_result.duration_ms
            except ProtocolViolationError:
                return (
                    None,
                    "TIMEOUT",
                    "Trace sandbox timed out before emitting a complete protocol frame",
                    raw_result.duration_ms,
                )
        if raw_result.resource_exceeded:
            return (
                None,
                "RESOURCE_LIMIT",
                "Trace sandbox exceeded configured memory/process resource limit",
                raw_result.duration_ms,
            )

        parsed = parse_runner_frame(
            raw_result.stdout,
            expected_mode="trace",
            max_result_bytes=budget.max_result_bytes,
            max_trace_bytes=budget.max_trace_bytes,
            max_stdout_bytes=budget.max_stdout_bytes,
            max_stderr_bytes=budget.max_stderr_bytes,
            max_trace_steps=budget.max_trace_steps,
        )
        return parsed, None, runtime_ver, raw_result.duration_ms

    if type(raw_result) is dict:
        runtime_ver = str(raw_result.get("runtime_version") or DEFAULT_RUNTIME_VERSION)
        duration_ms = (
            raw_result["duration_ms"]
            if type(raw_result.get("duration_ms")) is int
            else 0
        )
        if raw_result.get("unavailable"):
            return (
                None,
                "UNAVAILABLE",
                str(raw_result.get("unavailable_reason") or "Sandbox runtime unavailable"),
                duration_ms,
            )
        if raw_result.get("timed_out"):
            if "stdout" in raw_result and raw_result["stdout"]:
                try:
                    parsed = parse_runner_frame(
                        raw_result["stdout"],
                        expected_mode="trace",
                        max_result_bytes=budget.max_result_bytes,
                        max_trace_bytes=budget.max_trace_bytes,
                        max_stdout_bytes=budget.max_stdout_bytes,
                        max_stderr_bytes=budget.max_stderr_bytes,
                        max_trace_steps=budget.max_trace_steps,
                    )
                    return parsed, "TIMEOUT", runtime_ver, duration_ms
                except ProtocolViolationError:
                    pass
            return (
                None,
                "TIMEOUT",
                "Trace sandbox timed out",
                duration_ms,
            )
        if "stdout" in raw_result and "protocol_version" not in raw_result:
            parsed = parse_runner_frame(
                raw_result["stdout"],
                expected_mode="trace",
                max_result_bytes=budget.max_result_bytes,
                max_trace_bytes=budget.max_trace_bytes,
                max_stdout_bytes=budget.max_stdout_bytes,
                max_stderr_bytes=budget.max_stderr_bytes,
                max_trace_steps=budget.max_trace_steps,
            )
            return parsed, None, runtime_ver, duration_ms

    raise ProtocolViolationError(
        "UNSUPPORTED_RUNNER_RESULT",
        f"Unsupported result type from SandboxRunnerProtocol: {type(raw_result).__name__}",
    )


def _invoke_runner(
    runner: SandboxRunnerProtocol | Callable[..., Any],
    payload: dict[str, Any],
    budget: ExecutionBudgetConfig,
) -> Any:
    for method_name in ("run_sandbox", "run_trace", "run_invocation", "run"):
        method = getattr(runner, method_name, None)
        if callable(method):
            sig = inspect.signature(method)
            params = list(sig.parameters.values())
            accepts_varargs = any(
                p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
                for p in params
            )
            if accepts_varargs or len(params) >= 2:
                return method(payload, budget)
            return method(payload)
    if callable(runner):
        return runner(payload, budget)
    raise TypeError("runner does not implement SandboxRunnerProtocol")


def record_execution_trace(
    req: TraceRequest,
    runner: SandboxRunnerProtocol | Any,
) -> TraceExecutionReport:
    """Broker-side trace recorder (§5.2, §9.4, R4 pre-launch validation)."""
    exercise_id = str(req.revision.exercise_id)
    spec_version = str(req.revision.spec_version)

    spec = registry.get_spec(exercise_id, spec_version)

    actual_code_hash = hashlib.sha256(req.source_code.encode("utf-8")).hexdigest()
    if actual_code_hash != req.revision.code_hash:
        raise ValueError(
            f"Code hash mismatch: TraceRequest source_code hash ({actual_code_hash}) "
            f"does not match revision.code_hash ({req.revision.code_hash})"
        )

    canonical_input = registry.validate_input(
        exercise_id, spec_version, req.input_args
    )
    expected_case_hash = registry.case_key(
        exercise_id, spec_version, canonical_input
    )
    if req.case_hash != expected_case_hash:
        raise ValueError(
            f"Case hash mismatch: expected {expected_case_hash}, got {req.case_hash}"
        )

    for direct_method_name in ("run_trace", "trace"):
        direct_method = getattr(runner, direct_method_name, None)
        if callable(direct_method):
            try:
                direct = direct_method(req)
                if isinstance(direct, TraceExecutionReport):
                    return direct
            except TypeError:
                pass

    runner_payload: dict[str, Any] = {
        "mode": "trace",
        "function_name": spec.function_name,
        "source_code": req.source_code,
        "source_hash": req.revision.code_hash,
        "input_args": canonical_input,
        "budget": {
            "invocation_wall_ms": req.budget.invocation_wall_ms,
            "invocation_cpu_seconds": req.budget.invocation_cpu_seconds,
            "memory_limit_mb": req.budget.memory_limit_mb,
            "pids_limit": req.budget.pids_limit,
            "max_stdout_bytes": req.budget.max_stdout_bytes,
            "max_stderr_bytes": req.budget.max_stderr_bytes,
            "max_result_bytes": req.budget.max_result_bytes,
            "max_trace_bytes": req.budget.max_trace_bytes,
            "max_trace_steps": req.budget.max_trace_steps,
            "max_trace_snapshots_work": req.budget.max_trace_snapshots_work,
        },
    }

    try:
        raw_result = _invoke_runner(runner, runner_payload, req.budget)
        parsed, override_kind, reason_or_ver, duration_ms = _coerce_runner_result(
            raw_result, budget=req.budget
        )
    except ProtocolViolationError as exc:
        tampered_codes = {
            "MULTIPLE_OR_SPOOFED_FRAMES",
            "FORBIDDEN_KEY",
            "UNFRAMED_LEADING_DATA",
            "TRAILING_DATA_AFTER_FRAME_END",
        }
        status = (
            TraceExecutionStatus.TRACE_TAMPERED
            if exc.code in tampered_codes
            else TraceExecutionStatus.TRACE_UNAVAILABLE
        )
        return TraceExecutionReport(
            trace_id=req.trace_id,
            revision=req.revision,
            case_hash=req.case_hash,
            status=status,
            steps=[],
            total_observed=0,
            trace_truncated=False,
            termination_reason=f"Protocol violation ({exc.code}): {exc.message}"[:256],
            observation=ExecutionObservation(
                kind=ExecutionObservationKind.INVALID_RESULT,
                return_value=None,
                error_type=exc.code[:128],
                error_message=exc.message[:1024],
                stdout_excerpt="",
                stderr_excerpt="",
                duration_ms=0,
            ),
            runtime_version=DEFAULT_RUNTIME_VERSION,
        )
    except Exception as exc:
        return TraceExecutionReport(
            trace_id=req.trace_id,
            revision=req.revision,
            case_hash=req.case_hash,
            status=TraceExecutionStatus.TRACE_UNAVAILABLE,
            steps=[],
            total_observed=0,
            trace_truncated=False,
            termination_reason=f"Sandbox trace invocation failed: {type(exc).__name__}: {exc}"[:256],
            observation=ExecutionObservation(
                kind=ExecutionObservationKind.UNAVAILABLE,
                return_value=None,
                error_type=type(exc).__name__[:128],
                error_message=str(exc)[:1024],
                stdout_excerpt="",
                stderr_excerpt="",
                duration_ms=0,
            ),
            runtime_version=DEFAULT_RUNTIME_VERSION,
        )

    if parsed is None:
        if override_kind == "TIMEOUT":
            return TraceExecutionReport(
                trace_id=req.trace_id,
                revision=req.revision,
                case_hash=req.case_hash,
                status=TraceExecutionStatus.TRACE_TIMEOUT,
                steps=[],
                total_observed=0,
                trace_truncated=True,
                termination_reason=reason_or_ver[:256],
                observation=ExecutionObservation(
                    kind=ExecutionObservationKind.TIMEOUT,
                    return_value=None,
                    error_type="TimeoutError",
                    error_message=reason_or_ver[:1024],
                    stdout_excerpt="",
                    stderr_excerpt="",
                    duration_ms=max(0, duration_ms),
                ),
                runtime_version=DEFAULT_RUNTIME_VERSION,
            )
        if override_kind == "RESOURCE_LIMIT":
            return TraceExecutionReport(
                trace_id=req.trace_id,
                revision=req.revision,
                case_hash=req.case_hash,
                status=TraceExecutionStatus.PARTIAL,
                steps=[],
                total_observed=0,
                trace_truncated=True,
                termination_reason=reason_or_ver[:256],
                observation=ExecutionObservation(
                    kind=ExecutionObservationKind.RESOURCE_LIMIT,
                    return_value=None,
                    error_type="ResourceLimitExceeded",
                    error_message=reason_or_ver[:1024],
                    stdout_excerpt="",
                    stderr_excerpt="",
                    duration_ms=max(0, duration_ms),
                ),
                runtime_version=DEFAULT_RUNTIME_VERSION,
            )
        return TraceExecutionReport(
            trace_id=req.trace_id,
            revision=req.revision,
            case_hash=req.case_hash,
            status=TraceExecutionStatus.TRACE_UNAVAILABLE,
            steps=[],
            total_observed=0,
            trace_truncated=False,
            termination_reason=reason_or_ver[:256],
            observation=ExecutionObservation(
                kind=ExecutionObservationKind.UNAVAILABLE,
                return_value=None,
                error_type="SandboxUnavailable",
                error_message=reason_or_ver[:1024],
                stdout_excerpt="",
                stderr_excerpt="",
                duration_ms=max(0, duration_ms),
            ),
            runtime_version=DEFAULT_RUNTIME_VERSION,
        )

    runtime_version = reason_or_ver or DEFAULT_RUNTIME_VERSION

    validated_steps: list[TraceStep] = []
    hash_mismatch_detected = False
    for raw_step in parsed.steps:
        if raw_step.get("source_hash") != req.revision.code_hash:
            hash_mismatch_detected = True
            break
        validated_steps.append(TraceStep(**raw_step))

    if hash_mismatch_detected:
        return TraceExecutionReport(
            trace_id=req.trace_id,
            revision=req.revision,
            case_hash=req.case_hash,
            status=TraceExecutionStatus.TRACE_TAMPERED,
            steps=[],
            total_observed=parsed.total_observed,
            trace_truncated=True,
            termination_reason="Returned TraceStep source_hash did not match revision.code_hash",
            observation=ExecutionObservation(
                kind=ExecutionObservationKind.INVALID_RESULT,
                return_value=None,
                error_type="TraceSourceHashMismatch",
                error_message="TraceStep source_hash mismatch",
                stdout_excerpt=parsed.stdout_excerpt,
                stderr_excerpt=parsed.stderr_excerpt,
                duration_ms=parsed.duration_ms,
            ),
            runtime_version=runtime_version,
        )

    obs_kind = (
        ExecutionObservationKind.TIMEOUT
        if override_kind == "TIMEOUT"
        else ExecutionObservationKind(parsed.kind)
    )
    observation = ExecutionObservation(
        kind=obs_kind,
        return_value=parsed.return_value if obs_kind == ExecutionObservationKind.RETURN else None,
        error_type=parsed.error_type,
        error_message=parsed.error_message,
        stdout_excerpt=parsed.stdout_excerpt,
        stderr_excerpt=parsed.stderr_excerpt,
        duration_ms=parsed.duration_ms,
    )

    if override_kind == "TIMEOUT" or obs_kind == ExecutionObservationKind.TIMEOUT:
        final_status = TraceExecutionStatus.TRACE_TIMEOUT
    else:
        final_status = TraceExecutionStatus(
            parsed.trace_status or str(TraceExecutionStatus.COMPLETED)
        )

    return TraceExecutionReport(
        trace_id=req.trace_id,
        revision=req.revision,
        case_hash=req.case_hash,
        status=final_status,
        steps=validated_steps,
        total_observed=parsed.total_observed,
        trace_truncated=parsed.trace_truncated,
        termination_reason=(parsed.termination_reason or "Trace finished")[:256],
        observation=observation,
        runtime_version=runtime_version,
    )


__all__ = [
    "DEFAULT_RUNTIME_VERSION",
    "InSandboxTraceOutput",
    "InSandboxTracer",
    "LEARNER_FILENAME",
    "RawSandboxResult",
    "SandboxRunnerProtocol",
    "record_execution_trace",
]
