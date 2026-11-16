"""Controller-only authentication of the actual native return/trace body."""
from __future__ import annotations

import hashlib
import hmac
import json
import re

HEADER = re.compile(rb"VIVA_NATIVE_V2 ([0-9a-f]{64}) ([1-9][0-9]{0,5})\n")
MAX_BODY = 262144
PREFIX = b"VIVA_NATIVE_V2\0"


class NativeProtocolError(ValueError):
    pass


def authenticated_body(raw: bytes, key: bytes, payload_sha256: str) -> bytes:
    if type(raw) is not bytes or type(key) is not bytes or len(key) != 32:
        raise NativeProtocolError("Invalid native authentication input")
    if not isinstance(payload_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", payload_sha256):
        raise NativeProtocolError("Invalid native invocation binding")
    match = HEADER.match(raw)
    if not match or len(raw) > MAX_BODY + 128:
        raise NativeProtocolError("Missing or oversized native result frame")
    size = int(match[2])
    body = raw[match.end():]
    if size > MAX_BODY or len(body) != size:
        raise NativeProtocolError("Truncated or multiple native result frames")
    expected = hmac.digest(key, PREFIX + payload_sha256.encode("ascii") + b"\0" + body, "sha256")
    if not hmac.compare_digest(expected.hex().encode("ascii"), match[1]):
        raise NativeProtocolError("Native result authentication failed")
    return body


def authenticated_runner_frame(raw: bytes, key: bytes, payload_sha256: str,
                               *, stdout: bytes = b"", stderr: bytes = b"") -> bytes:
    body = authenticated_body(raw, key, payload_sha256)
    try:
        envelope = json.loads(body, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeDecodeError):
        raise NativeProtocolError("Invalid authenticated native JSON") from None
    if not isinstance(envelope, dict):
        raise NativeProtocolError("Invalid authenticated native observation")
    # Only bounded independent controller captures enter the excerpts. The
    # signed observation is never parsed from the learner stdout channel.
    envelope["stdout_excerpt"] = stdout[:65536].decode("utf-8", errors="replace")[:4096]
    envelope["stderr_excerpt"] = stderr[:65536].decode("utf-8", errors="replace")[:4096]
    encoded = json.dumps(envelope, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    encoded = encoded.replace(b"<", b"\\u003c").replace(b">", b"\\u003e")
    if len(encoded) > MAX_BODY:
        raise NativeProtocolError("Authenticated observation exceeds controller limit")
    return b"<<VCC_RUNNER_FRAME_V1_BEGIN>>\n" + encoded + b"\n<<VCC_RUNNER_FRAME_V1_END>>\n"
