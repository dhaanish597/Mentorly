"""Structured JSON logging with request_id correlation and secret redaction."""

from contextvars import ContextVar, Token
from datetime import datetime, timezone
import json
import logging
import re
import sys
from typing import Any

_REQUEST_ID_CTX: ContextVar[str] = ContextVar("vcc_request_id", default="-")

_SENSITIVE_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "authorization",
    "password",
    "credential",
    "x-api-key",
)

_SECRET_VALUE_PATTERN = re.compile(
    r"(?i)\b(bearer\s+[A-Za-z0-9._\-]+|sk-[A-Za-z0-9_\-]+|gsk_[A-Za-z0-9_\-]+)\b"
)

_STANDARD_RECORD_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)


def get_request_id() -> str:
    return _REQUEST_ID_CTX.get()


def set_request_id(request_id: str) -> Token[str]:
    return _REQUEST_ID_CTX.set(request_id)


def reset_request_id(token: Token[str]) -> None:
    _REQUEST_ID_CTX.reset(token)


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in _SENSITIVE_KEY_FRAGMENTS)


def _sanitize_value(value: Any, *, key: str | None = None) -> Any:
    if key is not None and _is_sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _sanitize_value(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str):
        return _SECRET_VALUE_PATTERN.sub("[REDACTED]", value)
    return value


class JsonLogFormatter(logging.Formatter):
    """Formats log records as single-line JSON with secret redaction."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": get_request_id(),
            "message": _sanitize_value(record.getMessage()),
        }
        for attr, val in record.__dict__.items():
            if attr in _STANDARD_RECORD_ATTRS or attr.startswith("_"):
                continue
            payload[attr] = _sanitize_value(val, key=attr)

        if record.exc_info and record.exc_info[0] is not None:
            payload["exception_type"] = record.exc_info[0].__name__

        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(level: str = "INFO") -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(numeric_level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
