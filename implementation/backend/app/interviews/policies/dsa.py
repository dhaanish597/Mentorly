"""DSA prompts derived only from public trusted exercise metadata."""
from backend.app.interviews.rubrics import next_probe

INDICATORS = ['reasoning_marker', 'example_marker', 'complexity_marker', 'boundary_marker']


def questions(exercises: list[dict], difficulty: str) -> list[dict]:
    depth = 'Compare an alternative approach and justify the constraints it needs.' if difficulty == 'advanced' else 'Explain your approach and why it fits the stated contract.'
    return [{'text': f"{row['title']}\n{row['description']}\nSpecification: {row['spec_version']}.\n{depth}",
             'topic': row['topics'][0] if row['topics'] else 'algorithms', 'indicator_ids': INDICATORS,
             'source_refs': [{'source': 'exercise_catalog', 'exercise_id': row['exercise_id'], 'spec_version': row['spec_version']}]} for row in exercises]


def followup(question: dict, answer: str) -> dict:
    return next_probe(question, answer, {
        'reasoning_marker': 'What reasoning or invariant supports the approach you described?',
        'example_marker': 'Walk through one concrete input using your approach and explain each state change.',
        'complexity_marker': 'What time and space complexity do you expect, and what operation determines each?',
        'boundary_marker': 'Which boundary input would you test first, and why?',
    }, 'How would your approach change under a different input-size bound? Explain the tradeoff.')
