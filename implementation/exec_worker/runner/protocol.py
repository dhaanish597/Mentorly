"""Untrusted in-sandbox wire framing and strict parser (§9.2).

Defines the framed JSON protocol between the disposable runner container
(`exec_worker/runner/run_invocation.py`) and the parent trusted broker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

from .safe_serializer import _safe_type_name

FRAME_BEGIN = "<<VCC_RUNNER_FRAME_V1_BEGIN>>"
FRAME_END = "<<VCC_RUNNER_FRAME_V1_END>>"
PROTOCOL_VERSION = "v1"

FORBIDDEN_LEARNER_KEYS: frozenset[str] = frozenset(
    {
        "reference_output",
        "challenge_id",
        "case_hash",
        "verification_status",
    }
)

_ALLOWED_MODES: frozenset[str] = frozenset({"execute", "trace"})

_ALLOWED_OBSERVATION_KINDS: frozenset[str] = frozenset(
    {
        "RETURN",
        "EXCEPTION",
        "TIMEOUT",
        "RESOURCE_LIMIT",
        "INVALID_RESULT",
        "UNAVAILABLE",
    }
)

_ALLOWED_TRACE_STATUSES: frozenset[str] = frozenset(
    {
        "COMPLETED",
        "PARTIAL",
        "TRACE_TIMEOUT",
        "TRACE_UNAVAILABLE",
        "TRACE_TAMPERED",
    }
)

_ALLOWED_TRACE_EVENT_KINDS: frozenset[str] = frozenset(
    {
        "CALL",
        "LINE",
        "RETURN",
        "EXCEPTION",
        "TRUNCATED",
    }
)

_ALLOWED_ATTRIBUTION_STATUSES: frozenset[str] = frozenset(
    {
        "ATTRIBUTED",
        "AMBIGUOUS",
        "UNAVAILABLE",
        "TAMPERED",
    }
)

_EXECUTE_ENVELOPE_KEYS: frozenset[str] = frozenset(
    {
        "protocol_version",
        "mode",
        "kind",
        "return_value",
        "error_type",
        "error_message",
        "stdout_excerpt",
        "stderr_excerpt",
        "duration_ms",
    }
)

_TRACE_ENVELOPE_KEYS: frozenset[str] = frozenset(
    {
        "protocol_version",
        "mode",
        "kind",
        "return_value",
        "error_type",
        "error_message",
        "stdout_excerpt",
        "stderr_excerpt",
        "duration_ms",
        "trace_status",
        "steps",
        "total_observed",
        "trace_truncated",
        "termination_reason",
    }
)

_TRACE_STEP_KEYS: frozenset[str] = frozenset(
    {
        "event_id",
        "frame_id",
        "parent_frame_id",
        "call_depth",
        "source_hash",
        "source_line",
        "event_kind",
        "attribution_status",
        "locals_snapshot",
        "truncated_values",
    }
)

MAX_EXCERPT_CHARS = 4096
MAX_ERROR_TYPE_CHARS = 128
MAX_ERROR_MESSAGE_CHARS = 1024
MAX_RETURN_INT_BITS = 4096


class ProtocolViolationError(ValueError):
    """Raised when raw output from the disposable runner violates the wire protocol."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ParsedRunnerOutput:
    """Validated, sanitized result parsed from the runner's framed output."""

    mode: str
    kind: str
    return_value: int | bool | str | list[int | bool | str] | None
    error_type: str | None
    error_message: str | None
    stdout_excerpt: str
    stderr_excerpt: str
    duration_ms: int
    trace_status: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    total_observed: int = 0
    trace_truncated: bool = False
    termination_reason: str | None = None


def is_strict_int(val: object) -> bool:
    """Return True if and only if `val` is an exact built-in `int` (never `bool`)."""
    return type(val) is int


def truncate_utf8_bytes(text: str | bytes, max_bytes: int) -> str:
    """Truncate `text` to at most `max_bytes` UTF-8 bytes and at most 4096 characters."""
    if type(max_bytes) is not int or max_bytes < 0:
        raise ValueError("max_bytes must be a non-negative integer")
    if isinstance(text, bytes):
        raw_bytes = text[:max_bytes]
        decoded = raw_bytes.decode("utf-8", errors="replace")
    elif type(text) is str:
        encoded = text.encode("utf-8", errors="replace")
        if len(encoded) > max_bytes:
            decoded = encoded[:max_bytes].decode("utf-8", errors="ignore")
        else:
            decoded = text
    else:
        raise TypeError("text must be str or bytes")

    if len(decoded) > MAX_EXCERPT_CHARS:
        decoded = decoded[:MAX_EXCERPT_CHARS]
    return decoded


def classify_learner_return_value(
    raw_value: object,
) -> tuple[str, int | bool | str | list[int | bool | str] | None, str | None, str | None]:
    """Classify a raw return value from learner code."""
    def scalar(value: object) -> bool:
        if type(value) is int:
            return -(2**53-1) <= value <= 2**53-1
        if type(value) is bool:
            return True
        if type(value) is str:
            return len(value) <= 256
        return False

    if scalar(raw_value):
        return ('RETURN', raw_value, None, None)
    if type(raw_value) is list and len(raw_value) <= 128 and all(scalar(v) for v in raw_value):
        return ('RETURN', list(raw_value), None, None)
    type_name = 'NoneType' if raw_value is None else _safe_type_name(raw_value)
    return ('INVALID_RESULT', None, 'InvalidReturnType',
        f'Expected bounded strict integer, boolean, string or scalar list; got {type_name}')


def build_execute_envelope(
    *,
    kind: str,
    return_value: object = None,
    error_type: str | None = None,
    error_message: str | None = None,
    stdout_text: str | bytes = "",
    stderr_text: str | bytes = "",
    duration_ms: int = 0,
    max_stdout_bytes: int = 65536,
    max_stderr_bytes: int = 65536,
) -> dict[str, Any]:
    """Build a strictly typed single-case execution envelope ready for framing."""
    if kind == "RETURN":
        kind, validated_ret, err_t, err_m = classify_learner_return_value(return_value)
        if kind != "RETURN":
            error_type = err_t
            error_message = err_m
    else:
        validated_ret = None

    if kind not in _ALLOWED_OBSERVATION_KINDS:
        raise ValueError(f"Unsupported observation kind: {kind}")

    safe_duration = duration_ms if (type(duration_ms) is int and duration_ms >= 0) else 0
    return {
        "protocol_version": PROTOCOL_VERSION,
        "mode": "execute",
        "kind": kind,
        "return_value": validated_ret,
        "error_type": (error_type[:MAX_ERROR_TYPE_CHARS] if type(error_type) is str else None),
        "error_message": (
            error_message[:MAX_ERROR_MESSAGE_CHARS] if type(error_message) is str else None
        ),
        "stdout_excerpt": truncate_utf8_bytes(stdout_text, max_stdout_bytes),
        "stderr_excerpt": truncate_utf8_bytes(stderr_text, max_stderr_bytes),
        "duration_ms": safe_duration,
    }


def build_trace_envelope(
    *,
    kind: str,
    return_value: object = None,
    error_type: str | None = None,
    error_message: str | None = None,
    stdout_text: str | bytes = "",
    stderr_text: str | bytes = "",
    duration_ms: int = 0,
    trace_status: str,
    steps: list[dict[str, Any]],
    total_observed: int,
    trace_truncated: bool,
    termination_reason: str,
    max_stdout_bytes: int = 65536,
    max_stderr_bytes: int = 65536,
) -> dict[str, Any]:
    """Build a strictly typed trace execution envelope ready for framing."""
    base = build_execute_envelope(
        kind=kind,
        return_value=return_value,
        error_type=error_type,
        error_message=error_message,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        duration_ms=duration_ms,
        max_stdout_bytes=max_stdout_bytes,
        max_stderr_bytes=max_stderr_bytes,
    )
    if trace_status not in _ALLOWED_TRACE_STATUSES:
        raise ValueError(f"Unsupported trace status: {trace_status}")
    safe_reason = (
        termination_reason[:256]
        if (type(termination_reason) is str and len(termination_reason) > 0)
        else "trace_completed"
    )
    base["mode"] = "trace"
    base["trace_status"] = trace_status
    base["steps"] = list(steps)
    base["total_observed"] = (
        total_observed if (type(total_observed) is int and total_observed >= 0) else 0
    )
    base["trace_truncated"] = bool(trace_truncated)
    base["termination_reason"] = safe_reason
    return base


def emit_runner_frame(
    payload: dict[str, Any],
    *,
    max_payload_bytes: int | None = None,
) -> str:
    """Serialize `payload` to compact JSON wrapped in `FRAME_BEGIN` / `FRAME_END`."""
    if type(payload) is not dict:
        raise ProtocolViolationError("INVALID_PAYLOAD", "Runner payload must be a JSON object")

    for forbidden in FORBIDDEN_LEARNER_KEYS:
        if forbidden in payload:
            raise ProtocolViolationError(
                "FORBIDDEN_KEY",
                f"Learner payload may never include forbidden key '{forbidden}'",
            )

    serialized = (
        json.dumps(
            payload,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    if max_payload_bytes is not None:
        encoded_len = len(serialized.encode("utf-8"))
        if encoded_len > max_payload_bytes:
            raise ProtocolViolationError(
                "PAYLOAD_TOO_LARGE",
                f"Serialized runner payload ({encoded_len} bytes) exceeds limit ({max_payload_bytes} bytes)",
            )
    return f"{FRAME_BEGIN}\n{serialized}\n{FRAME_END}\n"


def _reject_invalid_constant(constant: str) -> Any:
    raise ProtocolViolationError(
        "NON_STANDARD_JSON",
        f"Non-standard JSON constant '{constant}' is forbidden in runner frame",
    )


def _validate_trace_step_dict(step: object, index: int) -> dict[str, Any]:
    if type(step) is not dict:
        raise ProtocolViolationError(
            "INVALID_TRACE_STEP",
            f"Trace step at index {index} must be a JSON object",
        )
    step_keys = set(step.keys())
    forbidden_hit = step_keys & FORBIDDEN_LEARNER_KEYS
    if forbidden_hit:
        raise ProtocolViolationError(
            "FORBIDDEN_KEY",
            f"Trace step {index} contains forbidden key(s): {sorted(forbidden_hit)}",
        )
    if step_keys != _TRACE_STEP_KEYS:
        extra = step_keys - _TRACE_STEP_KEYS
        missing = _TRACE_STEP_KEYS - step_keys
        raise ProtocolViolationError(
            "INVALID_TRACE_STEP_KEYS",
            f"Trace step {index} has invalid keys (extra={sorted(extra)}, missing={sorted(missing)})",
        )

    event_id = step["event_id"]
    if type(event_id) is not int or event_id < 0:
        raise ProtocolViolationError(
            "INVALID_TRACE_STEP", f"Trace step {index} event_id must be a non-negative strict int"
        )

    frame_id = step["frame_id"]
    if type(frame_id) is not str or not (1 <= len(frame_id) <= 64):
        raise ProtocolViolationError(
            "INVALID_TRACE_STEP", f"Trace step {index} frame_id must be a non-empty string <= 64 chars"
        )

    parent_frame_id = step["parent_frame_id"]
    if parent_frame_id is not None and (
        type(parent_frame_id) is not str or not (1 <= len(parent_frame_id) <= 64)
    ):
        raise ProtocolViolationError(
            "INVALID_TRACE_STEP",
            f"Trace step {index} parent_frame_id must be None or string <= 64 chars",
        )

    call_depth = step["call_depth"]
    if type(call_depth) is not int or call_depth < 0:
        raise ProtocolViolationError(
            "INVALID_TRACE_STEP", f"Trace step {index} call_depth must be a non-negative strict int"
        )

    source_hash = step["source_hash"]
    if (
        type(source_hash) is not str
        or len(source_hash) != 64
        or any(ch not in "0123456789abcdef" for ch in source_hash)
    ):
        raise ProtocolViolationError(
            "INVALID_TRACE_STEP", f"Trace step {index} source_hash must be a 64-char lowercase hex SHA-256"
        )

    source_line = step["source_line"]
    if type(source_line) is not int or source_line < 1:
        raise ProtocolViolationError(
            "INVALID_TRACE_STEP", f"Trace step {index} source_line must be a strict int >= 1"
        )

    event_kind = step["event_kind"]
    if type(event_kind) is not str or event_kind not in _ALLOWED_TRACE_EVENT_KINDS:
        raise ProtocolViolationError(
            "INVALID_TRACE_STEP", f"Trace step {index} has invalid event_kind: {event_kind!r}"
        )

    attribution_status = step["attribution_status"]
    if (
        type(attribution_status) is not str
        or attribution_status not in _ALLOWED_ATTRIBUTION_STATUSES
    ):
        raise ProtocolViolationError(
            "INVALID_TRACE_STEP",
            f"Trace step {index} has invalid attribution_status: {attribution_status!r}",
        )

    locals_snapshot = step["locals_snapshot"]
    if type(locals_snapshot) is not dict:
        raise ProtocolViolationError(
            "INVALID_TRACE_STEP", f"Trace step {index} locals_snapshot must be a dict"
        )

    truncated_values = step["truncated_values"]
    if type(truncated_values) is not list or any(type(x) is not str for x in truncated_values):
        raise ProtocolViolationError(
            "INVALID_TRACE_STEP", f"Trace step {index} truncated_values must be a list[str]"
        )

    return dict(step)


def parse_runner_frame(
    raw_stdout: str | bytes,
    *,
    expected_mode: str = "execute",
    max_result_bytes: int = 65536,
    max_trace_bytes: int = 262144,
    max_stdout_bytes: int = 65536,
    max_stderr_bytes: int = 65536,
    max_trace_steps: int = 250,
) -> ParsedRunnerOutput:
    """Strictly parse and validate a single framed JSON payload from the disposable runner."""
    if expected_mode not in _ALLOWED_MODES:
        raise ValueError(f"Unsupported expected_mode: {expected_mode}")

    byte_cap = max_trace_bytes if expected_mode == "trace" else max_result_bytes

    if isinstance(raw_stdout, bytes):
        raw_bytes = raw_stdout
    elif type(raw_stdout) is str:
        raw_bytes = raw_stdout.encode("utf-8", errors="replace")
    else:
        raise ProtocolViolationError("INVALID_STDOUT_TYPE", "Runner stdout must be bytes or str")

    framing_allowance = len(FRAME_BEGIN.encode("utf-8")) + len(FRAME_END.encode("utf-8")) + 64
    if len(raw_bytes) > byte_cap + framing_allowance:
        raise ProtocolViolationError(
            "FRAME_BYTE_CAP_EXCEEDED",
            f"Runner output ({len(raw_bytes)} bytes) exceeds protocol cap ({byte_cap} bytes)",
        )

    try:
        text = raw_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ProtocolViolationError(
            "INVALID_UTF8", f"Runner frame is not valid UTF-8: {exc}"
        ) from exc

    begin_count = text.count(FRAME_BEGIN)
    end_count = text.count(FRAME_END)

    if begin_count == 0 or end_count == 0:
        raise ProtocolViolationError(
            "MISSING_FRAME",
            "Runner output is missing required frame delimiters",
        )
    if begin_count > 1 or end_count > 1:
        raise ProtocolViolationError(
            "MULTIPLE_OR_SPOOFED_FRAMES",
            f"Detected multiple frame delimiters (begin={begin_count}, end={end_count}); possible frame spoofing",
        )

    begin_idx = text.find(FRAME_BEGIN)
    end_idx = text.find(FRAME_END)
    if end_idx < begin_idx:
        raise ProtocolViolationError(
            "INVERTED_FRAME_DELIMITERS",
            "FRAME_END appeared before FRAME_BEGIN",
        )

    leading_data = text[:begin_idx]
    trailing_data = text[end_idx + len(FRAME_END) :]

    if leading_data.strip() != "":
        raise ProtocolViolationError(
            "UNFRAMED_LEADING_DATA",
            "Unexpected data before FRAME_BEGIN on protocol channel",
        )
    if trailing_data.strip() != "":
        raise ProtocolViolationError(
            "TRAILING_DATA_AFTER_FRAME_END",
            "Unexpected trailing data after FRAME_END on protocol channel",
        )

    inner_json = text[begin_idx + len(FRAME_BEGIN) : end_idx].strip()
    inner_bytes = inner_json.encode("utf-8")
    if len(inner_bytes) > byte_cap:
        raise ProtocolViolationError(
            "PAYLOAD_BYTE_CAP_EXCEEDED",
            f"Inner JSON payload ({len(inner_bytes)} bytes) exceeds cap ({byte_cap} bytes)",
        )

    if not inner_json:
        raise ProtocolViolationError("EMPTY_FRAME", "Runner frame payload is empty")

    try:
        payload = json.loads(inner_json, parse_constant=_reject_invalid_constant)
    except ProtocolViolationError:
        raise
    except Exception as exc:
        raise ProtocolViolationError(
            "MALFORMED_JSON", f"Runner frame payload is not valid JSON: {exc}"
        ) from exc

    if type(payload) is not dict:
        raise ProtocolViolationError(
            "NON_OBJECT_JSON", "Runner frame JSON root must be an object"
        )

    payload_keys = set(payload.keys())
    forbidden_found = payload_keys & FORBIDDEN_LEARNER_KEYS
    if forbidden_found:
        raise ProtocolViolationError(
            "FORBIDDEN_KEY",
            f"Runner payload contains forbidden key(s): {sorted(forbidden_found)}",
        )

    expected_keys = (
        _TRACE_ENVELOPE_KEYS if expected_mode == "trace" else _EXECUTE_ENVELOPE_KEYS
    )
    if payload_keys != expected_keys:
        extra = payload_keys - expected_keys
        missing = expected_keys - payload_keys
        raise ProtocolViolationError(
            "UNEXPECTED_KEYS",
            f"Runner payload keys mismatch (extra={sorted(extra)}, missing={sorted(missing)})",
        )

    if payload["protocol_version"] != PROTOCOL_VERSION:
        raise ProtocolViolationError(
            "UNSUPPORTED_PROTOCOL_VERSION",
            f"Expected protocol_version {PROTOCOL_VERSION!r}, got {payload['protocol_version']!r}",
        )

    mode = payload["mode"]
    if mode != expected_mode:
        raise ProtocolViolationError(
            "MODE_MISMATCH",
            f"Expected mode {expected_mode!r}, got {mode!r}",
        )

    raw_kind = payload["kind"]
    if type(raw_kind) is not str or raw_kind not in _ALLOWED_OBSERVATION_KINDS:
        raise ProtocolViolationError(
            "INVALID_OBSERVATION_KIND",
            f"Invalid observation kind: {raw_kind!r}",
        )

    raw_return_value = payload["return_value"]
    raw_error_type = payload["error_type"]
    raw_error_message = payload["error_message"]

    if raw_error_type is not None and type(raw_error_type) is not str:
        raise ProtocolViolationError("INVALID_ERROR_TYPE", "error_type must be str or null")
    if raw_error_message is not None and type(raw_error_message) is not str:
        raise ProtocolViolationError(
            "INVALID_ERROR_MESSAGE", "error_message must be str or null"
        )

    stdout_excerpt = payload["stdout_excerpt"]
    stderr_excerpt = payload["stderr_excerpt"]
    if type(stdout_excerpt) is not str or type(stderr_excerpt) is not str:
        raise ProtocolViolationError(
            "INVALID_STDIO_EXCERPT", "stdout_excerpt and stderr_excerpt must be strings"
        )

    duration_ms = payload["duration_ms"]
    if type(duration_ms) is not int or duration_ms < 0:
        raise ProtocolViolationError(
            "INVALID_DURATION", "duration_ms must be a non-negative strict integer"
        )

    effective_kind = raw_kind
    effective_return: int | bool | str | list[int | bool | str] | None = None
    effective_err_type = (
        raw_error_type[:MAX_ERROR_TYPE_CHARS] if raw_error_type is not None else None
    )
    effective_err_msg = (
        raw_error_message[:MAX_ERROR_MESSAGE_CHARS]
        if raw_error_message is not None
        else None
    )

    if raw_kind == "RETURN":
        classified_kind, classified_val, c_err_t, c_err_m = classify_learner_return_value(
            raw_return_value
        )
        effective_kind = classified_kind
        effective_return = classified_val
        if classified_kind != "RETURN":
            effective_err_type = c_err_t
            effective_err_msg = c_err_m
    else:
        if raw_return_value is not None:
            raise ProtocolViolationError(
                "NON_NULL_RETURN_ON_ERROR",
                f"Non-RETURN observation ({raw_kind}) must have return_value=null",
            )

    safe_stdout = truncate_utf8_bytes(stdout_excerpt, max_stdout_bytes)
    safe_stderr = truncate_utf8_bytes(stderr_excerpt, max_stderr_bytes)

    if expected_mode == "execute":
        return ParsedRunnerOutput(
            mode="execute",
            kind=effective_kind,
            return_value=effective_return,
            error_type=effective_err_type,
            error_message=effective_err_msg,
            stdout_excerpt=safe_stdout,
            stderr_excerpt=safe_stderr,
            duration_ms=duration_ms,
        )

    trace_status = payload["trace_status"]
    if type(trace_status) is not str or trace_status not in _ALLOWED_TRACE_STATUSES:
        raise ProtocolViolationError(
            "INVALID_TRACE_STATUS", f"Invalid trace_status: {trace_status!r}"
        )

    raw_steps = payload["steps"]
    if type(raw_steps) is not list:
        raise ProtocolViolationError("INVALID_TRACE_STEPS", "steps must be a list")
    if len(raw_steps) > max_trace_steps:
        raise ProtocolViolationError(
            "TRACE_STEPS_EXCEEDED",
            f"Trace steps count ({len(raw_steps)}) exceeds max_trace_steps ({max_trace_steps})",
        )

    validated_steps = [
        _validate_trace_step_dict(step_obj, idx) for idx, step_obj in enumerate(raw_steps)
    ]

    total_observed = payload["total_observed"]
    if type(total_observed) is not int or total_observed < 0:
        raise ProtocolViolationError(
            "INVALID_TOTAL_OBSERVED",
            "total_observed must be a non-negative strict integer",
        )

    trace_truncated = payload["trace_truncated"]
    if type(trace_truncated) is not bool:
        raise ProtocolViolationError(
            "INVALID_TRACE_TRUNCATED", "trace_truncated must be a strict boolean"
        )

    termination_reason = payload["termination_reason"]
    if type(termination_reason) is not str or not (1 <= len(termination_reason) <= 256):
        raise ProtocolViolationError(
            "INVALID_TERMINATION_REASON",
            "termination_reason must be a non-empty string <= 256 chars",
        )

    return ParsedRunnerOutput(
        mode="trace",
        kind=effective_kind,
        return_value=effective_return,
        error_type=effective_err_type,
        error_message=effective_err_msg,
        stdout_excerpt=safe_stdout,
        stderr_excerpt=safe_stderr,
        duration_ms=duration_ms,
        trace_status=trace_status,
        steps=validated_steps,
        total_observed=total_observed,
        trace_truncated=trace_truncated,
        termination_reason=termination_reason,
    )
