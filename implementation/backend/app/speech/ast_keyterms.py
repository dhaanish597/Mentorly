"""AST-First Speech Bias Keyterm Extractor (`ast_keyterms.py`).

Implements Plan §8.2 / Phase 2 Prompt §B.3 & Fix P2-02:
- `extract_bias_keyterms(code: str, exercise_id: str | ExerciseId) -> list[str]`
- Uses canonical `ExerciseId` members (`EX1_SHORTEST_SUBARRAY`, `EX2_BINARY_SEARCH`, `EX3_MAX_PRODUCT`)
  and canonical function/domain terms (`shortest_subarray_ge_target`, `first_at_least`,
  `max_product_subarray`).
- Parses valid Python AST (`ast.parse`) and prioritizes:
  1. Function names (`ast.FunctionDef`, `ast.AsyncFunctionDef`)
  2. Function parameters (`ast.arg`)
  3. Assigned/referenced local variable identifiers (`ast.Name`)
  4. Curated exercise domain terms (e.g., `prefix_sum`, `target`, `mid`, `min_prod`, `max_prod`)
- Falls back to a deterministic regex/token scanner when learner code has a `SyntaxError`
  without claiming semantic validity.
- Completes well within `<= 50 ms` for 200-line inputs and returns at most `30` deduplicated
  bias terms (respecting Gnani's `<= 200` keyterm limit with ample safety headroom).
"""

from __future__ import annotations

import ast
import keyword
import re
from typing import Final

from backend.app.models.enums import ExerciseId

MAX_BIAS_KEYTERMS: Final[int] = 30
MAX_TOPIC_CHARS: Final[int] = 1600

_PYTHON_BUILTINS_TO_SKIP: Final[frozenset[str]] = frozenset(
    {
        "abs",
        "all",
        "any",
        "bool",
        "dict",
        "enumerate",
        "Exception",
        "float",
        "int",
        "len",
        "list",
        "max",
        "min",
        "None",
        "print",
        "range",
        "set",
        "sorted",
        "str",
        "sum",
        "True",
        "False",
        "tuple",
        "ValueError",
        "zip",
    }
)

_EXERCISE_DOMAIN_TERMS: Final[dict[str, tuple[str, ...]]] = {
    ExerciseId.EX1_SHORTEST_SUBARRAY.value: (
        "shortest_subarray_ge_target",
        "nums",
        "target",
        "prefix_sum",
        "first_seen",
        "curr_sum",
        "min_len",
        "max_len",
        "subarray",
        "negative",
        "sliding_window",
    ),
    ExerciseId.EX2_BINARY_SEARCH.value: (
        "first_at_least",
        "nums",
        "target",
        "left",
        "right",
        "mid",
        "lo",
        "hi",
        "binary_search",
        "duplicate",
        "boundary",
    ),
    ExerciseId.EX3_MAX_PRODUCT.value: (
        "max_product_subarray",
        "nums",
        "max_prod",
        "min_prod",
        "best",
        "curr",
        "negative",
        "zero",
        "subarray",
    ),
}

_EXERCISE_TOPICS: Final[dict[str, str]] = {
    ExerciseId.EX1_SHORTEST_SUBARRAY.value: (
        "Computer science viva on finding the shortest contiguous subarray with sum at least target "
        "in an integer array (with positive-only and negative-allowed specs) using sliding windows "
        "and prefix sums."
    ),
    ExerciseId.EX2_BINARY_SEARCH.value: (
        "Computer science viva on finding the first index whose value is at least target in a "
        "sorted integer array with duplicates using binary search boundary invariants."
    ),
    ExerciseId.EX3_MAX_PRODUCT.value: (
        "Computer science viva on finding the maximum product of a contiguous non-empty subarray "
        "by tracking both running maximum and running minimum products across negative numbers and zeros."
    ),
}

_IDENT_RE: Final[re.Pattern[str]] = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{0,63}\b")


def _add_term(
    term: str,
    out: list[str],
    seen: set[str],
    max_terms: int,
) -> None:
    cleaned = term.strip()
    if (
        not cleaned
        or len(cleaned) > 64
        or cleaned in seen
        or keyword.iskeyword(cleaned)
        or cleaned in _PYTHON_BUILTINS_TO_SKIP
        or cleaned.startswith("__")
    ):
        return
    if len(out) < max_terms:
        seen.add(cleaned)
        out.append(cleaned)


def extract_bias_keyterms(
    code: str,
    exercise_id: str | ExerciseId,
    *,
    max_terms: int = MAX_BIAS_KEYTERMS,
) -> list[str]:
    """Extract up to `max_terms` (default 30) prioritized identifier and domain keyterms."""
    cap = max(1, min(max_terms, MAX_BIAS_KEYTERMS))
    ex_key = exercise_id.value if isinstance(exercise_id, ExerciseId) else str(exercise_id)
    out: list[str] = []
    seen: set[str] = set()

    clipped_code = (code or "")[:16_384]
    if clipped_code.strip():
        try:
            tree = ast.parse(clipped_code)
            func_names: list[str] = []
            arg_names: list[str] = []
            var_names: list[str] = []

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func_names.append(node.name)
                    for arg in (
                        node.args.posonlyargs
                        + node.args.args
                        + node.args.kwonlyargs
                    ):
                        arg_names.append(arg.arg)
                    if node.args.vararg:
                        arg_names.append(node.args.vararg.arg)
                    if node.args.kwarg:
                        arg_names.append(node.args.kwarg.arg)
                elif isinstance(node, ast.Name):
                    var_names.append(node.id)

            for name in func_names:
                _add_term(name, out, seen, cap)
            for name in arg_names:
                _add_term(name, out, seen, cap)
            for name in var_names:
                _add_term(name, out, seen, cap)
        except SyntaxError:
            # Deterministic lexical fallback when learner code has a SyntaxError
            for match in _IDENT_RE.finditer(clipped_code):
                _add_term(match.group(0), out, seen, cap)
                if len(out) >= cap:
                    break

    for domain_term in _EXERCISE_DOMAIN_TERMS.get(ex_key, ()):
        _add_term(domain_term, out, seen, cap)

    return out[:cap]


def build_stt_topic_string(
    exercise_id: str | ExerciseId,
    keyterms: list[str] | None = None,
    topic_override: str | None = None,
) -> str:
    """Build a bounded (`<= 1600` chars) Gnani STT `topic` context string."""
    if topic_override and topic_override.strip():
        return topic_override.strip()[:MAX_TOPIC_CHARS]

    ex_key = exercise_id.value if isinstance(exercise_id, ExerciseId) else str(exercise_id)
    base_topic = _EXERCISE_TOPICS.get(
        ex_key,
        "Computer science viva debugging discussion on Python array algorithms.",
    )
    if not keyterms:
        return base_topic[:MAX_TOPIC_CHARS]

    terms_preview = ", ".join(keyterms[:MAX_BIAS_KEYTERMS])
    combined = f"{base_topic} Identifiers in scope: {terms_preview}."
    return combined[:MAX_TOPIC_CHARS]
