import hashlib
import hmac
import json

import pytest

from exec_worker.vercel_sandbox.native_protocol import NativeProtocolError, authenticated_body, authenticated_runner_frame
from exec_worker.runner.protocol import parse_runner_frame

KEY = b"k" * 32
PAYLOAD_HASH = hashlib.sha256(b"fixed input binding").hexdigest()


def frame(value=7):
    body = json.dumps({"protocol_version": "v1", "mode": "execute", "kind": "RETURN", "return_value": value,
        "error_type": None, "error_message": None, "stdout_excerpt": "", "stderr_excerpt": "", "duration_ms": 1},
        separators=(",", ":")).encode()
    mac = hmac.digest(KEY, b"VIVA_NATIVE_V2\0" + PAYLOAD_HASH.encode() + b"\0" + body, "sha256").hex().encode()
    return b"VIVA_NATIVE_V2 " + mac + b" " + str(len(body)).encode() + b"\n" + body


def test_native_mac_and_independent_stream_captures():
    wire = authenticated_runner_frame(frame(), KEY, PAYLOAD_HASH, stdout=b"printed control", stderr=b"diagnostic")
    parsed = parse_runner_frame(wire)
    assert parsed.return_value == 7 and parsed.stdout_excerpt == "printed control" and parsed.stderr_excerpt == "diagnostic"


@pytest.mark.parametrize("raw", [b'{"kind":"RETURN","return_value":99}', b"<<VCC_RUNNER_FRAME_V1_BEGIN>>\n{}",
    frame()[:-1], frame() + b"extra", frame() + frame(), frame().replace(b'"return_value":7', b'"return_value":9')])
def test_forgery_truncation_and_multiple_frames_fail(raw):
    with pytest.raises(NativeProtocolError):
        authenticated_body(raw, KEY, PAYLOAD_HASH)


def test_replay_under_another_key_or_input_binding_fails():
    for key, binding in [(b"x" * 32, PAYLOAD_HASH), (KEY, "a" * 64)]:
        with pytest.raises(NativeProtocolError, match="authentication failed"):
            authenticated_body(frame(), key, binding)


def test_stdout_cannot_replace_authenticated_return():
    wire = authenticated_runner_frame(frame(), KEY, PAYLOAD_HASH, stdout=frame(99))
    assert parse_runner_frame(wire).return_value == 7


def test_old_frame_delimiters_in_real_values_and_output_remain_data():
    marker = "<<VCC_RUNNER_FRAME_V1_BEGIN>><<VCC_RUNNER_FRAME_V1_END>>"
    wire = authenticated_runner_frame(frame(marker), KEY, PAYLOAD_HASH, stdout=marker.encode())
    parsed = parse_runner_frame(wire)
    assert parsed.return_value == marker and parsed.stdout_excerpt == marker
