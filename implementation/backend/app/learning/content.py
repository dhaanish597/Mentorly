"""Original lesson-building vocabulary; no generated filler or implied mastery."""

from typing import Any

EXPLANATION_RUBRIC = {
    "status": "unassessed",
    "criteria": [
        "State the relevant invariant or assumption.",
        "Trace the worked example and justify each transition.",
        "Identify a boundary case and explain the trade-off.",
    ],
    "reason": "Only the objective answer is checked. Explanation quality and topic mastery are not assessed.",
}


def lesson(
    identifier: str,
    title: str,
    prerequisites: tuple[str, ...],
    objectives: tuple[str, ...],
    explanation: str,
    example: str,
    hints: tuple[str, str, str],
    prompt: str,
    options: tuple[str, ...],
    correct: str,
    rationale: str,
    *,
    difficulty: str = "beginner",
    minutes: int = 15,
    target: str | None = None,
) -> dict[str, Any]:
    return {
        "id": identifier,
        "title": title,
        "prerequisites": list(prerequisites),
        "difficulty": difficulty,
        "estimated_minutes": minutes,
        "objectives": list(objectives),
        "explanation": explanation,
        "example": example,
        "hints": list(hints),
        "practice_url": target or f"/learn/{identifier}",
        "question": {
            "id": identifier + "-q1",
            "prompt": prompt,
            "options": list(options),
            "correct_answer": correct,
            "rationale": rationale,
        },
        "explanation_rubric": {
            **EXPLANATION_RUBRIC,
            "criteria": list(EXPLANATION_RUBRIC["criteria"]),
        },
    }


def track(
    identifier: str,
    module: str,
    title: str,
    description: str,
    lessons: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    return {
        "id": identifier,
        "module": module,
        "title": title,
        "description": description,
        "lessons": list(lessons),
    }
