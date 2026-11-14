import asyncio
import io
import json
import wave
from contextlib import asynccontextmanager

import pytest

from backend.app.models.api_schemas import STTRequest
from backend.app.speech.audio_utils import generate_sine_wav_bytes
from backend.app.speech.gatekeeper import SpeechBusyError, SpeechGatekeeper
from backend.app.speech.gnani_adapter import GnaniSpeechAdapter


def test_ws_relay_imports_and_strips_nonstandard_wav_header():
    from backend.app.speech.ws_streamer import strip_wav_header_to_raw_pcm16

    original = generate_sine_wav_bytes(duration_sec=0.1)
    # RIFF JUNK subchunk demonstrates why slicing at byte 44 loses framing.
    wav = original[:12] + b"JUNK" + (4).to_bytes(4, "little") + b"abcd" + original[12:]
    wav = wav[:4] + (len(wav) - 8).to_bytes(4, "little") + wav[8:]
    with wave.open(io.BytesIO(wav), "rb") as f:
        expected = f.readframes(f.getnframes())
    assert strip_wav_header_to_raw_pcm16(wav) == expected


def test_ws_uses_upgrade_headers_paced_pcm_commit_and_dispatcher():
    from backend.app.speech.ws_streamer import GnaniWebSocketSTTRelay

    sent = []
    kwargs_seen = {}

    class Connection:
        def __init__(self):
            self.count = 0

        async def send(self, value):
            sent.append(value)

        async def recv(self):
            self.count += 1
            if self.count == 1:
                return json.dumps(
                    {
                        "type": "connected",
                        "request_id": "provider-real",
                        "config": {"sample_rate": 16000, "chunk_size": 512},
                    }
                )
            return json.dumps(
                {
                    "type": "transcript",
                    "text": "returns three",
                    "request_id": "provider-real",
                    "is_final": True,
                    "segment_id": "seg1",
                }
            )

    @asynccontextmanager
    async def connect(url, **kwargs):
        kwargs_seen.update(kwargs)
        yield Connection()

    async def go():
        gate = SpeechGatekeeper(GnaniSpeechAdapter(api_key="test-only"))
        relay = GnaniWebSocketSTTRelay(gate, connect_fn=connect, pace_frames=False)
        req = STTRequest(session_id="ws-test")
        result = await relay.transcribe_stream_with_fallback(
            req, [generate_sine_wav_bytes(duration_sec=0.1)]
        )
        assert result.transport == "WS_V3"
        assert result.provider_confidence is None
        assert result.provider_request_id == "provider-real"
        assert gate.get_capacity_status().stt_requests_count == 1
        assert gate.get_capacity_status().active_requests == 0

    asyncio.run(go())
    assert kwargs_seen["additional_headers"]["language_code"] == "en-IN"
    assert kwargs_seen["additional_headers"]["x-api-key-id"] == "test-only"
    assert json.loads(sent[-1]) == {"type": "commit"}
    assert all(len(frame) == 1024 for frame in sent if isinstance(frame, bytes))
    assert all(
        not frame.startswith(b"RIFF") for frame in sent if isinstance(frame, bytes)
    )


def test_speech_cannot_resurrect_tombstoned_session():
    gate = SpeechGatekeeper(GnaniSpeechAdapter(api_key="test-only"))
    rid = gate._reserve_usage(
        session_id="deleted", turn_generation=1, operation_type="TTS", est_tts_chars=3
    )
    gate._conn.execute("UPDATE sessions SET deleted_at='now' WHERE id='deleted'")
    with pytest.raises(SpeechBusyError):
        gate._reserve_usage(
            session_id="deleted",
            turn_generation=1,
            operation_type="TTS",
            est_tts_chars=3,
        )
    gate._conn.execute("DELETE FROM sessions WHERE id='deleted'")
    gate._finalize_reservation(
        rid,
        session_id="deleted",
        turn_generation=1,
        operation_type="TTS",
        committed=False,
    )
    assert (
        gate._conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE id='deleted'"
        ).fetchone()[0]
        == 0
    )


def test_sse_stream_delivers_first_chunk_before_provider_finishes():
    import base64
    import httpx
    from backend.app.models.api_schemas import TTSRequest

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"event: start\ndata: {}\n\n"
            audio = base64.b64encode(b"\1\0" * 30).decode()
            yield f'event: chunk\ndata: {{"chunk_index":1,"audio":"{audio}"}}\n\n'.encode()
            await terminal_allowed.wait()
            yield b'event: complete\ndata: {"chunk_index":2,"audio":"","is_final":true}\n\n'

    async def go():
        nonlocal terminal_allowed
        terminal_allowed = asyncio.Event()
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(200, stream=Body())
            )
        ) as client:
            adapter = GnaniSpeechAdapter(api_key="test-only", http_client=client)
            stream = adapter.iter_tts_audio_events(
                TTSRequest(session_id="stream", text="Hello.")
            )
            first = await asyncio.wait_for(anext(stream), 1)
            chunk = await asyncio.wait_for(anext(stream), 1)
            assert first.event_type == "start" and chunk.event_type == "chunk"
            assert not terminal_allowed.is_set()
            terminal_allowed.set()
            remaining = [event async for event in stream]
            assert remaining[-1].event_type == "complete"

    terminal_allowed = None
    asyncio.run(go())


def test_cancellation_records_dispatched_speech_as_uncertain():
    class Adapter:
        async def transcribe_rest(self, req, wav):
            entered.set()
            await asyncio.Event().wait()

    async def go():
        nonlocal entered
        entered = asyncio.Event()
        gate = SpeechGatekeeper(Adapter())
        job = asyncio.create_task(
            gate.execute_stt(
                STTRequest(session_id="cancel"),
                generate_sine_wav_bytes(duration_sec=0.1),
            )
        )
        await entered.wait()
        job.cancel()
        with pytest.raises(asyncio.CancelledError):
            await job
        cap = gate.get_capacity_status()
        assert cap.stt_seconds_reserved == 0
        assert cap.uncertain_requests_count == 1
        assert cap.stt_seconds_uncertain > 0

    entered = None
    asyncio.run(go())


def test_model_claim_is_bound_unconfirmed_and_preserves_nullable_confidence():
    import httpx
    from uuid import uuid4
    from backend.app.coaching.claim_extractor import ModelAssistedClaimExtractor
    from backend.app.models.enums import ExtractionMethod

    cid = uuid4()
    claim = {
        "claim_type": "OUTPUT_PREDICTION_AND_REASON",
        "challenge_id": str(cid),
        "predicted_output": 3,
        "extraction_method": "MODEL_ASSISTED",
        "critical_tokens": ["3"],
        "confirmed_at": None,
    }
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200, json={"choices": [{"message": {"content": json.dumps(claim)}}]}
            )
        )
    )
    extractor = ModelAssistedClaimExtractor(
        api_key="test-only", model="test-model", http_client=client
    )
    result = extractor.extract("It returns three", challenge_id=cid)
    assert result.extraction_method == ExtractionMethod.MODEL_ASSISTED
    assert result.confirmed_at is None and result.provider_confidence is None
    claim["challenge_id"] = str(uuid4())
    result = extractor.extract("3", challenge_id=cid)
    assert (
        result.challenge_id == cid
        and result.extraction_method == ExtractionMethod.DETERMINISTIC
    )
    client.close()


def test_live_ws_forwards_first_browser_frame_before_capture_finishes():
    from backend.app.speech.ws_streamer import GnaniWebSocketSTTRelay

    class Connection:
        def __init__(self):
            self.first = True

        async def send(self, value):
            if isinstance(value, bytes):
                first_sent.set()
            else:
                committed.set()

        async def recv(self):
            if self.first:
                self.first = False
                return json.dumps({"type": "connected", "request_id": "live-provider"})
            await committed.wait()
            if not transcript_sent.is_set():
                transcript_sent.set()
                return json.dumps(
                    {
                        "type": "transcript",
                        "request_id": "live-provider",
                        "text": "returns one",
                        "segment_id": "s1",
                        "is_final": True,
                    }
                )
            await asyncio.Event().wait()

    @asynccontextmanager
    async def connect(url, **kwargs):
        yield Connection()

    async def frames():
        yield b"\1\0" * 512
        await asyncio.wait_for(first_sent.wait(), 1)
        yield b"\1\0" * 512

    async def go():
        nonlocal first_sent, committed, transcript_sent
        first_sent = asyncio.Event()
        committed = asyncio.Event()
        transcript_sent = asyncio.Event()
        gate = SpeechGatekeeper(GnaniSpeechAdapter(api_key="test-only"))
        relay = GnaniWebSocketSTTRelay(gate, connect_fn=connect, pace_frames=False)
        result = await relay.transcribe_live(
            STTRequest(session_id="live-test"), frames()
        )
        assert result.transport == "WS_V3"
        assert result.audio_duration_sec == 2048 / 32000
        assert gate.get_capacity_status().stt_seconds_used == round(
            result.audio_duration_sec, 4
        )
        assert gate.get_capacity_status().stt_seconds_reserved == 0

    first_sent = committed = transcript_sent = None
    asyncio.run(go())


def test_cache_session_identity_and_playback_speed_do_not_collide(tmp_path):
    from backend.app.speech.tts_cache import TTSDiskCache

    cache = TTSDiskCache(tmp_path)
    key = cache.compute_cache_key(normalized_text="Hello")
    assert cache._target_path(key, session_id="a/b") != cache._target_path(
        key, session_id="ab"
    )
    assert key != cache.compute_cache_key(normalized_text="Hello", speed=1.1)


def test_stt_malformed_success_cannot_become_empty_transcript_and_released_usage():
    import httpx
    from backend.app.speech.gnani_adapter import GnaniTransportError

    async def go():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(
                    200,
                    json={"success": True, "transcript": {"hallucinated": "object"}},
                )
            )
        ) as client:
            gate = SpeechGatekeeper(
                GnaniSpeechAdapter(api_key="test-only", http_client=client)
            )
            with pytest.raises(GnaniTransportError):
                await gate.execute_stt(
                    STTRequest(session_id="invalid-response"),
                    generate_sine_wav_bytes(duration_sec=0.1),
                )
            assert gate.get_capacity_status().uncertain_requests_count == 1
            assert gate.get_capacity_status().stt_seconds_reserved == 0

    asyncio.run(go())


def test_restart_preserves_abandoned_budget_as_uncertain(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    first = SpeechGatekeeper(GnaniSpeechAdapter(api_key="test-only"), db_path=path)
    first._reserve_usage(
        session_id="restarted", turn_generation=1, operation_type="STT", est_stt_sec=3
    )
    first._conn.close()
    restarted = SpeechGatekeeper(GnaniSpeechAdapter(api_key="test-only"), db_path=path)
    assert restarted.recover_pending_usage() == 1
    assert restarted.recover_pending_usage() == 0
    cap = restarted.get_capacity_status()
    assert cap.stt_seconds_reserved == 0
    assert cap.stt_seconds_uncertain == 3
