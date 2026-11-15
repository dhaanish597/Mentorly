"""One synthetic SSE TTS + one live WS STT; no retries or REST fallback.

Requires --live. Never prints credentials, provider bodies, or transcripts.
The mixed English/Tamil fixture exercises Tanglish configuration, not human ASR.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.models.api_schemas import STTRequest, TTSAudioConfig, TTSRequest
from backend.app.models.enums import ExerciseId, LanguageMode, SpecVersion
from backend.app.speech.audio_utils import inspect_and_validate_tts_wav
from backend.app.speech.gatekeeper import SpeechGatekeeper
from backend.app.speech.gnani_adapter import (
    GnaniSpeechAdapter,
    GnaniTransportError,
    build_ws_stt_init_frame,
)
from backend.app.speech.ws_streamer import (
    GnaniWebSocketSTTRelay,
    strip_wav_header_to_raw_pcm16,
)
from scripts.smoke_gnani import _load_env_file_if_present


def safe_failure_category(exc):
    """Map application-owned messages; never return provider text."""
    known = {
        "WS transcript omitted its final flag.": "transcript_final_flag_missing",
        "Gnani WS did not acknowledge configuration.": "configuration_not_acknowledged",
        "Gnani WS rejected the stream.": "provider_error_event",
        "Gnani WS handshake rejected.": "handshake_rejected",
        "Gnani WS transport unavailable; live work is unconfirmed.": "transport_unavailable",
    }
    return known.get(str(exc), "unclassified_transport_error")


def diagnostic_connector(metrics, *, single_tamil_probe=False):
    """Observe event shapes without recording text, headers or bodies."""
    from websockets.asyncio.client import connect

    @asynccontextmanager
    async def observed_connect(*args, **kwargs):
        if single_tamil_probe:
            # Explicit diagnostic override; current production mapping uses the same wire values.
            headers = dict(kwargs["additional_headers"])
            headers["language_code"] = "ta-IN"
            headers["format"] = "codemix"
            kwargs["additional_headers"] = headers
        async with connect(*args, **kwargs) as ws:
            metrics["ws_handshake_completed"] = True

            class Socket:
                async def send(self, value):
                    await ws.send(value)

                async def recv(self):
                    value = await ws.recv()
                    try:
                        event = json.loads(value)
                    except (ValueError, TypeError):
                        metrics["ws_invalid_json_seen"] = True
                        return value
                    if isinstance(event, dict):
                        kind = event.get("type")
                        allowed = {"connected", "processing", "speech_start", "transcript", "error"}
                        label = kind if isinstance(kind, str) and kind in allowed else "other"
                        counts = metrics.setdefault("ws_event_counts", {})
                        counts[label] = counts.get(label, 0) + 1
                        if kind == "transcript":
                            metrics["ws_transcript_final_flag_is_boolean"] = isinstance(event.get("is_final"), bool)
                    return value

            yield Socket()

    return observed_connect


FIXTURE = "The answer is three. பதில் மூன்று."


async def run_probe(env_file: Path | None = None, *, single_tamil_probe=False) -> dict:
    _load_env_file_if_present(env_file)
    if not os.environ.get("VCC_GNANI_API_KEY", "").strip():
        return {"status": "BLOCKED_EXTERNAL", "stage": "configuration"}
    stage = "tts_sse"
    metrics = {"synthetic_audio": True, "human_accuracy_validated": False,
               "maximum_tts_calls": 1, "maximum_stt_calls": 1,
               "retries": 0, "rest_fallback": False}
    with tempfile.TemporaryDirectory(prefix="mentorly-streaming-") as tmp:
        adapter = GnaniSpeechAdapter(api_key=os.environ["VCC_GNANI_API_KEY"])
        gate = SpeechGatekeeper(adapter, db_path=Path(tmp) / "ledger.sqlite3",
                                max_429_retries=0, max_tts_chars_budget=100,
                                max_stt_seconds_budget=30, global_daily_call_limit=2)
        counts = {}
        first_chunk_ms = None
        start = time.perf_counter()

        async def event_seen(event):
            nonlocal first_chunk_ms
            counts[event.event_type] = counts.get(event.event_type, 0) + 1
            if event.event_type == "chunk" and first_chunk_ms is None:
                first_chunk_ms = round((time.perf_counter() - start) * 1000)

        try:
            async with asyncio.timeout(65):
                tts = await gate.execute_tts(TTSRequest(
                    session_id="mentorly-streaming-probe", text=FIXTURE,
                    language="auto", audio_config=TTSAudioConfig(sample_rate=16000)),
                    on_event=event_seen)
                info = inspect_and_validate_tts_wav(tts.wav_bytes, expected_sample_rate_hz=16000)
                metrics.update(tts_event_counts=counts, tts_first_chunk_ms=first_chunk_ms,
                               tts_audio_seconds=round(info.duration_sec, 3))
                if info.duration_sec > 10:
                    return dict(metrics, status="FAIL", stage="audio_duration_guard")
                raw = strip_wav_header_to_raw_pcm16(tts.wav_bytes)

                async def frames():
                    for offset in range(0, len(raw), 1024):
                        yield raw[offset:offset + 1024]

                stage = "stt_ws_live"
                req = STTRequest(session_id="mentorly-streaming-probe", turn_generation=1,
                                 capture_attempt_id=1, exercise_id=ExerciseId.EX1_SHORTEST_SUBARRAY,
                                 spec_version=SpecVersion.EX1_V1_POSITIVE_ONLY,
                                 language_mode=LanguageMode.TA_IN_EN_IN,
                                 source_code="def answer():\n    return 3\n")
                result = await GnaniWebSocketSTTRelay(
                    gate, connect_fn=diagnostic_connector(metrics, single_tamil_probe=single_tamil_probe)
                ).transcribe_live(req, frames())
                metrics.update(stt_transport=result.transport,
                               stt_latency_ms=result.latency_ms,
                               stt_audio_seconds=round(result.audio_duration_sec, 3),
                               transcript_characters=len(result.raw_transcript),
                               language_mode=req.language_mode.value,
                               probe_wire_language="ta-IN" if single_tamil_probe else build_ws_stt_init_frame(req)["language_code"],
                               fixture_exact_match=result.raw_transcript.strip() == FIXTURE,
                               fixture_english_answer_present="three" in result.raw_transcript.lower(),
                               fixture_tamil_answer_present="மூன்று" in result.raw_transcript)
                passed = (
                    counts.get("chunk", 0) > 0
                    and metrics["fixture_english_answer_present"]
                    and metrics["fixture_tamil_answer_present"]
                )
                return dict(metrics, status="PASS" if passed else "FAIL", stage="complete")
        except GnaniTransportError as exc:
            return dict(metrics, status="BLOCKED_EXTERNAL", stage=stage,
                        http_status=exc.status_code, failure_category=safe_failure_category(exc))
        except Exception as exc:  # noqa: BLE001 - sanitize the CLI trust boundary
            # Exception messages can contain provider bodies or request headers.
            return dict(metrics, status="FAIL", stage=stage, error_type=type(exc).__name__)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--single-tamil-probe", action="store_true",
                        help="Force ta-IN/codemix for diagnostics; current production WS mapping already uses these values.")
    args = parser.parse_args(argv)
    result = asyncio.run(run_probe(args.env_file, single_tamil_probe=args.single_tamil_probe)) if args.live else {
        "status": "BLOCKED_EXTERNAL", "stage": "explicit_live_flag_required"}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
