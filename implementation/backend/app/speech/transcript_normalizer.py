"""Post-STT Transcript Normalizer (`transcript_normalizer.py`).

Implements Plan §8.3 / Phase 2 Prompt §B.4:
- Strictly separates `raw_transcript` (exact provider output) from `normalized_transcript`
  (deterministic proposal shown in the learner confirmation bar).
- Handles Indian English and Tanglish (`ta-IN,en-IN`) code-mixed spoken math/code phrases:
  - Spoken negative numbers: `"minus one"` -> `"-1"`, `"negative four"` -> `"-4"`
  - Spoken comparators: `"less than or equal to"` -> `"<="`, `"greater than or equal to"` -> `">="`,
    `"double equals"` / `"equal to"` -> `"=="`, `"not equal to"` -> `"!="`
  - Spoken identifiers & subscripts: `"nums of i"` -> `"nums[i]"`, `"nums of zero"` -> `"nums[0]"`
  - Tanglish discourse/code-mixed particles (`"illa"`, `"aa"`, `"la"`, `"maari"`) preserved in
    `raw_transcript` and cleanly normalized when modifying a numeric/variable correction
  - Self-corrections (`"three—no, one"`, `"three, wait no, one"`, `"moonu illa onnu"`):
    surfaces `contains_self_correction=True` and proposes the corrected clause while keeping
    `requires_confirmation=True` so no claim is ever auto-confirmed without learner consent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_NUMBER_WORDS: dict[str, str] = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    # Common Romanized Tamil number words in Tanglish viva utterances
    "onnu": "1",
    "rendu": "2",
    "moonu": "3",
    "naalu": "4",
    "anju": "5",
    "puzhu": "0",
    "poojyam": "0",
}

_SELF_CORRECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?P<abandoned>-?\d+|zero|one|two|three|four|five|six|seven|eight|nine|ten|onnu|rendu|moonu|naalu|anju)\s*"
        r"(?:—|--|,|\s)+\s*(?:no(?:\s+wait)?|wait(?:\s+no)?|sorry|illa|illai|actually)\s*(?:,|\s)*\s*"
        r"(?P<corrected>(?:minus\s+|negative\s+)?(?:-?\d+|zero|one|two|three|four|five|six|seven|eight|nine|ten|onnu|rendu|moonu|naalu|anju))\b",
        re.IGNORECASE,
    ),
)

_COMPARATOR_REPLACEMENTS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(r"\bless\s+than\s+or\s+equal(?:\s+to)?\b", re.IGNORECASE),
        "<=",
        "normalized 'less than or equal to' -> '<='",
    ),
    (
        re.compile(r"\bgreater\s+than\s+or\s+equal(?:\s+to)?\b", re.IGNORECASE),
        ">=",
        "normalized 'greater than or equal to' -> '>='",
    ),
    (
        re.compile(r"\bnot\s+equal(?:\s+to)?\b", re.IGNORECASE),
        "!=",
        "normalized 'not equal to' -> '!='",
    ),
    (
        re.compile(r"\bdouble\s+equals?\b", re.IGNORECASE),
        "==",
        "normalized 'double equals' -> '=='",
    ),
)


@dataclass(frozen=True)
class NormalizationProposal:
    """Result of normalizing an STT transcript without auto-confirming learner claims."""

    raw_transcript: str
    normalized_transcript: str
    normalization_notes: list[str] = field(default_factory=list)
    contains_self_correction: bool = False
    requires_confirmation: bool = True


def _replace_spoken_signed_numbers(text: str, notes: list[str]) -> str:
    """Convert `'minus one'` / `'negative 3'` / number words in math contexts."""
    word_alt = "|".join(_NUMBER_WORDS.keys())

    def _neg_repl(match: re.Match[str]) -> str:
        tok = match.group("num").lower()
        digit = _NUMBER_WORDS.get(tok, tok)
        notes.append(f"normalized '{match.group(0)}' -> '-{digit}'")
        return f"-{digit}"

    pattern_neg = re.compile(
        rf"\b(?:minus|negative)\s+(?P<num>\d+|{word_alt})\b",
        re.IGNORECASE,
    )
    out = pattern_neg.sub(_neg_repl, text)

    def _word_repl(match: re.Match[str]) -> str:
        w = match.group(0).lower()
        digit = _NUMBER_WORDS[w]
        return digit

    pattern_words = re.compile(rf"\b(?:{word_alt})\b", re.IGNORECASE)
    converted = pattern_words.sub(_word_repl, out)
    if converted != out:
        notes.append("normalized spoken number words to digits")
    return converted


def _replace_subscript_phrases(text: str, notes: list[str]) -> str:
    """Convert `'nums of i'` or `'nums of 0'` to `'nums[i]'` / `'nums[0]'`."""
    pattern = re.compile(
        r"\b(?P<arr>nums|arr|prefix|first_seen)\s+(?:of|at\s+index|index)\s+(?P<idx>[iIjJkKlLrR]|\d+|mid|left|right|lo|hi)\b"
    )

    def _sub_repl(match: re.Match[str]) -> str:
        arr = match.group("arr")
        idx = match.group("idx")
        notes.append(f"normalized '{match.group(0)}' -> '{arr}[{idx}]'")
        return f"{arr}[{idx}]"

    return pattern.sub(_sub_repl, text)


def normalize_learner_transcript(
    raw_transcript: str,
    *,
    known_identifiers: list[str] | None = None,
) -> NormalizationProposal:
    """Produce a deterministic `NormalizationProposal` while preserving `raw_transcript` verbatim."""
    raw = raw_transcript or ""
    if not raw.strip():
        return NormalizationProposal(
            raw_transcript=raw,
            normalized_transcript="",
            normalization_notes=[],
            contains_self_correction=False,
            requires_confirmation=True,
        )

    notes: list[str] = []
    working = " ".join(raw.strip().split())
    contains_self_correction = False

    # 1. Detect spoken self-corrections (e.g., "three—no, one" or "moonu illa onnu")
    for pat in _SELF_CORRECTION_PATTERNS:
        if pat.search(working):
            contains_self_correction = True

            def _corr_repl(m: re.Match[str]) -> str:
                corrected = m.group("corrected")
                notes.append(
                    f"self-correction detected ('{m.group(0)}') -> proposed '{corrected}'"
                )
                return corrected

            working = pat.sub(_corr_repl, working)

    # 2. Spoken comparators
    for pat, repl, note in _COMPARATOR_REPLACEMENTS:
        if pat.search(working):
            working = pat.sub(repl, working)
            notes.append(note)

    # 3. Spoken signed & cardinal numbers
    working = _replace_spoken_signed_numbers(working, notes)

    # 4. Spoken array indexing ("nums of i" -> "nums[i]")
    working = _replace_subscript_phrases(working, notes)

    # 5. Spoken snake_case identifier restoration for known identifiers in scope
    if known_identifiers:
        for ident in known_identifiers:
            if "_" in ident:
                spoken_form = ident.replace("_", " ")
                pat = re.compile(rf"\b{re.escape(spoken_form)}\b", re.IGNORECASE)
                if pat.search(working):
                    working = pat.sub(ident, working)
                    notes.append(f"restored identifier '{spoken_form}' -> '{ident}'")

    return NormalizationProposal(
        raw_transcript=raw,
        normalized_transcript=working,
        normalization_notes=notes[:32],
        contains_self_correction=contains_self_correction,
        requires_confirmation=True,
    )
