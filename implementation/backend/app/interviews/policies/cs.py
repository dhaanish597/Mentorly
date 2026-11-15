"""CS oral assessment policy; no reference answer leaks during the session."""

from backend.app.interviews.rubrics import next_probe

TOPICS = {
    "operating-systems": "Explain how a process differs from a thread in resource ownership and scheduling.",
    "databases": "Describe how a transaction handles two concurrent updates to the same record.",
    "networking": "Explain the path from a DNS lookup to receiving an HTTP response.",
}


def questions(topics: list[str], difficulty: str) -> list[dict]:
    suffix = (
        "Include a mechanism-level tradeoff."
        if difficulty == "advanced"
        else "State your assumptions."
    )
    return [
        {
            "text": TOPICS[t] + " " + suffix,
            "topic": t,
            "indicator_ids": ["reasoning_marker", "example_marker", "tradeoff_marker"],
            "source_refs": [
                {"source": "authored_interview_policy", "policy_id": f"cs:{t}:v1"}
            ],
        }
        for t in topics
    ]


def followup(question: dict, answer: str) -> dict:
    return next_probe(
        question,
        answer,
        {
            "reasoning_marker": "Which underlying CS mechanism explains your claim?",
            "example_marker": "Describe a concrete execution sequence illustrating your explanation.",
            "tradeoff_marker": "What competing resource or guarantee makes this CS choice a tradeoff?",
        },
        "Give a counter-scenario where the CS assumption you made would not hold.",
    )
