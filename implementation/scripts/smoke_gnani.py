"""Dispatcher-Routed Gnani STT & SSE TTS Live Smoke Script (`scripts/smoke_gnani.py`).

Security & Cost Discipline (Plan §8 / Phase 2 Prompt §B.7 & P2 Repair):
- Reads `VCC_GNANI_API_KEY` exclusively from the environment (or an optional local `.env` file
  such as `/Users/dhaanish/Desktop/VIVA/.env` via `--env-file`).
- Never embeds, echoes, prints, or writes any secret value to logs or artifacts.
- Uses canonical `ExerciseId.EX1_SHORTEST_SUBARRAY` and one short genuine TTS
  utterance followed by one STT transcription of that spoken synthetic clip.
  This checks provider protocol, never human ASR accuracy.
- Disables retries on auth/schema/quota errors (`max_429_retries=0`) to protect credits.
- If `VCC_GNANI_API_KEY` is absent, exits cleanly with status `BLOCKED_EXTERNAL` (exit code 0
  when `--allow-blocked` is set, or 2 otherwise) so offline CI/Colab runs report honest status.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.models.api_schemas import STTRequest, TTSAudioConfig, TTSRequest  # noqa: E402
from backend.app.models.enums import ExerciseId, LanguageMode, SpecVersion  # noqa: E402
from backend.app.speech.audio_utils import (  # noqa: E402
    inspect_and_validate_tts_wav,
)
from backend.app.speech.gatekeeper import SpeechGatekeeper  # noqa: E402
from backend.app.speech.gnani_adapter import GnaniSpeechAdapter, GnaniTransportError  # noqa: E402
from backend.app.speech.tts_cache import TTSDiskCache  # noqa: E402

DEFAULT_LOCAL_ENV_PATH = Path("/Users/dhaanish/Desktop/VIVA/.env")


def _load_env_file_if_present(env_path: Path | None) -> None:
    """Load `VCC_GNANI_API_KEY` from a local `.env` file if not already set in `os.environ`."""
    if os.environ.get("VCC_GNANI_API_KEY", "").strip():
        return
    candidates: list[Path] = []
    if env_path is not None:
        candidates.append(env_path)
    candidates.append(REPO_ROOT / ".env")
    candidates.append(DEFAULT_LOCAL_ENV_PATH)

    for candidate in candidates:
        try:
            if not candidate.is_file():
                continue
            for raw_line in candidate.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[len("export ") :].strip()
                k, v = line.split("=", 1)
                key = k.strip()
                val = v.strip().strip("'").strip('"')
                if key == "VCC_GNANI_API_KEY" and val:
                    os.environ["VCC_GNANI_API_KEY"] = val
                    return
        except OSError:
            continue


async def run_live_smoke(env_file: Path | None = None) -> dict[str, object]:
    _load_env_file_if_present(env_file)
    api_key = os.environ.get("VCC_GNANI_API_KEY", "").strip()
    if not api_key:
        return {
            "status": "BLOCKED_EXTERNAL",
            "reason": "VCC_GNANI_API_KEY is not set in environment.",
            "stt_smoke": "BLOCKED_EXTERNAL",
            "tts_smoke": "BLOCKED_EXTERNAL",
        }

    with tempfile.TemporaryDirectory() as tmp_dir:
        cache = TTSDiskCache(Path(tmp_dir) / "tts_cache")
        adapter = GnaniSpeechAdapter(tts_cache=cache)
        gatekeeper = SpeechGatekeeper(
            adapter,
            db_path=Path(tmp_dir) / "ledger.sqlite3",
            max_429_retries=0,
            max_stt_seconds_budget=10,
            max_tts_chars_budget=100,
        )

        # A genuine spoken clip from one short TTS call, not an unvoiced tone.
        tts_req = TTSRequest(
            session_id="smoke_sess_p2",
            turn_generation=1,
            text="The program returns three.",
            audio_config=TTSAudioConfig(sample_rate=16000),
        )
        try:
            tts_res = await gatekeeper.execute_tts(tts_req)
        except GnaniTransportError as exc:
            return {
                "status": "BLOCKED_EXTERNAL",
                "stage": "TTS",
                "http_status": exc.status_code,
                "reason": "Provider rejected or could not complete the bounded TTS request; no STT attempted.",
            }
        wav_bytes = tts_res.wav_bytes
        stt_req = STTRequest(
            session_id="smoke_sess_p2",
            turn_generation=1,
            capture_attempt_id=1,
            exercise_id=ExerciseId.EX1_SHORTEST_SUBARRAY,
            spec_version=SpecVersion.EX1_V1_POSITIVE_ONLY,
            language_mode=LanguageMode.EN_IN,
            source_code="def shortest_subarray_ge_target(nums, target):\n    return 0\n",
        )
        try:
            stt_res = await gatekeeper.execute_stt(stt_req, wav_bytes)
        except GnaniTransportError as exc:
            return {
                "status": "BLOCKED_EXTERNAL",
                "stage": "STT",
                "http_status": exc.status_code,
                "reason": "Provider rejected or could not complete the bounded STT request; no retry attempted.",
                "tts_request_id": tts_res.request_id,
            }
        wav_info = inspect_and_validate_tts_wav(
            tts_res.wav_bytes,
            expected_sample_rate_hz=tts_req.audio_config.sample_rate,
        )

        cap = gatekeeper.get_capacity_status()
        return {
            "status": "PASS",
            "note": (
                "Synthetic spoken TTS audio validates Gnani STT/TTS protocol roundtrip "
                "and single-concurrency ledger accounting rather than human ASR word accuracy."
            ),
            "stt_smoke": {
                "request_id": stt_res.request_id,
                "client_request_id": stt_res.client_request_id,
                "provider_request_id": stt_res.provider_request_id,
                "observed_format": stt_res.observed_format,
                "duration_sec": stt_res.audio_duration_sec,
                "latency_ms": stt_res.latency_ms,
                "provider_confidence": stt_res.provider_confidence,
                "transcript": stt_res.raw_transcript,
            },
            "tts_smoke": {
                "request_id": tts_res.request_id,
                "wav_byte_len": len(tts_res.wav_bytes),
                "duration_sec": wav_info.duration_sec,
                "cache_hit": tts_res.cache_hit,
                "latency_ms": tts_res.latency_ms,
            },
            "ledger": cap.model_dump(mode="json"),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run bounded Gnani STT/TTS smoke check via SpeechGatekeeper."
    )
    parser.add_argument(
        "--allow-blocked",
        action="store_true",
        help="Return exit code 0 when BLOCKED_EXTERNAL due to missing VCC_GNANI_API_KEY.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Optional path to .env file containing VCC_GNANI_API_KEY.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Explicitly authorize the bounded provider calls.",
    )
    args = parser.parse_args(argv)

    if not args.live:
        summary = {
            "status": "BLOCKED_EXTERNAL",
            "reason": "Live provider check not requested; use --live explicitly.",
        }
    else:
        summary = asyncio.run(run_live_smoke(env_file=args.env_file))
    print(json.dumps(summary, indent=2, sort_keys=True))
    if summary["status"] == "BLOCKED_EXTERNAL":
        return 0 if args.allow_blocked else 2
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
