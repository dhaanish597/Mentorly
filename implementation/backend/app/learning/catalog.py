"""Validated versioned curriculum and answer-key-free public projection."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .content_aptitude import APTITUDE
from .content_cs import CS
from .content_design import DESIGN
from .content_dsa import DSA

VERSION = "1.1.0"
_CATALOG = {"version": VERSION, "tracks": [DSA, CS, APTITUDE, DESIGN]}
PUBLIC_FIELDS = (
    "id",
    "title",
    "prerequisites",
    "difficulty",
    "estimated_minutes",
    "objectives",
    "explanation",
    "example",
    "hints",
    "practice_url",
)


def curriculum() -> dict[str, Any]:
    return deepcopy(_CATALOG)


def public_question(question: dict[str, Any]) -> dict[str, Any]:
    value = {key: deepcopy(question[key]) for key in ("id", "prompt")}
    value["response_kind"] = question.get("response_kind", "multiple_choice")
    if value["response_kind"] == "multiple_choice":
        value["options"] = deepcopy(question["options"])
        value["option_ids"] = [
            option_id(question, option) for option in question["options"]
        ]
    return value


def option_id(question: dict[str, Any], option: str) -> str:
    return (
        "option_"
        + hashlib.sha256((question["id"] + "\0" + option).encode()).hexdigest()[:20]
    )


def public_catalog(value: dict[str, Any] | None = None) -> dict[str, Any]:
    catalog = value if value is not None else _CATALOG
    return {
        "version": catalog["version"],
        "tracks": [
            {
                **{k: track[k] for k in ("id", "module", "title", "description")},
                "lessons": [
                    {
                        **{k: deepcopy(lesson[k]) for k in PUBLIC_FIELDS},
                        "question": public_question(lesson["question"]),
                    }
                    for lesson in track["lessons"]
                ],
            }
            for track in catalog["tracks"]
        ],
    }


def lesson_by_id(identifier: str) -> dict[str, Any] | None:
    return next(
        (
            deepcopy(lesson)
            for track in _CATALOG["tracks"]
            for lesson in track["lessons"]
            if lesson["id"] == identifier
        ),
        None,
    )


def encode(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def exercise_lesson_mapping() -> dict[tuple[str, str], str]:
    mapping = {}
    for track in _CATALOG["tracks"]:
        for lesson in track["lessons"]:
            target = urlsplit(lesson["practice_url"])
            if target.path.startswith("/practice/"):
                mapping[
                    (
                        target.path.removeprefix("/practice/"),
                        parse_qs(target.query)["spec"][0],
                    )
                ] = lesson["id"]
    return mapping


def content_hash(lesson: dict[str, Any]) -> str:
    return hashlib.sha256(encode(lesson).encode()).hexdigest()


def evaluate_answer(
    question: dict[str, Any], answer: str, selected_option_id: str | None = None
) -> dict[str, Any]:
    # Exact normalized equality only: a paragraph containing an answer is not evidence.
    kind = question.get("response_kind", "multiple_choice")
    if kind == "multiple_choice":
        selected = (
            next(
                (
                    option
                    for option in question["options"]
                    if option_id(question, option) == selected_option_id
                ),
                None,
            )
            if selected_option_id
            else answer.strip()
        )
        # Explicit IDs cannot be combined with a different label, even if one is correct.
        valid_pair = (
            not selected_option_id
            or selected is not None
            and (not answer.strip() or answer.strip().casefold() == selected.casefold())
        )
        correct = (
            valid_pair
            and selected is not None
            and selected.casefold() == question["correct_answer"].strip().casefold()
        )
    else:
        correct = evaluate_declared_short_answer(question, answer)
    return {
        "correct": correct,
        "message": (
            question["rationale"]
            if correct
            else "Not yet correct. Revisit the stated assumptions and work through the example."
        ),
        "answer_key_revealed": correct,
    }


def evaluate_declared_short_answer(question: dict[str, Any], answer: str) -> bool:
    """Only opt-in literal numeric/boolean/enumeration representations; no algebra."""
    contract = question.get("accepted_representations", {})
    if contract.get("version") != "1.0":
        return False
    kind = question.get("response_kind")
    value = answer.strip()
    if len(value) > 200:
        return False
    if kind in {"boolean", "enumeration"}:
        aliases = contract.get("aliases", [])
        return (
            isinstance(aliases, list)
            and all(isinstance(item, str) for item in aliases)
            and value.casefold() in {item.strip().casefold() for item in aliases}
        )
    if kind == "numeric":

        def number(raw: str):
            if (
                re.fullmatch(r"[+-]?\d{1,30}\s*/\s*[+-]?\d{1,30}", raw)
                and contract.get("allow_fraction") is True
            ):
                return Fraction(raw.replace(" ", ""))
            if not re.fullmatch(r"[+-]?(?:\d{1,30}(?:\.\d{1,30})?|\.\d{1,30})", raw):
                raise ValueError("Only finite literal numbers accepted")
            return Fraction(Decimal(raw))

        try:
            return number(value) == number(str(question["correct_answer"]))
        except (InvalidOperation, ValueError, ZeroDivisionError):
            return False
    return False


def _text(value: Any, minimum: int = 1, maximum: int = 8000) -> None:
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise ValueError("Invalid or missing substantive content")


def _targets() -> tuple[dict[str, set[str]], dict[str, Any]]:
    from backend.app.exercises.registry import catalog_packages
    from backend.app.studio.catalog import SCENARIOS

    exercises = {
        p["exercise_id"]: {s["spec_version"] for s in p["spec_versions"]}
        for p in catalog_packages()
        if p["catalog_status"] == "READY"
    }
    return exercises, SCENARIOS


def _validate_target(url: str, ids: set[str], exercises: dict, studios: dict) -> None:
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    valid = not (parsed.scheme or parsed.netloc or parsed.fragment)
    if parsed.path.startswith("/learn/"):
        valid = valid and parsed.path.removeprefix("/learn/") in ids and not query
    elif parsed.path.startswith("/practice/"):
        specs = exercises.get(parsed.path.removeprefix("/practice/"), set())
        valid = (
            valid
            and set(query) == {"spec"}
            and len(query["spec"]) == 1
            and query["spec"][0] in specs
        )
    elif parsed.path == "/studio":
        valid = (
            valid
            and set(query) == {"scenario"}
            and len(query["scenario"]) == 1
            and query["scenario"][0] in studios
        )
    else:
        valid = False
    if not valid:
        raise ValueError("Invalid catalog practice target")


def _validate_lesson(
    lesson: dict, ids: set[str], exercises: dict, studios: dict
) -> None:
    for field in ("id", "title", "practice_url"):
        _text(lesson[field], maximum=300)
    _text(lesson["explanation"], minimum=150)
    _text(lesson["example"], minimum=70)
    if lesson["difficulty"] not in {"beginner", "intermediate", "advanced"}:
        raise ValueError("Invalid lesson difficulty")
    if (
        type(lesson["estimated_minutes"]) is not int
        or not 5 <= lesson["estimated_minutes"] <= 120
    ):
        raise ValueError("Invalid lesson duration")
    if (
        not isinstance(lesson["objectives"], list)
        or not 2 <= len(lesson["objectives"]) <= 8
    ):
        raise ValueError("Missing learning objectives content")
    for objective in lesson["objectives"]:
        _text(objective)
    if (
        not isinstance(lesson["hints"], list)
        or len(lesson["hints"]) != 3
        or len(set(lesson["hints"])) != 3
    ):
        raise ValueError("Missing graduated hints content")
    for hint in lesson["hints"]:
        _text(hint)
    prerequisites = lesson["prerequisites"]
    if (
        not isinstance(prerequisites, list)
        or len(set(prerequisites)) != len(prerequisites)
        or any(p not in ids for p in prerequisites)
    ):
        raise ValueError("Dangling or duplicate prerequisite")
    question = lesson["question"]
    _text(question["id"], maximum=128)
    _text(question["prompt"])
    kind = question.get("response_kind", "multiple_choice")
    if kind == "multiple_choice":
        options = question["options"]
        if not isinstance(options, list) or not 2 <= len(options) <= 6:
            raise ValueError("Invalid objective question options")
        for option in options:
            _text(option, maximum=500)
        if (
            len({o.strip().casefold() for o in options}) != len(options)
            or question["correct_answer"] not in options
        ):
            raise ValueError("Invalid objective answer key")
    elif kind in {"numeric", "boolean", "enumeration"}:
        _text(question["correct_answer"], maximum=200)
        contract = question.get("accepted_representations")
        if (
            not isinstance(contract, dict)
            or contract.get("version") != "1.0"
            or set(contract) - {"version", "aliases", "allow_fraction"}
        ):
            raise ValueError("Invalid declared short-answer contract")
        if kind in {"boolean", "enumeration"}:
            aliases = contract.get("aliases")
            if not isinstance(aliases, list) or not 1 <= len(aliases) <= 20:
                raise ValueError("Invalid declared short-answer aliases")
            for alias in aliases:
                _text(alias, maximum=200)
            if len({item.strip().casefold() for item in aliases}) != len(aliases):
                raise ValueError("Duplicate declared short-answer aliases")
        elif (
            "allow_fraction" in contract
            and type(contract["allow_fraction"]) is not bool
        ):
            raise ValueError("Invalid declared numeric representation")
        if not evaluate_declared_short_answer(question, question["correct_answer"]):
            raise ValueError("Invalid declared short-answer key")
    else:
        raise ValueError("Unsupported objective response kind")
    _text(question["rationale"], minimum=40)
    if lesson["explanation_rubric"]["status"] != "unassessed":
        raise ValueError("Explanation rubric must be unassessed")
    _validate_target(lesson["practice_url"], ids, exercises, studios)


def _validate_acyclic(lessons: list[dict]) -> None:
    edges = {lesson["id"]: lesson["prerequisites"] for lesson in lessons}
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(identifier: str) -> None:
        if identifier in visiting:
            raise ValueError("Prerequisite cycle")
        if identifier in visited:
            return
        visiting.add(identifier)
        for parent in edges[identifier]:
            visit(parent)
        visiting.remove(identifier)
        visited.add(identifier)

    for identifier in edges:
        visit(identifier)


def validate_catalog(
    value: dict,
    *,
    exercise_targets: dict | None = None,
    studio_targets: dict | None = None,
) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+", value.get("version", "")):
        raise ValueError("Invalid catalog version")
    tracks = value.get("tracks", [])
    if not tracks or len({t["id"] for t in tracks}) != len(tracks):
        raise ValueError("Missing or duplicate tracks")
    lessons = [lesson for track in tracks for lesson in track["lessons"]]
    ids = {lesson["id"] for lesson in lessons}
    if not lessons or len(ids) != len(lessons):
        raise ValueError("Duplicate or missing lesson identifiers")
    question_ids = [lesson["question"]["id"] for lesson in lessons]
    if len(set(question_ids)) != len(question_ids):
        raise ValueError("Duplicate objective question identifiers")
    defaults = (
        _targets() if exercise_targets is None or studio_targets is None else ({}, {})
    )
    exercises = defaults[0] if exercise_targets is None else exercise_targets
    studios = defaults[1] if studio_targets is None else studio_targets
    for track in tracks:
        if (
            track["module"] not in {"dsa", "cs", "aptitude", "system_design"}
            or not track["lessons"]
        ):
            raise ValueError("Invalid curriculum module")
        for field in ("id", "title", "description"):
            _text(track[field])
    for lesson in lessons:
        _validate_lesson(lesson, ids, exercises, studios)
    _validate_acyclic(lessons)


validate_catalog(_CATALOG)
