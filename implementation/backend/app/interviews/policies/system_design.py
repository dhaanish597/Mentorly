"""System-design oral assessment policy: assumptions, capacity and failure probes."""
from backend.app.interviews.rubrics import next_probe

TOPICS = {
    'capacity': 'Design a URL-shortening service. State workload assumptions and estimate storage and request capacity.',
    'reliability': 'Design a notification delivery service. Describe failure boundaries and retry behavior.',
    'consistency': 'Design an inventory reservation service. Explain the consistency requirement for concurrent purchases.',
}


def questions(topics: list[str], difficulty: str) -> list[dict]:
    suffix = 'Consider cross-region failure and a cost constraint.' if difficulty == 'advanced' else 'Identify the major components and their responsibilities.'
    return [{'text': TOPICS[t] + ' ' + suffix, 'topic': t,
             'indicator_ids': ['reasoning_marker', 'example_marker', 'failure_marker', 'tradeoff_marker'],
             'source_refs': [{'source': 'authored_interview_policy', 'policy_id': f'system_design:{t}:v1'}]} for t in topics]


def followup(question: dict, answer: str) -> dict:
    return next_probe(question, answer, {
        'reasoning_marker': 'Which workload assumption justifies the component choice you described?',
        'example_marker': 'Give a numerical workload estimate and show the capacity calculation you would use.',
        'failure_marker': 'What happens if one of those components fails during a request?',
        'tradeoff_marker': 'Which latency, consistency or cost tradeoff would you measure before committing?',
    }, 'Walk through a regional outage in your proposed design, including recovery order.')
