"""Bounded lexical observations, never semantic grading or psychological inference."""
import re

PATTERNS = {
    'reasoning_marker': ('Reasoning marker mentioned', r'\b(?:because|therefore|since|so that|invariant)\b|ஏனெனில்|அதனால்|yenna|athanaal'),
    'example_marker': ('Example marker mentioned', r'\b(?:example|e\.g\.|for instance|test case)\b|\[[^\]\n]{1,120}\]|உதாரண|example'),
    'complexity_marker': ('Complexity notation or term mentioned', r'O\s*\([^\)\n]{1,40}\)|\b(?:time complexity|space complexity|linear|logarithmic)\b'),
    'boundary_marker': ('Boundary condition term mentioned', r'\b(?:empty|zero|duplicate|negative|boundary|edge case|null)\b'),
    'tradeoff_marker': ('Tradeoff term mentioned', r'\b(?:tradeoff|trade-off|versus|latency|throughput|cost)\b'),
    'failure_marker': ('Failure or recovery term mentioned', r'\b(?:failure|recovery|retry|timeout|crash|rollback)\b'),
    'source_marker': ('File and line reference mentioned, not verified', r'[\w./-]+\.(?:py|ts|tsx|js|go|java|rs|c|cpp):\d{1,7}'),
}


def observe(answer: str, indicator_ids: list[str]) -> list[dict]:
    result = []
    for ident in indicator_ids:
        label, pattern = PATTERNS[ident]
        matches = list(re.finditer(pattern, answer, re.IGNORECASE))[:3]
        result.append({'id': ident, 'label': label, 'value': int(bool(matches)), 'maximum': 1,
                       'status': 'observed_text_only' if matches else 'not_observed_text_only',
                       'semantic_validity': 'unassessed',
                       'excerpts': [{'start': m.start(), 'end': m.end(), 'text': answer[m.start():m.end()]} for m in matches]})
    return result


def next_probe(question: dict, answer: str, prompts: dict[str, str], fallback: str) -> dict:
    observations = observe(answer, question['indicator_ids'])
    missing = next((x['id'] for x in observations if x['value'] == 0), None)
    return {**question, 'kind': 'followup', 'parent_id': question['id'],
            'text': prompts.get(missing, fallback), 'probe_target': missing or 'depth'}
