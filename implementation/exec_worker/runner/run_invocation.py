"""Disposable in-sandbox entrypoint executed inside `runsc` (§9.1, §9.2, §9.4, R1 repaired).

Security & Packaging Contract (Review Finding R1):
- Imports ONLY Python standard library modules and `exec_worker.runner.*`.
- Zero imports from `backend.*` or `exec_worker.worker_app.*`.
- Supports both `/ipc_in/payload.json` file argument and stdin JSON payload fallback
  when invoked without file arguments in isolated subprocess tests.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import resource
import signal
import sys
import time
from typing import Any

from exec_worker.runner.safe_serializer import _safe_type_name, safe_repr

from exec_worker.runner.in_sandbox_tracer import (
    LEARNER_FILENAME,
    InSandboxTracer,
)
from exec_worker.runner.protocol import (
    ProtocolViolationError,
    build_execute_envelope,
    build_trace_envelope,
    emit_runner_frame,
    truncate_utf8_bytes,
)


class BoundedTextStream(io.TextIOBase):
    """In-memory text stream that strictly caps retained UTF-8 bytes."""

    def __init__(self, max_bytes: int = 65536) -> None:
        super().__init__()
        self.max_bytes = max(0, int(max_bytes))
        self._chunks: list[bytes] = []
        self._bytes_stored: int = 0
        self.truncated: bool = False

    def writable(self) -> bool:
        return True

    def write(self, s: str) -> int:
        if type(s) is not str:
            raise TypeError("write() argument must be an exact str")
        raw_len = len(s)
        if self._bytes_stored >= self.max_bytes:
            self.truncated = True
            return raw_len

        encoded = s.encode("utf-8", errors="replace")
        remaining = self.max_bytes - self._bytes_stored
        if len(encoded) > remaining:
            self._chunks.append(encoded[:remaining])
            self._bytes_stored = self.max_bytes
            self.truncated = True
        else:
            self._chunks.append(encoded)
            self._bytes_stored += len(encoded)
        return raw_len

    def flush(self) -> None:
        return None

    def getvalue(self) -> str:
        raw = b"".join(self._chunks)
        return truncate_utf8_bytes(raw, self.max_bytes)


class _WallClockTimeoutError(BaseException):
    """Internal signal-raised exception when `SIGALRM` wall-clock timer fires."""


def _set_single_rlimit(limit_const: int | None, soft: int, hard: int) -> None:
    if limit_const is None:
        return
    try:
        current_soft, current_hard = resource.getrlimit(limit_const)
        if current_hard != resource.RLIM_INFINITY:
            hard = min(hard, current_hard)
            soft = min(soft, hard)
        resource.setrlimit(limit_const, (soft, hard))
    except (ValueError, OSError):
        pass


def apply_sandbox_rlimits(budget: dict[str, Any]) -> None:
    """Apply defense-in-depth `resource.setrlimit` caps inside the runner process."""
    cpu_seconds = max(1, int(budget.get("invocation_cpu_seconds", 2)))
    memory_mb = max(64, int(budget.get("memory_limit_mb", 256)))
    memory_bytes = memory_mb * 1024 * 1024
    pids_limit = max(4, int(budget.get("pids_limit", 16)))
    max_fsize_bytes = max(65536, int(budget.get("max_trace_bytes", 262144)) * 2)

    _set_single_rlimit(getattr(resource, "RLIMIT_CORE", None), 0, 0)
    _set_single_rlimit(
        getattr(resource, "RLIMIT_CPU", None), cpu_seconds, cpu_seconds + 1
    )
    _set_single_rlimit(
        getattr(resource, "RLIMIT_AS", None), memory_bytes, memory_bytes
    )
    _set_single_rlimit(
        getattr(resource, "RLIMIT_DATA", None), memory_bytes, memory_bytes
    )
    _set_single_rlimit(
        getattr(resource, "RLIMIT_NPROC", None), pids_limit, pids_limit
    )
    _set_single_rlimit(
        getattr(resource, "RLIMIT_FSIZE", None), max_fsize_bytes, max_fsize_bytes
    )


def _clone_input_args(input_args: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(input_args))


def execute_payload_in_process(
    payload: dict[str, Any],
    *,
    apply_rlimits: bool = False,
) -> dict[str, Any]:
    """Execute a validated runner payload dictionary (`execute` or `trace` mode)."""
    if type(payload) is not dict:
        raise ValueError("Runner payload must be a JSON object")

    mode = payload.get("mode")
    if mode is None:
        mode = "trace" if payload.get("record_trace") else "execute"
    if mode not in ("execute", "trace"):
        raise ValueError(f"Unsupported runner mode: {mode!r}")

    source_code = payload.get("source_code")
    function_name = payload.get("function_name") or payload.get("entrypoint")
    input_args = payload.get("input_args")
    budget = payload.get("budget") or {}

    if type(source_code) is not str or not source_code:
        raise ValueError("source_code must be a non-empty string")
    if type(function_name) is not str or not function_name:
        raise ValueError("function_name must be a non-empty string")
    if type(input_args) is not dict:
        raise ValueError("input_args must be a dictionary")

    max_stdout_bytes = int(budget.get("max_stdout_bytes", 65536))
    max_stderr_bytes = int(budget.get("max_stderr_bytes", 65536))
    max_trace_steps = int(
        budget.get("max_trace_steps", payload.get("max_trace_events", 250))
    )
    max_trace_snapshots_work = int(budget.get("max_trace_snapshots_work", 2000))
    wall_ms = int(budget.get("invocation_wall_ms", payload.get("timeout_ms", 2000)))

    source_hash = payload.get("source_hash")
    if type(source_hash) is not str or len(source_hash) != 64:
        source_hash = hashlib.sha256(source_code.encode("utf-8")).hexdigest()

    if apply_rlimits:
        apply_sandbox_rlimits(budget)

    stdout_buf = BoundedTextStream(max_bytes=max_stdout_bytes)
    stderr_buf = BoundedTextStream(max_bytes=max_stderr_bytes)

    saved_stdout = sys.stdout
    saved_stderr = sys.stderr
    saved_stdin = sys.stdin

    start_ns = time.perf_counter_ns()
    kind = "RETURN"
    ret_val: Any = None
    error_type: str | None = None
    error_message: str | None = None
    tracer: InSandboxTracer | None = None
    trace_output = None

    alarm_armed = False
    prev_sigalrm_handler = None
    if hasattr(signal, "SIGALRM") and hasattr(signal, "setitimer"):
        try:

            def _handle_alarm(signum: int, frame: Any) -> None:
                raise _WallClockTimeoutError("Execution exceeded invocation wall-clock timer")

            prev_sigalrm_handler = signal.signal(signal.SIGALRM, _handle_alarm)
            wall_sec = max(0.05, wall_ms / 1000.0)
            signal.setitimer(signal.ITIMER_REAL, wall_sec)
            alarm_armed = True
        except (ValueError, OSError):
            alarm_armed = False

    try:
        sys.stdout = stdout_buf  # type: ignore[assignment]
        sys.stderr = stderr_buf  # type: ignore[assignment]
        sys.stdin = io.StringIO("")

        compiled = compile(source_code, LEARNER_FILENAME, "exec")
        namespace: dict[str, Any] = {"__name__": "__learner__"}
        exec(compiled, namespace)  # noqa: S102

        target_fn = namespace.get(function_name)
        if not callable(target_fn):
            kind = "EXCEPTION"
            error_type = "AttributeError"
            error_message = f"Required function '{function_name}' is missing or not callable"
        else:
            call_kwargs = _clone_input_args(input_args)
            if mode == "trace":
                tracer = InSandboxTracer(
                    source_code=source_code,
                    source_hash=source_hash,
                    target_filename=LEARNER_FILENAME,
                    max_trace_steps=max_trace_steps,
                    max_trace_snapshots_work=max_trace_snapshots_work,
                )
                t_kind, t_ret, t_exc, trace_output = tracer.run_traced_callable(
                    target_fn, call_kwargs
                )
                if t_exc is not None:
                    raise t_exc
                kind = t_kind
                ret_val = t_ret
            else:
                ret_val = target_fn(**call_kwargs)
                kind = "RETURN"

    except _WallClockTimeoutError as exc:
        kind = "TIMEOUT"
        error_type = "TimeoutError"
        error_message = "Execution timed out"
        if tracer is not None:
            trace_output = tracer.build_output(outcome_kind="TIMEOUT", exc=exc)
    except MemoryError as exc:
        kind = "RESOURCE_LIMIT"
        error_type = "MemoryError"
        error_message = "Memory limit exceeded"
        if tracer is not None:
            trace_output = tracer.build_output(outcome_kind="EXCEPTION", exc=exc)
    except SyntaxError as exc:
        kind = "EXCEPTION"
        error_type = _safe_type_name(exc)
        error_message = f"{exc.msg} (line {exc.lineno})" if type(exc) is SyntaxError else safe_repr(exc)
        if tracer is not None:
            trace_output = tracer.build_output(outcome_kind="EXCEPTION", exc=exc)
    except BaseException as exc:
        kind = "EXCEPTION"
        error_type = _safe_type_name(exc)
        error_message = safe_repr(exc)
        if tracer is not None:
            trace_output = tracer.build_output(outcome_kind="EXCEPTION", exc=exc)
    finally:
        if alarm_armed:
            try:
                signal.setitimer(signal.ITIMER_REAL, 0.0)
                if prev_sigalrm_handler is not None:
                    signal.signal(signal.SIGALRM, prev_sigalrm_handler)
            except (ValueError, OSError):
                pass
        sys.stdout = saved_stdout
        sys.stderr = saved_stderr
        sys.stdin = saved_stdin

    duration_ms = max(0, (time.perf_counter_ns() - start_ns) // 1_000_000)

    if mode == "trace":
        if trace_output is None:
            if tracer is not None:
                trace_output = tracer.build_output(outcome_kind=kind)
            else:
                trace_status = (
                    "TRACE_TIMEOUT" if kind == "TIMEOUT" else "TRACE_UNAVAILABLE"
                )
                return build_trace_envelope(
                    kind=kind,
                    return_value=ret_val if kind == "RETURN" else None,
                    error_type=error_type,
                    error_message=error_message,
                    stdout_text=stdout_buf.getvalue(),
                    stderr_text=stderr_buf.getvalue(),
                    duration_ms=duration_ms,
                    trace_status=trace_status,
                    steps=[],
                    total_observed=0,
                    trace_truncated=False,
                    termination_reason=error_message or "Trace failed before execution",
                    max_stdout_bytes=max_stdout_bytes,
                    max_stderr_bytes=max_stderr_bytes,
                )

        envelope = build_trace_envelope(
            kind=kind,
            return_value=ret_val if kind == "RETURN" else None,
            error_type=error_type,
            error_message=error_message,
            stdout_text=stdout_buf.getvalue(),
            stderr_text=stderr_buf.getvalue(),
            duration_ms=duration_ms,
            trace_status=trace_output.trace_status,
            steps=trace_output.steps,
            total_observed=trace_output.total_observed,
            trace_truncated=trace_output.trace_truncated,
            termination_reason=trace_output.termination_reason,
            max_stdout_bytes=max_stdout_bytes,
            max_stderr_bytes=max_stderr_bytes,
        )
        max_trace_bytes = int(budget.get("max_trace_bytes", 262144))
        while True:
            try:
                emit_runner_frame(envelope, max_payload_bytes=max_trace_bytes)
                break
            except ProtocolViolationError:
                if not envelope["steps"]:
                    break
                envelope["steps"].pop()
                envelope["trace_truncated"] = True
                if envelope["trace_status"] == "COMPLETED":
                    envelope["trace_status"] = "PARTIAL"
                envelope["termination_reason"] = (
                    f"Trimmed retained steps to fit max_trace_bytes ({max_trace_bytes})"
                )
        return envelope

    return build_execute_envelope(
        kind=kind,
        return_value=ret_val if kind == "RETURN" else None,
        error_type=error_type,
        error_message=error_message,
        stdout_text=stdout_buf.getvalue(),
        stderr_text=stderr_buf.getvalue(),
        duration_ms=duration_ms,
        max_stdout_bytes=max_stdout_bytes,
        max_stderr_bytes=max_stderr_bytes,
    )


def main(argv: list[str] | None = None) -> int:
    """Entrypoint invoked as `python3 -I -B -m exec_worker.runner.run_invocation [/ipc_in/payload.json]`."""
    args = argv if argv is not None else sys.argv[1:]

    raw_stdin_payload: str | None = None
    if len(args) == 0 and not sys.stdin.isatty():
        raw_stdin_payload = sys.stdin.read()

    protocol_fd = os.dup(1)
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull_fd, 1)
    os.close(devnull_fd)

    try:
        if len(args) == 1:
            payload_path = Path(args[0])
            raw_payload = json.loads(payload_path.read_text(encoding="utf-8"))
        elif len(args) == 0 and raw_stdin_payload and raw_stdin_payload.strip():
            raw_payload = json.loads(raw_stdin_payload)
        else:
            err_env = build_execute_envelope(
                kind="UNAVAILABLE",
                error_type="RunnerInvocationError",
                error_message="Expected single argument: path to payload.json (or JSON on stdin)",
                duration_ms=0,
            )
            frame_str = emit_runner_frame(err_env)
            os.write(protocol_fd, frame_str.encode("utf-8"))
            return 2

        should_apply_rlimits = bool(raw_payload.get("apply_rlimits", len(args) == 1))
        envelope = execute_payload_in_process(
            raw_payload, apply_rlimits=should_apply_rlimits
        )

        budget = raw_payload.get("budget") or {}
        mode = envelope.get("mode", raw_payload.get("mode", "execute"))
        max_bytes = (
            int(budget.get("max_trace_bytes", 262144))
            if mode == "trace"
            else int(budget.get("max_result_bytes", 65536))
        )
        frame_str = emit_runner_frame(envelope, max_payload_bytes=max_bytes)
        os.write(protocol_fd, frame_str.encode("utf-8"))
        return 0
    except Exception as exc:
        fallback_env = build_execute_envelope(
            kind="UNAVAILABLE",
            error_type=_safe_type_name(exc),
            error_message=safe_repr(exc),
            duration_ms=0,
        )
        frame_str = emit_runner_frame(fallback_env)
        os.write(protocol_fd, frame_str.encode("utf-8"))
        return 1
    finally:
        try:
            os.close(protocol_fd)
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
