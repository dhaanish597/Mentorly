"""Pre-TTS Code-to-Speech Normalizer (`pre_tts_normalizer.py`).

Implements Plan §8.4 / Phase 2 Prompt §B.5 & Fix P2-08:
- `to_speakable(text: str) -> list[str]`
- Converts code symbols, array literals, negative numbers, subscripts, snake_case
  identifiers, and comparison operators into natural Indian English spoken phrasing
  while preserving the original display text for the UI.
- Splits long responses at sentence and clause boundaries so each chunk respects
  Gnani SSE TTS's `<= 1000` character limit (default target `<= 900` chars per
  chunk) without silent truncation or content deletion.
"""

from __future__ import annotations

import re
from typing import Final

NORMALIZER_VERSION: Final[str] = "v2.0.0-p2"
MAX_TTS_CHUNK_CHARS: Final[int] = 900

_OPERATOR_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"<="), " is less than or equal to "),
    (re.compile(r">="), " is greater than or equal to "),
    (re.compile(r"!="), " is not equal to "),
    (re.compile(r"=="), " equals "),
    (re.compile(r"\+="), " plus equals "),
    (re.compile(r"-="), " minus equals "),
    (re.compile(r"\*="), " times equals "),
    (re.compile(r"->"), " returns "),
)

_IDENTIFIER_PRONUNCIATIONS: Final[dict[str, str]] = {
    "nums": "nums",
    "curr_sum": "current sum",
    "prefix_sum": "prefix sum",
    "first_seen": "first seen",
    "max_len": "max length",
    "min_len": "min length",
    "max_prod": "max product",
    "min_prod": "min product",
    "shortest_subarray_ge_target": "shortest subarray greater than or equal to target",
    "first_at_least": "first at least",
    "max_product_subarray": "max product subarray",
    "longest_subarray_sum_k": "longest subarray sum k",
    "find_min_rotated": "find min rotated",
}


def _expand_array_literal(match: re.Match[str]) -> str:
    inner = match.group(1).strip()
    if not inner:
        return "an empty list"
    items = [item.strip() for item in inner.split(",") if item.strip()]
    spoken_items: list[str] = []
    for item in items:
        if item.startswith("-") and item[1:].isdigit():
            spoken_items.append(f"minus {item[1:]}")
        else:
            spoken_items.append(item)
    return "list " + ", ".join(spoken_items)


def _normalize_single_chunk(text: str) -> str:
    working = text.strip()
    if not working:
        return ""

    # 1. Strip backticks around inline code
    working = working.replace("`", "")

    # 2. Subscripts: nums[i] -> nums at index i, nums[0] -> nums at index 0
    working = re.sub(
        r"\b([A-Za-z_][A-Za-z0-9_]*)\[([^\[\]]+)\]",
        r"\1 at index \2",
        working,
    )

    # 3. Array literals: [1, -1, 5] -> list 1, minus 1, 5
    working = re.sub(
        r"\[\s*(-?\d+(?:\s*,\s*-?\d+)*)\s*\]",
        _expand_array_literal,
        working,
    )
    working = re.sub(r"\[\s*\]", "an empty list", working)

    # 4. Multi-character operators before single '='
    for pat, replacement in _OPERATOR_RULES:
        working = pat.sub(replacement, working)

    # 5. Standalone assignment '=' between identifier and value
    working = re.sub(
        r"(?<=[A-Za-z0-9_])\s*=\s*(?=[A-Za-z0-9_\-\[])",
        " equals ",
        working,
    )

    # 6. Negative numbers: -1 -> minus 1
    working = re.sub(r"(?<![A-Za-z0-9_])-(\d+)\b", r"minus \1", working)

    # 7. Known snake_case identifier pronunciations, then general snake_case -> space-separated
    for ident, spoken in _IDENTIFIER_PRONUNCIATIONS.items():
        working = re.sub(rf"\b{re.escape(ident)}\b", spoken, working)
    working = re.sub(
        r"\b([A-Za-z0-9]+)_([A-Za-z0-9_]+)\b",
        lambda m: m.group(0).replace("_", " "),
        working,
    )

    # Collapse whitespace
    return " ".join(working.split())


def _split_bounded_sentences(text: str, max_chars: int = MAX_TTS_CHUNK_CHARS) -> list[str]:
    """Split speakable text along sentence/clause boundaries without ever dropping content."""
    bound = max(1, min(max_chars, 1000))
    raw_sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+", text)
        if s.strip()
    ]
    if not raw_sentences:
        return []

    chunks: list[str] = []
    current = ""
    for sent in raw_sentences:
        if len(sent) > bound:
            if current:
                chunks.append(current)
                current = ""
            # Split long sentence by words (and split oversized single tokens without dropping chars)
            words = sent.split(" ")
            part = ""
            for w in words:
                if len(w) > bound:
                    if part:
                        chunks.append(part)
                        part = ""
                    for idx in range(0, len(w), bound):
                        piece = w[idx : idx + bound]
                        if len(piece) == bound:
                            chunks.append(piece)
                        else:
                            part = piece
                    continue
                candidate = f"{part} {w}".strip() if part else w
                if len(candidate) <= bound:
                    part = candidate
                else:
                    if part:
                        chunks.append(part)
                    part = w
            if part:
                chunks.append(part)
            continue

        candidate = f"{current} {sent}".strip() if current else sent
        if len(candidate) <= bound:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = sent

    if current:
        chunks.append(current)
    return chunks


def to_speakable(text: str, *, max_chunk_chars: int = MAX_TTS_CHUNK_CHARS) -> list[str]:
    """Convert coach response text with code symbols into bounded speakable chunks (`<= 1000` chars)."""
    if not text or not text.strip():
        return []
    normalized = _normalize_single_chunk(text)
    if not normalized:
        return []
    return _split_bounded_sentences(normalized, max_chars=min(max_chunk_chars, 1000))
