"""Offline safety checks for the explicitly bounded synthetic provider probe."""
import asyncio
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

PATH = Path(__file__).resolve().parents[3] / "scripts" / "mentorly_streaming_probe.py"
spec = importlib.util.spec_from_file_location("mentorly_streaming_probe", PATH)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_requires_live_flag(capsys):
    with patch.object(probe, "run_probe") as run:
        assert probe.main([]) == 2
        run.assert_not_called()
    assert json.loads(capsys.readouterr().out)["stage"] == "explicit_live_flag_required"


def test_missing_key_does_not_construct_adapter():
    with patch.dict(probe.os.environ, {}, clear=True), patch.object(
        probe, "_load_env_file_if_present"
    ), patch.object(probe, "GnaniSpeechAdapter") as adapter:
        result = asyncio.run(probe.run_probe())
    assert result["status"] == "BLOCKED_EXTERNAL"
    adapter.assert_not_called()


def test_provider_failure_is_sanitized_and_never_calls_stt():
    class Gate:
        def __init__(self, adapter, **kwargs):
            assert kwargs["max_429_retries"] == 0
            assert kwargs["global_daily_call_limit"] == 2

        async def execute_tts(self, req, **kwargs):
            assert len(req.text) < 100
            raise probe.GnaniTransportError("SECRET provider body", status_code=429)

    with patch.dict(probe.os.environ, {"VCC_GNANI_API_KEY": "SECRET"}), patch.object(
        probe, "SpeechGatekeeper", Gate
    ), patch.object(probe, "GnaniWebSocketSTTRelay") as relay:
        result = asyncio.run(probe.run_probe())
    assert result["http_status"] == 429
    assert "SECRET" not in json.dumps(result)
    relay.assert_not_called()


def test_failure_category_never_echoes_unknown_body():
    error = probe.GnaniTransportError("SECRET provider message")
    assert probe.safe_failure_category(error) == "unclassified_transport_error"
    error = probe.GnaniTransportError("WS transcript omitted its final flag.")
    assert probe.safe_failure_category(error) == "transcript_final_flag_missing"


@pytest.mark.parametrize(("transcript", "expected_status"), [
    (probe.FIXTURE, "PASS"),
    ("The answer is three.", "FAIL"),
    ("பதில் மூன்று.", "FAIL"),
    ("unrelated but nonempty", "FAIL"),
    ("", "FAIL"),
])
def test_success_and_duration_guard_are_bounded(transcript, expected_status):
    from types import SimpleNamespace

    calls = {"tts": 0, "stt": 0}

    class Gate:
        def __init__(self, adapter, **kwargs):
            pass

        async def execute_tts(self, req, on_event):
            calls["tts"] += 1
            for kind in ("start", "chunk", "complete"):
                await on_event(SimpleNamespace(event_type=kind))
            return SimpleNamespace(wav_bytes=b"synthetic")

    class Relay:
        def __init__(self, gate, **kwargs):
            pass

        async def transcribe_live(self, req, frames):
            calls["stt"] += 1
            assert req.language_mode.value == "ta-IN,en-IN"
            assert [chunk async for chunk in frames] == [b"\0\0"]
            return SimpleNamespace(transport="WS_V3", latency_ms=1,
                                   audio_duration_sec=0.1, raw_transcript=transcript)

    with patch.dict(probe.os.environ, {"VCC_GNANI_API_KEY": "SECRET"}), patch.object(
        probe, "SpeechGatekeeper", Gate
    ), patch.object(probe, "GnaniWebSocketSTTRelay", Relay), patch.object(
        probe, "strip_wav_header_to_raw_pcm16", return_value=b"\0\0"
    ), patch.object(probe, "inspect_and_validate_tts_wav") as inspect:
        inspect.return_value = SimpleNamespace(duration_sec=0.1)
        result = asyncio.run(probe.run_probe())
        assert result["status"] == expected_status
        assert calls == {"tts": 1, "stt": 1}
        inspect.return_value = SimpleNamespace(duration_sec=11)
        result = asyncio.run(probe.run_probe())
        assert result["stage"] == "audio_duration_guard"
        assert calls == {"tts": 2, "stt": 1}


def test_single_tamil_override_is_explicit_and_does_not_mutate_original_headers():
    from contextlib import asynccontextmanager

    import websockets.asyncio.client

    observed = []

    @asynccontextmanager
    async def fake_connect(*args, **kwargs):
        observed.append(kwargs["additional_headers"])
        yield object()

    original = {"language_code": "ta-IN,en-IN", "format": "codemix"}

    async def check():
        for override in (False, True):
            connector = probe.diagnostic_connector({}, single_tamil_probe=override)
            async with connector("wss://unused.invalid", additional_headers=original):
                pass

    with patch.object(websockets.asyncio.client, "connect", fake_connect):
        asyncio.run(check())
    assert observed[0]["language_code"] == "ta-IN,en-IN"
    assert observed[1]["language_code"] == "ta-IN"
    assert original["language_code"] == "ta-IN,en-IN"
