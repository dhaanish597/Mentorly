"""Bounded, explicitly opted-in Gnani protocol smoke with payload-free evidence.

At most four sequential calls (SSE TTS, English REST, codemix REST, WebSocket),
no retries, <=60 seconds aggregate uploaded STT and <=1500 TTS characters.
Never use this concurrently with another account client. No human ASR claim.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile

IMPLEMENTATION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(IMPLEMENTATION))

from backend.app.core.config import Settings
from backend.app.models.api_schemas import STTRequest, TTSAudioConfig, TTSRequest
from backend.app.models.enums import LanguageMode
from backend.app.speech.audio_utils import inspect_and_validate_stt_wav
from backend.app.speech.gatekeeper import SpeechGatekeeper
from backend.app.speech.gnani_adapter import GnaniSpeechAdapter, GnaniTransportError
from backend.app.speech.tts_cache import TTSDiskCache
from backend.app.speech.ws_streamer import GnaniWebSocketSTTRelay

SMOKE_TEXT = "The program returns three. Explain why before running the code."


async def run_smoke(settings: Settings, *, include_ws: bool = False, ws_only: bool = False, adapter_factory=GnaniSpeechAdapter) -> dict[str, object]:
    summary: dict[str, object] = {
        "status": "BLOCKED_EXTERNAL", "timestamp": datetime.now(timezone.utc).isoformat(),
        "limits": {"provider_calls": 4, "stt_seconds": 60, "tts_characters": 1500},
        "provider_calls_attempted": 0, "stt_seconds_attempted": 0.0,
        "tts_characters_attempted": 0, "retries": 0,
        "evidence_type": "synthetic_protocol_only", "credit_remaining_status": "UNKNOWN_UNVERIFIED_TARIFF",
    }
    if settings.gnani_api_key is None:
        return {**summary, "reason": "Missing or placeholder server credential; no provider call."}
    if settings.gnani_base_url.rstrip('/') != 'https://api.vachana.ai':
        return {**summary, "reason": "Live smoke accepts only the documented HTTPS provider origin."}
    with tempfile.TemporaryDirectory(prefix='vcc-provider-smoke-') as directory:
        cache = TTSDiskCache(Path(directory)/'tts')
        adapter = adapter_factory(api_key=settings.gnani_api_key.get_secret_value(), tts_cache=cache)
        gate = SpeechGatekeeper(adapter, db_path=Path(directory)/'usage.sqlite', max_429_retries=0,
                               max_stt_seconds_budget=60, max_tts_chars_budget=1500, global_daily_call_limit=4)
        stage = 'TTS_SSE'
        try:
            async with asyncio.timeout(60):
                request = TTSRequest(session_id='bounded-smoke', text=SMOKE_TEXT,
                                     model=settings.gnani_tts_model, voice=settings.gnani_tts_voice,
                                     audio_config=TTSAudioConfig(sample_rate=16000))
                summary.update(provider_calls_attempted=1, tts_characters_attempted=len(SMOKE_TEXT))
                synthesis = await gate.execute_tts(request)
                summary['tts'] = {'status':'PASS','cache_hit':synthesis.cache_hit,
                                  'wav_bytes':len(synthesis.wav_bytes),'latency_ms':synthesis.latency_ms,
                                  'provider_request_id':next((event.provider_request_id for event in reversed(synthesis.events) if event.provider_request_id), None)}
                # Replay cache admission consumes no provider call and no additional characters.
                replay = await gate.execute_tts(request)
                summary['cache_replay'] = {'status':'PASS' if replay.cache_hit else 'FAIL', 'cache_hit':replay.cache_hit}
                duration = inspect_and_validate_stt_wav(synthesis.wav_bytes).duration_sec
                if duration * (3 if include_ws else 2) > 60:
                    raise ValueError('Generated clip exceeds cumulative smoke upload bound.')
                rest_checks = [] if ws_only else [('STT_EN_REST', LanguageMode.EN_IN), ('STT_CODEMIX_REST', LanguageMode.TA_IN_EN_IN)]
                async def dispatch_rest(req, wav):
                    summary['provider_calls_attempted'] += 1
                    summary['stt_seconds_attempted'] += duration
                    return await adapter.transcribe_rest(req, wav)
                for stage, language in rest_checks:
                    result = await gate.execute_stt(STTRequest(session_id='bounded-smoke', language_mode=language), synthesis.wav_bytes, transcribe_fn=dispatch_rest)
                    summary[stage.lower()] = {'status':'PASS','transport':result.transport,
                                              'format':result.observed_format,'configured_model':result.configured_model,
                                              'provider_model':result.provider_model,'provider_request_id':result.provider_request_id,
                                              'duration_seconds':result.audio_duration_sec,'latency_ms':result.latency_ms,
                                              'confidence_available':result.provider_confidence is not None,
                                              'transcript_nonempty':bool(result.raw_transcript.strip())}
                if include_ws or ws_only:
                    stage = 'STT_WS'
                    relay = GnaniWebSocketSTTRelay(gate)
                    async def dispatch_ws(req, wav):
                        summary['provider_calls_attempted'] += 1
                        summary['stt_seconds_attempted'] += duration
                        return await relay._transcribe(req, wav)
                    result = await gate.execute_stt(STTRequest(session_id='bounded-smoke'), synthesis.wav_bytes,
                                                    transcribe_fn=dispatch_ws)
                    summary['stt_ws'] = {'status':'PASS','transport':result.transport,'provider_request_id':result.provider_request_id}
                summary['status'] = 'PASS'
        except GnaniTransportError as exc:
            summary.update(stage=stage, http_status=exc.status_code,
                           reason='Provider rejected or did not complete the bounded call. Stopped; no retries or further calls.')
        except TimeoutError:
            summary.update(stage=stage, reason='Smoke deadline reached. Cancelled; uncertain usage retained.')
        except Exception as exc:
            summary.update(stage=stage, reason='Smoke stopped on a validation or protocol gate.', error_type=type(exc).__name__)
        finally:
            summary['ledger'] = gate.get_capacity_status().model_dump(mode='json')
            gate._conn.close()
        return summary


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description='Opt-in bounded Gnani protocol smoke; never print secrets.')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--include-ws', action='store_true')
    parser.add_argument('--ws-only', action='store_true', help='Only one TTS and one WS STT; omit REST checks.')
    parser.add_argument('--output', type=Path)
    args=parser.parse_args(argv)
    if not args.live:
        summary={'status':'NOT_RUN','reason':'Live provider work requires --live and an explicit private --env-file.'}
    elif not args.env_file or not args.env_file.is_file():
        summary={'status':'BLOCKED_EXTERNAL','reason':'Explicit private server environment file is required.'}
    else:
        summary=asyncio.run(run_smoke(Settings(_env_file=args.env_file), include_ws=args.include_ws, ws_only=args.ws_only))
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
    print(json.dumps(summary,indent=2,sort_keys=True))
    return 0 if summary['status'] in {'PASS','NOT_RUN'} else 2


if __name__ == '__main__':
    raise SystemExit(main())
