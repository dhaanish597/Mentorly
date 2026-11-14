"""Phase 9 Public Generic TTS Cache Pre-Warmer (`scripts/prewarm_tts_cache.py`).

Synthesizes canonical onboarding and static UI prompts through `SpeechGatekeeper` (`max_concurrency=1`)
with `cache_scope="PUBLIC_GENERIC"`. Reports `BLOCKED_EXTERNAL` cleanly when `VCC_GNANI_API_KEY` is unset.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.models.api_schemas import TTSRequest  # noqa: E402
from backend.app.speech.gatekeeper import SpeechGatekeeper  # noqa: E402
from backend.app.speech.gnani_adapter import GnaniSpeechAdapter  # noqa: E402
from backend.app.speech.tts_cache import TTSDiskCache  # noqa: E402

PUBLIC_ONBOARDING_PROMPTS: tuple[str, ...] = (
    "Welcome to Voice Coding Coach. Explain your approach and predict what your function returns on the challenge input.",
    "Please confirm or edit your transcript before running the isolated verification check.",
    "Negative integers are now permitted under the updated specification. Please acknowledge the domain change.",
)


async def prewarm_public_prompts(cache_dir: Path, db_path: Path) -> dict[str, object]:
    api_key = os.environ.get("VCC_GNANI_API_KEY", "").strip()
    if not api_key:
        return {
            "status": "BLOCKED_EXTERNAL",
            "reason": "VCC_GNANI_API_KEY is not set; skipped live TTS cache pre-warming.",
            "warmed_count": 0,
        }

    cache = TTSDiskCache(cache_dir)
    adapter = GnaniSpeechAdapter(api_key=api_key, tts_cache=cache)
    gatekeeper = SpeechGatekeeper(adapter, db_path=db_path, max_429_retries=0)
    warmed = 0
    for idx, prompt in enumerate(PUBLIC_ONBOARDING_PROMPTS):
        req = TTSRequest(
            session_id="public_prewarm",
            turn_generation=idx + 1,
            text=prompt,
            cache_scope="PUBLIC_GENERIC",
        )
        await gatekeeper.execute_tts(req)
        warmed += 1

    return {
        "status": "PASS",
        "warmed_count": warmed,
        "ledger": gatekeeper.get_capacity_status().model_dump(mode="json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-warm PUBLIC_GENERIC TTS cache entries.")
    parser.add_argument("--cache-dir", type=Path, default=REPO_ROOT / "data" / "tts_cache")
    parser.add_argument("--db-path", type=Path, default=REPO_ROOT / "data" / "vcc.db")
    parser.add_argument("--allow-blocked", action="store_true")
    args = parser.parse_args()

    res = asyncio.run(prewarm_public_prompts(args.cache_dir, args.db_path))
    print(json.dumps(res, indent=2))
    if res["status"] == "BLOCKED_EXTERNAL":
        return 0 if args.allow_blocked else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
