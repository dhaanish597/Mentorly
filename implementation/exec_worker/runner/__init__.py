"""Disposable in-sandbox runner package for Voice Coding Coach."""

from .protocol import (
    FORBIDDEN_LEARNER_KEYS,
    FRAME_BEGIN,
    FRAME_END,
    PROTOCOL_VERSION,
    ParsedRunnerOutput,
    ProtocolViolationError,
    build_execute_envelope,
    build_trace_envelope,
    classify_learner_return_value,
    emit_runner_frame,
    is_strict_int,
    parse_runner_frame,
    truncate_utf8_bytes,
)
from .safe_serializer import (
    SerializationBudget,
    SerializationResult,
    serialize_frame_locals,
    serialize_value,
)

__all__ = [
    "FORBIDDEN_LEARNER_KEYS",
    "FRAME_BEGIN",
    "FRAME_END",
    "PROTOCOL_VERSION",
    "ParsedRunnerOutput",
    "ProtocolViolationError",
    "SerializationBudget",
    "SerializationResult",
    "build_execute_envelope",
    "build_trace_envelope",
    "classify_learner_return_value",
    "emit_runner_frame",
    "is_strict_int",
    "parse_runner_frame",
    "serialize_frame_locals",
    "serialize_value",
    "truncate_utf8_bytes",
]
