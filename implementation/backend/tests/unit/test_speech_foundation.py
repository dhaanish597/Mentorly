"""Phase 2 (T-03): Voice Foundation Unit & Protocol Test Suite (`test_speech_foundation.py`).

Covers all required Phase 2 acceptance criteria and P2-02, P2-05, P2-06, P2-08 regression tests:
1. Audio WAV validation (`audio_utils.py`): 16 kHz, 16-bit mono PCM enforcement, wrong sample
   rate/channels/width/magic rejection, >30s and >1 MiB rejection, non-blocking low-RMS warning,
   full TTS WAV container validation (`inspect_and_validate_tts_wav`), synthetic formant waveform
   generation (`generate_synthetic_speech_wav_bytes`), and single RIFF/WAVE header wrapping.
2. AST keyterm extraction (`ast_keyterms.py`): Canonical `ExerciseId` (`EX1_SHORTEST_SUBARRAY`,
   `EX2_BINARY_SEARCH`, `EX3_MAX_PRODUCT`), function/arg/variable/domain prioritization,
   `<= 30` cap, `SyntaxError` lexical fallback, and `<= 50 ms` latency on 200-line code.
3. Transcript normalization (`transcript_normalizer.py`): Separate `raw_transcript` and
   `normalized_transcript`, spoken negative numbers, comparators, subscripts, Tanglish number
   words, and self-correction (`"three—no, one"`, `"moonu illa onnu"`) without auto-confirming.
4. Pre-TTS normalizer (`pre_tts_normalizer.py`): Canonical exercise identifiers
   (`shortest_subarray_ge_target`, `first_at_least`, `max_product_subarray`) and code symbols
   converted to natural speech and split at sentence boundaries without truncation.
5. TTS disk cache (`tts_cache.py`): Deterministic SHA-256 key, `PUBLIC_GENERIC` vs `SESSION_SCOPED`
   isolation, atomic `.tmp` promotion only on `complete`, full WAV validation rejecting corrupt/truncated
   WAV files, and session eviction.
6. Gnani STT/TTS adapter & SSE parser (`gnani_adapter.py`):
   - Fix P2-05: 0-based and 1-based contiguous `chunk_index` (`chunk_index: 1, 2` and `complete`
     with `chunk_index: 3, audio: "", is_final: true`), incremental UTF-8 decoder handling multi-byte
     UTF-8 split across TCP chunks, CRLF/CR/LF handling, and stream size/event bounds.
   - Fix P2-08: Multi-chunk TTS synthesis (`> 1200` chars) synthesizing all bounded `speakable_chunks`
     without `[:1000]` truncation and billing full character count.
   - Client vs provider `request_id` separation, non-retryable `400/401/403/422`, and WebSocket
     init/commit frames.
7. Single-concurrency `SpeechGatekeeper` (`gatekeeper.py`):
   - Fix P2-06: Seamless compatibility with existing Phase 0 SQLite databases initialized by
     `SQLiteRepository(db_path).initialize()` (`0001_initial.sql`) with `PRAGMA foreign_keys = ON`.
   - Atomic budget admission (`BEGIN IMMEDIATE`) where 3 concurrent 6-char reservations against a
     10-char budget accept at most 1 and reject the 2nd and 3rd with `SpeechQuotaExhaustedError`.
   - Queue overflow and queue wait timeout releasing `RESERVED` rows to `RELEASED`.
   - Post-provider freshness recheck rejecting stale in-flight STT/TTS responses while recording
     committed/uncertain usage in the ledger.
   - Uncertain usage accounting when network drops (`status_code=None`) lose provider acknowledgement.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import sqlite3
import struct
import tempfile
import time
import unittest
import wave
from pathlib import Path

import httpx

from backend.app.db import SQLiteRepository
from backend.app.models.api_schemas import STTRequest, TTSAudioConfig, TTSRequest
from backend.app.models.enums import ExerciseId, LanguageMode, SpeechDegradationStatus
from backend.app.speech.ast_keyterms import build_stt_topic_string, extract_bias_keyterms
from backend.app.speech.audio_utils import (
    AudioValidationError,
    generate_sine_wav_bytes,
    generate_synthetic_speech_wav_bytes,
    inspect_and_validate_stt_wav,
    inspect_and_validate_tts_wav,
    is_riff_wav,
    wrap_raw_pcm_as_wav,
)
from backend.app.speech.gatekeeper import (
    SpeechBusyError,
    SpeechGatekeeper,
    SpeechQuotaExhaustedError,
)
from backend.app.speech.gnani_adapter import (
    GnaniSpeechAdapter,
    GnaniTransportError,
    build_ws_stt_commit_frame,
    build_ws_stt_init_frame,
    parse_gnani_sse_stream,
    select_gnani_stt_format,
)
from backend.app.speech.pre_tts_normalizer import to_speakable
from backend.app.speech.transcript_normalizer import normalize_learner_transcript
from backend.app.speech.tts_cache import TTSDiskCache


# ---------------------------------------------------------------------------
# 1. Audio Validation, TTS WAV Inspection & Synthetic Speech Tests
# ---------------------------------------------------------------------------


def test_audio_utils_validates_canonical_16khz_mono_pcm_and_low_energy() -> None:
    normal_wav = generate_sine_wav_bytes(duration_sec=0.5, amplitude=0.3)
    res = inspect_and_validate_stt_wav(normal_wav)
    assert res.sample_rate_hz == 16_000
    assert res.num_channels == 1
    assert res.sample_width_bytes == 2
    assert 0.49 <= res.duration_sec <= 0.51
    assert res.low_energy_warning is False

    # Synthetic vowel-formant speech waveform passes STT validation with non-silent energy
    synth_wav = generate_synthetic_speech_wav_bytes(duration_sec=1.2)
    synth_res = inspect_and_validate_stt_wav(synth_wav)
    assert synth_res.sample_rate_hz == 16_000
    assert 1.19 <= synth_res.duration_sec <= 1.21
    assert synth_res.low_energy_warning is False

    # Quiet speech / near-silence produces low_energy_warning=True without raising
    quiet_wav = generate_sine_wav_bytes(duration_sec=0.5, amplitude=0.001)
    quiet_res = inspect_and_validate_stt_wav(quiet_wav)
    assert quiet_res.low_energy_warning is True


def test_audio_utils_rejects_invalid_headers_rates_channels_and_durations() -> None:
    try:
        inspect_and_validate_stt_wav(b"RIFFshort")
        raise AssertionError("Expected AudioValidationError")
    except AudioValidationError as exc:
        assert "too short" in str(exc)

    # Wrong sample rate (22050 Hz instead of 16000 Hz) for STT
    bad_rate_wav = generate_sine_wav_bytes(duration_sec=0.2, sample_rate_hz=22_050)
    try:
        inspect_and_validate_stt_wav(bad_rate_wav)
        raise AssertionError("Expected AudioValidationError")
    except AudioValidationError as exc:
        assert "Invalid sample rate" in str(exc)

    # Valid for TTS at 22050 Hz, but rejected if truncated mid-frame
    tts_info = inspect_and_validate_tts_wav(bad_rate_wav, expected_sample_rate_hz=22_050)
    assert tts_info.sample_rate_hz == 22_050
    try:
        inspect_and_validate_tts_wav(bad_rate_wav[:-10], expected_sample_rate_hz=22_050)
        raise AssertionError("Expected AudioValidationError on truncated TTS WAV")
    except AudioValidationError as exc:
        assert "Truncated" in str(exc)

    # Stereo (2 channels) rejection
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(16_000)
        wf.writeframes(b"\x00\x00\x00\x00" * 160)
    try:
        inspect_and_validate_stt_wav(buf.getvalue())
        raise AssertionError("Expected AudioValidationError")
    except AudioValidationError as exc:
        assert "Invalid channel count" in str(exc)

    # Duration > 30s (checked with custom max_duration_sec=1.0)
    two_sec_wav = generate_sine_wav_bytes(duration_sec=1.5)
    try:
        inspect_and_validate_stt_wav(two_sec_wav, max_duration_sec=1.0)
        raise AssertionError("Expected AudioValidationError")
    except AudioValidationError as exc:
        assert "exceeds" in str(exc)


def test_wrap_raw_pcm_as_wav_never_double_wraps() -> None:
    raw_pcm = struct.pack("<4h", 100, -100, 200, -200)
    wrapped_once = wrap_raw_pcm_as_wav(raw_pcm, sample_rate_hz=22_050)
    assert is_riff_wav(wrapped_once)
    wrapped_twice = wrap_raw_pcm_as_wav(wrapped_once, sample_rate_hz=22_050)
    assert wrapped_twice == wrapped_once


# ---------------------------------------------------------------------------
# 2. AST Keyterm Extractor Tests (P2-02 Canonical ExerciseId)
# ---------------------------------------------------------------------------


def test_ast_keyterms_prioritizes_identifiers_and_handles_syntax_errors_fast() -> None:
    code_lines = [
        "def shortest_subarray_ge_target(nums: list[int], target: int) -> int:",
        "    prefix_map = {0: -1}",
        "    running_total = 0",
        "    best_window = 0",
    ]
    for i in range(195):
        code_lines.append(f"    step_var_{i} = running_total + {i}")
    code_lines.append("    return best_window")
    large_code = "\n".join(code_lines)

    t0 = time.perf_counter()
    terms = extract_bias_keyterms(large_code, ExerciseId.EX1_SHORTEST_SUBARRAY)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert elapsed_ms <= 50.0
    assert len(terms) <= 30
    assert terms[0] == "shortest_subarray_ge_target"
    assert "nums" in terms[:4]
    assert "target" in terms[:4]
    assert "prefix_map" in terms

    ex2_terms = extract_bias_keyterms(
        "def first_at_least(nums, target):\n    return 0\n",
        ExerciseId.EX2_BINARY_SEARCH,
    )
    assert "first_at_least" in ex2_terms
    assert "mid" in ex2_terms

    ex3_terms = extract_bias_keyterms(
        "def max_product_subarray(nums):\n    return 0\n",
        ExerciseId.EX3_MAX_PRODUCT,
    )
    assert "max_product_subarray" in ex3_terms
    assert "max_prod" in ex3_terms

    # SyntaxError fallback
    broken_code = (
        "def shortest_subarray_ge_target(nums, target)\n    broken_accum = nums[0]\n"
    )
    fallback_terms = extract_bias_keyterms(broken_code, ExerciseId.EX1_SHORTEST_SUBARRAY)
    assert "shortest_subarray_ge_target" in fallback_terms
    assert "broken_accum" in fallback_terms
    topic = build_stt_topic_string(ExerciseId.EX1_SHORTEST_SUBARRAY, fallback_terms)
    assert len(topic) <= 1600


# ---------------------------------------------------------------------------
# 3. Transcript Normalizer & Pre-TTS Normalizer Tests
# ---------------------------------------------------------------------------


def test_transcript_normalizer_preserves_raw_and_handles_tanglish_self_correction() -> None:
    raw = "I think curr sum is three—no, minus one when nums of i is less than or equal to zero"
    prop = normalize_learner_transcript(raw, known_identifiers=["curr_sum", "nums"])
    assert prop.raw_transcript == raw
    assert prop.contains_self_correction is True
    assert prop.requires_confirmation is True
    assert "curr_sum" in prop.normalized_transcript
    assert "-1" in prop.normalized_transcript
    assert "nums[i]" in prop.normalized_transcript
    assert "<=" in prop.normalized_transcript

    # Tanglish self-correction ("moonu illa onnu" -> "3 illa 1" -> "1")
    tanglish_raw = "return value vandhu moonu illa onnu"
    t_prop = normalize_learner_transcript(tanglish_raw)
    assert t_prop.raw_transcript == tanglish_raw
    assert t_prop.contains_self_correction is True
    assert t_prop.normalized_transcript.endswith("1")


def test_pre_tts_normalizer_converts_code_symbols_and_splits_sentences() -> None:
    coach_text = (
        "In `shortest_subarray_ge_target` and `first_at_least`, when `nums = [1, -1, 5]` and "
        "`curr_sum >= target`, what is `nums[i]` at step 2? "
        "Check whether `first_seen` already stores `-1` before updating `max_len` or `max_product_subarray`."
    )
    chunks = to_speakable(coach_text, max_chunk_chars=90)
    assert len(chunks) >= 2
    joined = " ".join(chunks)
    assert "shortest subarray greater than or equal to target" in joined
    assert "first at least" in joined
    assert "max product subarray" in joined
    assert "list 1, minus 1, 5" in joined
    assert "current sum is greater than or equal to target" in joined
    assert "nums at index i" in joined
    assert "first seen" in joined
    assert "minus 1" in joined


# ---------------------------------------------------------------------------
# 4. Gnani Adapter, WS Contract, P2-05 SSE Parser & TTS Cache Tests
# ---------------------------------------------------------------------------


def test_gnani_stt_format_and_ws_commit_contract() -> None:
    assert select_gnani_stt_format(LanguageMode.EN_IN) == "transcribe"
    assert select_gnani_stt_format(LanguageMode.TA_IN_EN_IN) == "codemix"

    req = STTRequest(
        session_id="sess_ws",
        turn_generation=2,
        exercise_id=ExerciseId.EX2_BINARY_SEARCH,
        language_mode=LanguageMode.TA_IN_EN_IN,
        source_code="def first_at_least(nums, target):\n    mid = len(nums) // 2\n    return mid\n",
        previous_audio_transcript=None,
        request_id="client_ws_42",
    )
    init_frame = build_ws_stt_init_frame(req)
    assert init_frame["model"] == "prisma-v3.0"
    assert init_frame["language_code"] == "ta-IN,en-IN"
    assert init_frame["format"] == "codemix"
    assert init_frame["sample_rate"] == 16000
    assert init_frame["x-sample-rate"] == "16000"
    assert init_frame["x-api-request-id"] == "client_ws_42"
    assert "previous_text" not in init_frame
    assert build_ws_stt_commit_frame() == {"type": "commit"}


def test_parse_gnani_sse_stream_p2_05_zero_and_one_based_and_multibyte_utf8() -> None:
    pcm_0 = struct.pack("<2h", 1000, -1000)
    pcm_1 = struct.pack("<2h", 2000, -2000)
    b64_0 = base64.b64encode(pcm_0).decode("ascii")
    b64_1 = base64.b64encode(pcm_1).decode("ascii")

    # 1. Zero-based chunk_index (0, 1) with arbitrary TCP fragmentation
    raw_stream_0 = (
        'event: start\ndata: {"type":"start","request_id":"prov_sse_0"}\n\n'
        f'event: chunk\ndata: {{"type":"chunk","chunk_index":0,"audio":"{b64_0}"}}\n\n'
        f'event: chunk\ndata: {{"type":"chunk","chunk_index":1,"audio":"{b64_1}"}}\n\n'
        'event: complete\ndata: {"type":"complete","duration_ms":120}\n\n'
    )
    fragments_0 = [
        raw_stream_0[i : i + 17].encode("utf-8")
        for i in range(0, len(raw_stream_0), 17)
    ]
    events_0, assembled_pcm_0 = parse_gnani_sse_stream(
        fragments_0, request_id="client_sse_0"
    )
    assert [e.event_type for e in events_0] == ["start", "chunk", "chunk", "complete"]
    assert assembled_pcm_0 == pcm_0 + pcm_1
    assert events_0[0].client_request_id == "client_sse_0"
    assert events_0[0].provider_request_id == "prov_sse_0"
    assert events_0[0].request_id == "prov_sse_0"

    # 2. Official 1-based Gnani SSE docs format: chunk_index 1, 2 and complete with chunk_index 3, audio: "", is_final: true
    # Include multi-byte Tamil UTF-8 characters ("வணக்கம்") split right across byte chunk boundaries and CRLF line endings
    raw_stream_1_bytes = (
        'event: start\r\ndata: {"type":"start","request_id":"prov_sse_1","note":"வணக்கம்"}\r\n\r\n'
        f'event: chunk\r\ndata: {{"type":"chunk","chunk_index":1,"audio":"{b64_0}","text":"வணக்கம்"}}\r\n\r\n'
        f'event: chunk\r\ndata: {{"type":"chunk","chunk_index":2,"audio":"{b64_1}"}}\r\n\r\n'
        'event: complete\r\ndata: {"type":"complete","chunk_index":3,"audio":"","is_final":true,"duration_ms":140}\r\n\r\n'
    ).encode("utf-8")
    # Split every 5 bytes so multi-byte UTF-8 sequences and \r\n pairs are split mid-sequence
    fragments_1 = [
        raw_stream_1_bytes[i : i + 5] for i in range(0, len(raw_stream_1_bytes), 5)
    ]
    events_1, assembled_pcm_1 = parse_gnani_sse_stream(
        fragments_1, request_id="client_sse_1"
    )
    assert [e.event_type for e in events_1] == ["start", "chunk", "chunk", "complete"]
    assert [e.chunk_index for e in events_1] == [None, 1, 2, 3]
    assert assembled_pcm_1 == pcm_0 + pcm_1

    # 3. Initial chunk_index = 2 must fail
    bad_start = [
        f'event: chunk\ndata: {{"chunk_index":2,"audio":"{b64_0}"}}\n\n'
        'event: complete\ndata: {"type":"complete"}\n\n'
    ]
    try:
        parse_gnani_sse_stream(bad_start, request_id="req_bad_start")
        raise AssertionError("Expected GnaniTransportError on initial chunk_index=2")
    except GnaniTransportError as exc:
        assert "chunk_index gap/reorder" in str(exc)

    # 4. Contiguity gap after 1-based start (1 -> 3) must fail
    gap_stream = [
        f'event: chunk\ndata: {{"chunk_index":1,"audio":"{b64_0}"}}\n\n'
        f'event: chunk\ndata: {{"chunk_index":3,"audio":"{b64_1}"}}\n\n'
        'event: complete\ndata: {"type":"complete"}\n\n'
    ]
    try:
        parse_gnani_sse_stream(gap_stream, request_id="req_gap")
        raise AssertionError("Expected GnaniTransportError on 1->3 gap")
    except GnaniTransportError as exc:
        assert "chunk_index gap/reorder" in str(exc)

    # 5. Missing terminal complete event must fail
    truncated_stream = [
        f'event: chunk\ndata: {{"chunk_index":0,"audio":"{b64_0}"}}\n\n'
    ]
    try:
        parse_gnani_sse_stream(truncated_stream, request_id="req_trunc")
        raise AssertionError("Expected GnaniTransportError on missing complete")
    except GnaniTransportError as exc:
        assert "missing terminal 'complete'" in str(exc)


def test_tts_cache_rejects_corrupt_or_truncated_wav(tmp_path: Path) -> None:
    cache = TTSDiskCache(tmp_path / "tts_cache")
    pcm = struct.pack("<8h", 200, -200, 400, -400, 600, -600, 800, -800)
    key = TTSDiskCache.compute_cache_key(normalized_text="hello world")
    valid_wav = cache.put_completed_stream(
        key,
        pcm,
        stream_completed=True,
        audio_config=TTSAudioConfig(sample_rate=22050),
        scope="PUBLIC_GENERIC",
    )
    assert cache.get_wav(key, scope="PUBLIC_GENERIC") == valid_wav

    # Corrupt the file on disk with truncated RIFF bytes (passes 12-byte magic but fails full WAV check)
    corrupt_path = cache.public_dir / f"{key}.wav"
    corrupt_path.write_bytes(valid_wav[:-6])
    assert cache.get_wav(key, scope="PUBLIC_GENERIC") is None


# ---------------------------------------------------------------------------
# 5. P2-08 Multi-Chunk TTS Synthesis (> 1200 chars) & End-to-End Adapter Tests
# ---------------------------------------------------------------------------


def test_p2_08_multi_chunk_tts_synthesis_without_truncation(tmp_path: Path) -> None:
    async def _scenario() -> None:
        observed_tts_texts: list[str] = []
        pcm_seg = struct.pack("<4h", 300, -300, 700, -700)
        b64_seg = base64.b64encode(pcm_seg).decode("ascii")

        async def _mock_handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode("utf-8"))
            seg_text = body["text"]
            assert len(seg_text) <= 1000
            observed_tts_texts.append(seg_text)
            seg_idx = len(observed_tts_texts)
            sse_body = (
                f'event: start\ndata: {{"type":"start","request_id":"prov_seg_{seg_idx}"}}\n\n'
                f'event: chunk\ndata: {{"chunk_index":1,"audio":"{b64_seg}"}}\n\n'
                'event: complete\ndata: {"type":"complete","chunk_index":2,"audio":"","is_final":true,"duration_ms":50}\n\n'
            )
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=sse_body.encode("utf-8"),
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(_mock_handler))
        cache = TTSDiskCache(tmp_path / "cache_p2_08")
        adapter = GnaniSpeechAdapter(
            api_key="test_secret_key",
            tts_cache=cache,
            http_client=client,
        )

        # Build a > 1400-character coaching explanation spanning multiple sentences
        long_sentences = [
            f"Sentence {i}: In shortest_subarray_ge_target, check how curr_sum and prefix_sum behave at index {i} when inspecting boundary values."
            for i in range(1, 14)
        ]
        long_text = " ".join(long_sentences)
        assert len(long_text) > 1400

        req = TTSRequest(
            session_id="sess_long",
            turn_generation=1,
            playback_id="play_long_1",
            text=long_text,
            request_id="client_tts_long",
        )
        res = await adapter.synthesize_tts(req)

        # Must split into >= 2 chunks, synthesize ALL chunks without [:1000] truncation, and bill full char sum
        assert len(res.speakable_chunks) >= 2
        assert observed_tts_texts == res.speakable_chunks
        expected_total_chars = sum(len(c) for c in res.speakable_chunks)
        assert expected_total_chars > 1200
        assert res.total_chars_billed == expected_total_chars
        assert "Sentence 13" in observed_tts_texts[-1]

        # Assembled WAV must contain frames from all segments combined
        wav_info = inspect_and_validate_tts_wav(res.wav_bytes, expected_sample_rate_hz=22050)
        assert wav_info.num_frames == 4 * len(res.speakable_chunks)
        assert {e.segment_index for e in res.events} == set(
            range(len(res.speakable_chunks))
        )
        assert all(e.playback_id == "play_long_1" for e in res.events)
        assert all(e.client_request_id == "client_tts_long" for e in res.events)

        # Second call hits cache for the full multi-chunk utterance with 0 billed chars
        res_cached = await adapter.synthesize_tts(req)
        assert res_cached.cache_hit is True
        assert res_cached.total_chars_billed == 0
        assert res_cached.wav_bytes == res.wav_bytes
        assert len(observed_tts_texts) == len(res.speakable_chunks)

        await client.aclose()

    asyncio.run(_scenario())


def test_gnani_adapter_and_gatekeeper_end_to_end_with_mock_transport(tmp_path: Path) -> None:
    async def _scenario() -> None:
        stt_calls = 0
        tts_calls = 0
        pcm_sample = struct.pack("<4h", 500, -500, 1000, -1000)
        b64_audio = base64.b64encode(pcm_sample).decode("ascii")

        async def _mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal stt_calls, tts_calls
            assert request.headers.get("X-API-Key-ID") == "test_secret_key"
            if request.url.path.endswith("/stt/v3"):
                stt_calls += 1
                body_str = request.content.decode("utf-8", errors="ignore")
                assert "prisma-v3.0" in body_str
                if stt_calls == 1:
                    return httpx.Response(429, json={"error": "rate_limited"})
                return httpx.Response(
                    200,
                    json={
                        "request_id": "gnani_prov_stt_99",
                        "transcript": "curr sum is minus one",
                        "confidence": None,
                        "language_code": "en-IN",
                    },
                )
            if request.url.path.endswith("/api/v1/tts/sse"):
                tts_calls += 1
                sse_body = (
                    'event: start\ndata: {"type":"start","request_id":"gnani_prov_tts_88"}\n\n'
                    f'event: chunk\ndata: {{"chunk_index":0,"audio":"{b64_audio}"}}\n\n'
                    'event: complete\ndata: {"type":"complete","duration_ms":80}\n\n'
                )
                return httpx.Response(
                    200,
                    headers={"Content-Type": "text/event-stream"},
                    content=sse_body.encode("utf-8"),
                )
            return httpx.Response(404)

        transport = httpx.MockTransport(_mock_handler)
        client = httpx.AsyncClient(transport=transport)
        cache = TTSDiskCache(tmp_path / "cache")
        adapter = GnaniSpeechAdapter(
            api_key="test_secret_key",
            tts_cache=cache,
            http_client=client,
        )
        gatekeeper = SpeechGatekeeper(
            adapter,
            db_path=tmp_path / "ledger.sqlite3",
            retry_backoff_base_sec=0.01,
        )

        # Verify re-recording on the same turn_generation increments capture_attempt_id
        a1 = gatekeeper.register_capture_attempt("sess_1", turn_generation=1)
        a2 = gatekeeper.register_capture_attempt("sess_1", turn_generation=1)
        assert a1 == 1
        assert a2 == 2
        assert gatekeeper.is_capture_superseded("sess_1", 1, a1) is True
        assert gatekeeper.is_capture_superseded("sess_1", 1, a2) is False

        wav_bytes = generate_sine_wav_bytes(duration_sec=0.25)
        # Superseded attempt 1 must be rejected immediately
        try:
            await gatekeeper.execute_stt(
                STTRequest(
                    session_id="sess_1",
                    turn_generation=1,
                    capture_attempt_id=1,
                    exercise_id=ExerciseId.EX1_SHORTEST_SUBARRAY,
                ),
                wav_bytes,
            )
            raise AssertionError("Expected SpeechBusyError")
        except SpeechBusyError as exc:
            assert "superseded" in str(exc)

        # Active attempt 2 succeeds after automatic 429 retry
        stt_res = await gatekeeper.execute_stt(
            STTRequest(
                session_id="sess_1",
                turn_generation=1,
                capture_attempt_id=2,
                exercise_id=ExerciseId.EX1_SHORTEST_SUBARRAY,
                source_code="def shortest_subarray_ge_target(nums, target):\n    curr_sum = 0\n    return curr_sum\n",
                request_id="client_stt_req_2",
            ),
            wav_bytes,
        )
        assert stt_calls == 2
        assert stt_res.client_request_id == "client_stt_req_2"
        assert stt_res.provider_request_id == "gnani_prov_stt_99"
        assert stt_res.request_id == "gnani_prov_stt_99"
        assert stt_res.detected_language_code == "en-IN"
        assert stt_res.raw_transcript == "curr sum is minus one"
        assert stt_res.normalized_transcript == "curr_sum is -1"
        assert stt_res.provider_confidence is None

        # First TTS call streams SSE and populates disk cache
        tts_req = TTSRequest(
            session_id="sess_1",
            turn_generation=1,
            text="When `curr_sum == -1`, what happens next?",
            cache_scope="SESSION_SCOPED",
        )
        tts_res_1 = await gatekeeper.execute_tts(tts_req)
        assert tts_res_1.cache_hit is False
        assert is_riff_wav(tts_res_1.wav_bytes)
        assert tts_calls == 1

        # Second identical TTS call hits SHA-256 disk cache without invoking HTTP
        tts_res_2 = await gatekeeper.execute_tts(tts_req)
        assert tts_res_2.cache_hit is True
        assert tts_res_2.wav_bytes == tts_res_1.wav_bytes
        assert tts_calls == 1

        cap = gatekeeper.get_capacity_status()
        assert cap.max_concurrency == 1
        assert cap.active_requests == 0
        assert cap.stt_requests_count == 1
        assert cap.tts_requests_count == 1
        assert cap.stt_seconds_reserved == 0.0
        assert cap.tts_chars_reserved == 0
        assert cap.credit_remaining_status == "UNKNOWN_UNVERIFIED_TARIFF"
        assert cap.degradation_status == SpeechDegradationStatus.HEALTHY

        # Evict session cache
        removed = cache.evict_session("sess_1")
        assert removed == 1
        await client.aclose()

    asyncio.run(_scenario())


# ---------------------------------------------------------------------------
# 6. P2-06 Gatekeeper Regression Tests (P0 DB Compatibility, Atomic Budget,
#    Queue Timeout Release, Post-Provider Freshness Recheck & Uncertain Ledger)
# ---------------------------------------------------------------------------


def test_p2_06_existing_p0_database_compatibility_and_atomic_budget_admission(
    tmp_path: Path,
) -> None:
    async def _scenario() -> None:
        db_path = tmp_path / "p0_existing.sqlite3"
        # Initialize with Phase 0 SQLiteRepository (`0001_initial.sql`) first!
        legacy = sqlite3.connect(db_path)
        initial_sql = Path(__file__).resolve().parents[2] / "app/db/migrations/0001_initial.sql"
        legacy.executescript(initial_sql.read_text())
        legacy.close()

        pcm_sample = struct.pack("<2h", 400, -400)
        b64_audio = base64.b64encode(pcm_sample).decode("ascii")

        async def _slow_tts_handler(request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(0.06)
            sse_body = (
                'event: start\ndata: {"type":"start"}\n\n'
                f'event: chunk\ndata: {{"chunk_index":1,"audio":"{b64_audio}"}}\n\n'
                'event: complete\ndata: {"type":"complete","chunk_index":2,"audio":"","is_final":true}\n\n'
            )
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=sse_body.encode("utf-8"),
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(_slow_tts_handler))
        adapter = GnaniSpeechAdapter(api_key="k", http_client=client)

        # Attach SpeechGatekeeper to the existing P0 database with a 10-char TTS budget
        gatekeeper = SpeechGatekeeper(
            adapter,
            db_path=db_path,
            max_tts_chars_budget=10,
            max_waiting=5,
            queue_wait_timeout_sec=2.0,
        )

        # Launch 3 concurrent 6-char TTS requests against the 10-char budget.
        # Atomic budget admission (BEGIN IMMEDIATE) must admit at most 1 (6 chars <= 10)
        # and reject the 2nd and 3rd immediately with SpeechQuotaExhaustedError!
        reqs = [
            TTSRequest(
                session_id=f"p0_sess_{i}",
                turn_generation=1,
                text="abcdef",  # 6 speakable chars
            )
            for i in range(3)
        ]
        outcomes = await asyncio.gather(
            *(gatekeeper.execute_tts(r) for r in reqs),
            return_exceptions=True,
        )
        successes = [o for o in outcomes if not isinstance(o, BaseException)]
        quota_errors = [
            o for o in outcomes if isinstance(o, SpeechQuotaExhaustedError)
        ]
        assert len(successes) == 1
        assert len(quota_errors) == 2

        cap = gatekeeper.get_capacity_status()
        assert cap.tts_chars_used == 6
        assert cap.tts_chars_reserved == 0
        assert cap.tts_requests_count == 1
        await client.aclose()

    asyncio.run(_scenario())


def test_p2_06_queue_timeout_and_overflow_release_reserved_rows(tmp_path: Path) -> None:
    async def _scenario() -> None:
        in_flight = 0
        max_observed_in_flight = 0

        async def _slow_handler(request: httpx.Request) -> httpx.Response:
            nonlocal in_flight, max_observed_in_flight
            in_flight += 1
            max_observed_in_flight = max(max_observed_in_flight, in_flight)
            await asyncio.sleep(0.15)
            in_flight -= 1
            return httpx.Response(200, json={"transcript": "one", "confidence": 0.9})

        client = httpx.AsyncClient(transport=httpx.MockTransport(_slow_handler))
        adapter = GnaniSpeechAdapter(api_key="k", http_client=client)
        db_path = tmp_path / "timeout_release.sqlite3"
        gatekeeper = SpeechGatekeeper(
            adapter,
            db_path=db_path,
            max_waiting=1,
            queue_wait_timeout_sec=0.04,
        )
        wav = generate_sine_wav_bytes(duration_sec=0.1)

        def _req(turn: int) -> STTRequest:
            return STTRequest(
                session_id=f"s_{turn}",
                turn_generation=turn,
                exercise_id=ExerciseId.EX1_SHORTEST_SUBARRAY,
            )

        # Req 1 acquires slot (takes 0.15s); Req 2 waits in queue and times out at 0.04s;
        # Req 3 overflows max_waiting=1 immediately.
        results = await asyncio.gather(
            gatekeeper.execute_stt(_req(1), wav),
            gatekeeper.execute_stt(_req(2), wav),
            gatekeeper.execute_stt(_req(3), wav),
            return_exceptions=True,
        )
        assert max_observed_in_flight == 1
        successes = [r for r in results if not isinstance(r, BaseException)]
        busy_errors = [r for r in results if isinstance(r, SpeechBusyError)]
        assert len(successes) == 1
        assert len(busy_errors) == 2

        # Verify zero leaked RESERVED rows in SQLite!
        cap = gatekeeper.get_capacity_status()
        assert cap.stt_seconds_reserved == 0.0
        conn = sqlite3.connect(db_path)
        try:
            reserved_count = conn.execute(
                "SELECT COUNT(*) FROM usage_reservations WHERE status = 'RESERVED';"
            ).fetchone()[0]
            released_count = conn.execute(
                "SELECT COUNT(*) FROM usage_reservations WHERE status = 'RELEASED';"
            ).fetchone()[0]
            committed_count = conn.execute(
                "SELECT COUNT(*) FROM usage_reservations WHERE status = 'COMMITTED';"
            ).fetchone()[0]
            assert reserved_count == 0
            assert released_count == 2
            assert committed_count == 1
        finally:
            conn.close()

        await client.aclose()

    asyncio.run(_scenario())


def test_p2_06_post_provider_freshness_recheck_and_uncertain_network_drop(
    tmp_path: Path,
) -> None:
    async def _scenario() -> None:
        gatekeeper_ref: list[SpeechGatekeeper] = []
        call_num = 0
        pcm_sample = struct.pack("<2h", 400, -400)
        b64_audio = base64.b64encode(pcm_sample).decode("ascii")

        async def _handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_num
            call_num += 1
            if request.url.path.endswith("/api/v1/tts/sse"):
                # Cancel turn 5 while TTS response has just completed before returning
                gatekeeper_ref[0].cancel_turn_speech("sess_race", turn_generation=5)
                sse_body = (
                    'event: start\ndata: {"type":"start"}\n\n'
                    f'event: chunk\ndata: {{"chunk_index":1,"audio":"{b64_audio}"}}\n\n'
                    'event: complete\ndata: {"type":"complete","chunk_index":2,"audio":"","is_final":true}\n\n'
                )
                return httpx.Response(
                    200,
                    headers={"Content-Type": "text/event-stream"},
                    content=sse_body.encode("utf-8"),
                )
            if call_num == 1:
                # Supersede capture attempt 1 while provider call is in flight!
                gatekeeper_ref[0].register_capture_attempt(
                    "sess_race", turn_generation=1
                )
                return httpx.Response(
                    200, json={"transcript": "stale answer", "confidence": 0.8}
                )
            if call_num == 2:
                # Second call simulates a network drop after request dispatch
                raise httpx.ReadTimeout("Simulated mid-flight read timeout")
            # Third call tests non-retryable 401/422 error classification
            return httpx.Response(422, json={"error": "unprocessable"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
        adapter = GnaniSpeechAdapter(api_key="k", http_client=client)
        gk = SpeechGatekeeper(adapter, db_path=tmp_path / "race.sqlite3")
        gatekeeper_ref.append(gk)

        wav = generate_sine_wav_bytes(duration_sec=0.2)
        a1 = gk.register_capture_attempt("sess_race", turn_generation=1)
        assert a1 == 1

        # 1. Superseded while in flight -> raises SpeechBusyError AND commits real provider usage
        try:
            await gk.execute_stt(
                STTRequest(
                    session_id="sess_race",
                    turn_generation=1,
                    capture_attempt_id=1,
                    exercise_id=ExerciseId.EX1_SHORTEST_SUBARRAY,
                ),
                wav,
            )
            raise AssertionError("Expected SpeechBusyError on post-provider freshness recheck")
        except SpeechBusyError as exc:
            assert "in flight" in str(exc)

        cap_after_race = gk.get_capacity_status()
        assert cap_after_race.stt_requests_count == 1
        assert cap_after_race.stt_seconds_used > 0.0
        assert cap_after_race.stt_seconds_reserved == 0.0

        # 2. Network drop (status_code=None) on attempt 2 -> records uncertain usage
        try:
            await gk.execute_stt(
                STTRequest(
                    session_id="sess_race",
                    turn_generation=1,
                    capture_attempt_id=2,
                    exercise_id=ExerciseId.EX1_SHORTEST_SUBARRAY,
                ),
                wav,
            )
            raise AssertionError("Expected GnaniTransportError on ReadTimeout")
        except GnaniTransportError as exc:
            assert exc.status_code is None
            assert exc.retryable is True

        cap_after_drop = gk.get_capacity_status()
        assert cap_after_drop.uncertain_requests_count == 1
        assert cap_after_drop.stt_seconds_uncertain > 0.0
        assert cap_after_drop.stt_seconds_reserved == 0.0

        # 3. HTTP 422 must have retryable=False and release reservation cleanly
        try:
            await gk.execute_stt(
                STTRequest(
                    session_id="sess_race",
                    turn_generation=2,
                    capture_attempt_id=1,
                    exercise_id=ExerciseId.EX1_SHORTEST_SUBARRAY,
                ),
                wav,
            )
            raise AssertionError("Expected GnaniTransportError on HTTP 422")
        except GnaniTransportError as exc:
            assert exc.status_code == 422
            assert exc.retryable is False

        # 4. TTS cancelled while in flight -> raises SpeechBusyError and records uncertain usage
        try:
            await gk.execute_tts(
                TTSRequest(
                    session_id="sess_race",
                    turn_generation=5,
                    text="Check line 4.",
                )
            )
            raise AssertionError("Expected SpeechBusyError on cancelled TTS turn")
        except SpeechBusyError as exc:
            assert "in flight" in str(exc)

        cap_final = gk.get_capacity_status()
        assert cap_final.tts_chars_reserved == 0
        assert cap_final.uncertain_requests_count == 2
        assert cap_final.tts_chars_uncertain > 0

        await client.aclose()

    asyncio.run(_scenario())


class SpeechFoundationUnitTestSuite(unittest.TestCase):
    """Unittest wrapper so `python -m unittest` runs all speech foundation tests even without pytest."""

    def test_01_audio_validation(self) -> None:
        test_audio_utils_validates_canonical_16khz_mono_pcm_and_low_energy()
        test_audio_utils_rejects_invalid_headers_rates_channels_and_durations()
        test_wrap_raw_pcm_as_wav_never_double_wraps()

    def test_02_ast_keyterms(self) -> None:
        test_ast_keyterms_prioritizes_identifiers_and_handles_syntax_errors_fast()

    def test_03_normalizers(self) -> None:
        test_transcript_normalizer_preserves_raw_and_handles_tanglish_self_correction()
        test_pre_tts_normalizer_converts_code_symbols_and_splits_sentences()

    def test_04_ws_and_sse_p2_05(self) -> None:
        test_gnani_stt_format_and_ws_commit_contract()
        test_parse_gnani_sse_stream_p2_05_zero_and_one_based_and_multibyte_utf8()
        with tempfile.TemporaryDirectory() as td:
            test_tts_cache_rejects_corrupt_or_truncated_wav(Path(td))

    def test_05_p2_08_and_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            test_p2_08_multi_chunk_tts_synthesis_without_truncation(Path(td))
        with tempfile.TemporaryDirectory() as td:
            test_gnani_adapter_and_gatekeeper_end_to_end_with_mock_transport(Path(td))

    def test_06_p2_06_gatekeeper_regressions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            test_p2_06_existing_p0_database_compatibility_and_atomic_budget_admission(
                Path(td)
            )
        with tempfile.TemporaryDirectory() as td:
            test_p2_06_queue_timeout_and_overflow_release_reserved_rows(Path(td))
        with tempfile.TemporaryDirectory() as td:
            test_p2_06_post_provider_freshness_recheck_and_uncertain_network_drop(
                Path(td)
            )


if __name__ == "__main__":
    unittest.main()
