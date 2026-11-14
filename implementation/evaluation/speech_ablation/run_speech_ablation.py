"""Phase 8 Speech Normalization, AST Bias Keyterm Latency & Pre-TTS Ablation Runner (`evaluation/run_speech_ablation.py`).

Implements Plan §14.2 (P8 / T-09):
- Evaluates AST bias keyterm extraction (`extract_bias_keyterms`) on 200-line code inputs and verifies
  latency `<= 50 ms` and keyterm count `<= 30`.
- Evaluates post-STT transcript normalization (`normalize_learner_transcript`) across Indian English,
  Tanglish (`ta-IN,en-IN`), spoken negative numbers, comparators, subscripts, and self-corrections,
  measuring exact token restoration rate with vs without AST identifier bias.
- Evaluates pre-TTS normalization (`to_speakable`) on long multi-sentence coaching outputs (`> 1500` chars)
  to verify zero character truncation and `<= 1000` char bound compliance.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.models.enums import ExerciseId  # noqa: E402
from backend.app.speech.ast_keyterms import extract_bias_keyterms  # noqa: E402
from backend.app.speech.pre_tts_normalizer import to_speakable  # noqa: E402
from backend.app.speech.transcript_normalizer import normalize_learner_transcript  # noqa: E402


def run_speech_ablation() -> dict[str, Any]:
    # 1. 200-line AST keyterm latency benchmark (must be <= 50 ms)
    lines = ["def shortest_subarray_ge_target(nums: list[int], target: int) -> int:"]
    for i in range(195):
        lines.append(f"    prefix_sum_{i % 15} = nums[0] if nums else {i}")
    lines.append("    return 0")
    code_200 = "\n".join(lines)

    t0 = time.perf_counter()
    keyterms = extract_bias_keyterms(code_200, ExerciseId.EX1_SHORTEST_SUBARRAY)
    ast_latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)

    # 2. Normalization ablation: with vs without known_identifiers
    utterances = [
        (
            "when curr sum is greater than or equal to target it returns minus one",
            ["curr_sum", "target"],
            "-1",
            ">=",
            "curr_sum",
        ),
        (
            "Wait it returns three—no, one on nums of zero",
            ["nums", "first_at_least"],
            "1",
            "nums[0]",
            "1",
        ),
        (
            "moonu illa onnu because min prod flips sign",
            ["min_prod", "max_prod"],
            "1",
            "min_prod",
            "1",
        ),
    ]

    with_bias_hits = 0
    without_bias_hits = 0
    for raw, idents, exp_tok1, exp_tok2, exp_ident in utterances:
        prop_with = normalize_learner_transcript(raw, known_identifiers=idents)
        prop_without = normalize_learner_transcript(raw, known_identifiers=[])
        if (
            exp_tok1 in prop_with.normalized_transcript
            and exp_tok2 in prop_with.normalized_transcript
            and exp_ident in prop_with.normalized_transcript
            and prop_with.requires_confirmation is True
        ):
            with_bias_hits += 1
        if exp_ident in prop_without.normalized_transcript:
            without_bias_hits += 1

    # 3. Pre-TTS multi-chunk synthesis check (> 1800 chars)
    long_coach_text = " ".join(
        [
            f"Sentence {idx}: Check nums[i] >= target and curr_sum = -5 in shortest_subarray_ge_target."
            for idx in range(28)
        ]
    )
    chunks = to_speakable(long_coach_text)
    max_chunk_len = max((len(c) for c in chunks), default=0)
    has_tail_sentence = any("Sentence 27" in c for c in chunks)

    overall_pass = (
        ast_latency_ms <= 50.0
        and 1 <= len(keyterms) <= 30
        and with_bias_hits == len(utterances)
        and len(chunks) >= 2
        and max_chunk_len <= 1000
        and has_tail_sentence
    )
    return {
        "overall_pass": overall_pass,
        "ast_keyterms_count": len(keyterms),
        "ast_extraction_latency_ms": ast_latency_ms,
        "with_ast_bias_exact_matches": with_bias_hits,
        "without_ast_bias_exact_matches": without_bias_hits,
        "total_ablation_utterances": len(utterances),
        "tts_chunk_count": len(chunks),
        "tts_max_chunk_chars": max_chunk_len,
        "tts_tail_preserved": has_tail_sentence,
    }


if __name__ == "__main__":
    res = run_speech_ablation()
    print(json.dumps(res, indent=2))
    raise SystemExit(0 if res["overall_pass"] else 1)
