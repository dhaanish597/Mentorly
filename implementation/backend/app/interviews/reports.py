"""End-only evidence report; observations are not technical validity or mastery."""

import json
from sqlite3 import Connection, Row

from .rubrics import observe

LIMITATIONS = [
    "Objective indicators are bounded lexical observations, not scores or correctness judgments.",
    "Semantic validity of explanations, reasoning, examples and complexity claims is unassessed.",
    "Technical code correctness is unassessed: submitted code is not executed and no server-owned execution evidence is integrated.",
    "File/line mentions are not verified repository citations. Repository contents are not loaded.",
    "No camera, speech affect, personality, confidence or psychological inference is used.",
    "Language mode selects a voice preference; English lexical cues are incomplete for multilingual answers.",
    "Recommendations identify available exercises. Lesson IDs require a coordinator-validated catalog mapping; no learning credit is granted here.",
]


def build_report(conn: Connection, session: Row, reason: str, timestamp: str) -> dict:
    rows = conn.execute(
        """SELECT a.*,q.question_json FROM interview_answers a
        JOIN interview_questions q ON q.id=a.question_id AND q.session_id=a.session_id
        WHERE a.session_id=? ORDER BY a.epoch""",
        (session["id"],),
    ).fetchall()
    answers = []
    for row in rows:
        question = json.loads(row["question_json"])
        answers.append(
            {
                "question_id": row["question_id"],
                "question": question["text"],
                "answer": row["answer"],
                "code": row["code"],
                "indicators": observe(row["answer"], question["indicator_ids"]),
            }
        )
    return {
        "session_id": session["id"],
        "completion_reason": reason,
        "completed_at": timestamp,
        "answered_count": len(answers),
        "answers": answers,
        "semantic_validity": {
            "status": "unassessed",
            "reason": "Lexical presence does not establish a valid explanation.",
        },
        "technical_correctness": {
            "status": "unassessed_no_execution_evidence",
            "reason": "No server-owned execution evidence; code was not run.",
        },
        "psychology": {
            "status": "not_assessed",
            "reason": "No psychological or camera-based inference.",
        },
        "recommendations": recommendations(session, answers),
        "practice_topics": practice_topics(session, answers),
        "limitations": LIMITATIONS,
    }


def practice_topics(session: Row, answers: list[dict]) -> list[dict]:
    plan = json.loads(session["plan_json"])
    missing = sorted(
        {i["id"] for a in answers for i in a["indicators"] if not i["value"]}
    )
    focus = {
        "dsa": "Work through concrete inputs and explain invariants, bounds and complexity.",
        "cs": "Trace the underlying mechanism with a concrete execution sequence and resource tradeoff.",
        "system_design": "Make workload assumptions numerical and explore failure, recovery and cost tradeoffs.",
        "codebase_defense": "Trace concrete callers, cite source boundaries and identify regression tests; citations need independent verification.",
    }[session["type"]]
    topics = list(dict.fromkeys(q["topic"] for q in plan))
    return [
        {
            "type": session["type"],
            "topic": t,
            "reason": focus + " These are practice suggestions, not mastery judgments.",
            "missing_indicators": missing,
        }
        for t in topics[:3]
    ]


def recommendations(session: Row, answers: list[dict]) -> list[dict]:
    # Reuse the pinned plan, not a later mutable catalog or client-supplied IDs.
    plan = json.loads(session["plan_json"])
    missing = sorted(
        {i["id"] for a in answers for i in a["indicators"] if not i["value"]}
    )
    refs = [
        r for q in plan for r in q["source_refs"] if r["source"] == "exercise_catalog"
    ]
    unique = {r["exercise_id"]: r for r in refs}
    return [
        {
            "exercise_id": r["exercise_id"],
            "spec_version": r["spec_version"],
            "lesson_id": None,
            "missing_indicators": missing,
            "reason": "Revisit this exercise and explicitly explain reasoning, examples and boundaries. This is practice guidance, not a correctness verdict.",
        }
        for r in list(unique.values())[:3]
    ]
