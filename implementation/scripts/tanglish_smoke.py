"""Newly authorized, two-call synthetic Tamil-English diagnostic only.

One TTS call and one REST codemix STT call; no replay, WS or retry. This is a
nonpersonal synthetic example, not a human accuracy benchmark. Retained audio
belongs in private local data storage, never source archives or uploads.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys

IMPLEMENTATION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(IMPLEMENTATION))

from backend.app.core.config import Settings
from backend.app.models.api_schemas import STTRequest, TTSAudioConfig, TTSRequest
from backend.app.models.enums import LanguageMode
from backend.app.speech.audio_utils import inspect_and_validate_stt_wav
from backend.app.speech.gatekeeper import SpeechGatekeeper
from backend.app.speech.gnani_adapter import GnaniSpeechAdapter, GnaniTransportError
from backend.app.speech.pre_tts_normalizer import to_speakable

TANGLISH_TEXT = "இந்த code ல nums array sum ஐ target உடன் compare பண்ணும். left index update ஆகும். negative value இருந்தால் answer மாறும்."
EXPECTED_PROGRAMMING_TOKENS = ('nums', 'sum', 'target', 'left', 'index', 'negative', 'answer')
SOURCE_CONTEXT = 'def shortest_subarray_ge_target(nums, target):\n    left = 0\n    answer = 0\n    return answer\n'


def _write_private_new(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, 'wb') as file:
        file.write(data)


def _token_evidence(transcript: str) -> dict[str, object]:
    actual = set(re.findall(r'[a-z][a-z_]*', transcript.lower()))
    return {'expected': list(EXPECTED_PROGRAMMING_TOKENS),
            'matched': [token for token in EXPECTED_PROGRAMMING_TOKENS if token in actual],
            'missing': [token for token in EXPECTED_PROGRAMMING_TOKENS if token not in actual],
            'basis': 'Exact case-insensitive Latin tokens in RAW provider transcript; no corrections or inferred matches.'}


async def run_tanglish_smoke(settings: Settings, output_dir: Path, *, adapter_factory=GnaniSpeechAdapter) -> dict[str, object]:
    summary: dict[str, object] = {
        'status': 'BLOCKED_EXTERNAL', 'timestamp': datetime.now(timezone.utc).isoformat(),
        'provider_calls': 0, 'tts_characters': 0, 'stt_seconds': 0.0, 'retries': 0,
        'limits': {'provider_calls': 2, 'tts_characters': 300, 'stt_seconds': 15},
        'input_type': 'SYNTHESIZED_TAMIL_ENGLISH_CODE_MIX', 'human_accuracy_claimed': False,
        'expected_text': TANGLISH_TEXT, 'tts_language': 'auto',
        'stt_languages': 'ta-IN,en-IN', 'stt_format': 'codemix',
        'credit_remaining_status': 'UNKNOWN_UNVERIFIED_TARIFF',
    }
    chunks = to_speakable(TANGLISH_TEXT)
    if len(chunks) != 1 or sum(map(len, chunks)) > 300:
        return {**summary, 'reason': 'Synthetic text exceeds the reviewed single-call limit.'}
    if settings.gnani_api_key is None or settings.gnani_base_url.rstrip('/') != 'https://api.vachana.ai':
        return {**summary, 'reason': 'Missing/placeholder credential or unapproved provider origin; no calls.'}
    adapter = adapter_factory(api_key=settings.gnani_api_key.get_secret_value())
    gate = SpeechGatekeeper(adapter, db_path=output_dir/'usage.sqlite', max_429_retries=0,
                           global_daily_call_limit=2, max_stt_seconds_budget=15, max_tts_chars_budget=300)
    stage = 'TTS_SYNTHETIC_TAMIL_ENGLISH'
    try:
        async with asyncio.timeout(60):
            request = TTSRequest(session_id='bounded-tanglish-synthetic', text=TANGLISH_TEXT,
                                 language='auto', model=settings.gnani_tts_model, voice=settings.gnani_tts_voice,
                                 audio_config=TTSAudioConfig(sample_rate=16000))
            summary.update(provider_calls=1, tts_characters=sum(map(len, chunks)))
            synthesis = await gate.execute_tts(request)
            inspection = inspect_and_validate_stt_wav(synthesis.wav_bytes)
            path = output_dir/'tanglish.wav'
            _write_private_new(path, synthesis.wav_bytes)
            summary['tts'] = {'configured_model': request.model, 'voice': request.voice,
                              'language': request.language, 'duration_seconds': inspection.duration_sec,
                              'sample_rate': 16000, 'wav_bytes': len(synthesis.wav_bytes),
                              'wav_sha256': hashlib.sha256(synthesis.wav_bytes).hexdigest(),
                              'retained_private_path': str(path), 'latency_ms': synthesis.latency_ms}
            if inspection.duration_sec > 15:
                return {**summary, 'reason': 'Generated audio exceeds 15-second upload limit; no STT dispatched.'}
            stage = 'STT_SYNTHETIC_CODEMIX'
            async def dispatch(req, wav):
                summary['provider_calls'] += 1
                summary['stt_seconds'] = inspection.duration_sec
                return await adapter.transcribe_rest(req, wav)
            result = await gate.execute_stt(STTRequest(session_id='bounded-tanglish-synthetic',
                                                       language_mode=LanguageMode.TA_IN_EN_IN, source_code=SOURCE_CONTEXT),
                                            synthesis.wav_bytes, transcribe_fn=dispatch)
            raw = result.raw_transcript
            summary['stt'] = {'raw_transcript': raw, 'normalized_transcript': result.normalized_transcript,
                              'configured_model': result.configured_model, 'provider_model': result.provider_model,
                              'provider_response_request_id': result.provider_request_id,
                              'client_request_id': result.client_request_id,
                              'request_id_provenance': 'Observed response ID may echo client correlation; not independent provider identity.',
                              'detected_language_code': result.detected_language_code,
                              'provider_confidence': result.provider_confidence,
                              'transport': result.transport, 'latency_ms': result.latency_ms}
            summary['programming_tokens'] = _token_evidence(raw)
            summary['tamil_script_observed'] = any('஀' <= character <= '௿' for character in raw)
            summary['latin_tokens_observed'] = bool(re.search('[A-Za-z]', raw))
            summary['status'] = 'PASS_SYNTHETIC_CODEMIX' if raw.strip() else 'EMPTY_SYNTHETIC_TRANSCRIPT'
    except GnaniTransportError as exc:
        summary.update(stage=stage, http_status=exc.status_code,
                       reason='Provider rejection or protocol failure; stopped without retry or another call.')
    except TimeoutError:
        summary.update(stage=stage, reason='Diagnostic deadline reached; cancelled and uncertain usage retained.')
    except Exception as exc:
        summary.update(stage=stage, error_type=type(exc).__name__, reason='Local diagnostic gate stopped further calls.')
    finally:
        summary['ledger'] = gate.get_capacity_status().model_dump(mode='json')
        gate._conn.close()
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Only one newly authorized synthetic Tanglish TTS/STT pair.')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--private-output-dir', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.live or not args.env_file or not args.env_file.is_file():
        summary = {'status':'NOT_RUN','reason':'Explicit --live and private --env-file required; no provider calls.'}
    else:
        if args.private_output_dir.exists() or args.private_output_dir.is_symlink():
            parser.error('Private output must be a new directory, never an existing cache or checkpoint.')
        args.private_output_dir.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        args.private_output_dir.mkdir(mode=0o700)
        summary = asyncio.run(run_tanglish_smoke(Settings(_env_file=args.env_file), args.private_output_dir))
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    _write_private_new(args.evidence, (json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)+'\n').encode())
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary['status'] in {'PASS_SYNTHETIC_CODEMIX','NOT_RUN'} else 2


if __name__ == '__main__':
    raise SystemExit(main())
