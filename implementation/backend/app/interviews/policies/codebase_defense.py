"""Codebase defense without repository ingestion: citations are claimed, not verified."""
from backend.app.interviews.rubrics import next_probe

TOPICS = {
    'ownership': 'Choose a codebase you can discuss without secrets. Describe one module, its ownership boundary and a file/line reference.',
    'data-flow': 'Trace one request through your codebase from entry point to persistence. Cite a file and line for each boundary.',
    'change-safety': 'Defend a change you would make in your codebase. Identify affected callers and the tests that would protect them.',
}


def questions(topics: list[str], difficulty: str) -> list[dict]:
    suffix = 'Discuss an alternative decomposition and migration risk.' if difficulty == 'advanced' else 'Explain only what you can support from your own code.'
    return [{'text': TOPICS[t] + ' ' + suffix, 'topic': t,
             'indicator_ids': ['reasoning_marker', 'source_marker', 'example_marker', 'failure_marker'],
             'source_refs': [{'source': 'authored_interview_policy', 'policy_id': f'codebase_defense:{t}:v1'}]} for t in topics]


def followup(question: dict, answer: str) -> dict:
    return next_probe(question, answer, {
        'reasoning_marker': 'Why does the codebase boundary you described belong in that module?',
        'source_marker': 'Which exact file and line supports your codebase claim? Do not include secrets.',
        'example_marker': 'Trace one concrete call and input through the code paths you described.',
        'failure_marker': 'Which failure path or regression test would challenge your codebase explanation?',
    }, 'How would you verify this codebase claim against an owned repository snapshot?')
