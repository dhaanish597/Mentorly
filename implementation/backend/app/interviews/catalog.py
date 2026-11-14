"""Allowlisted exercise metadata; never expose oracle code, hints or holdouts."""
from backend.app.exercises.registry import catalog_packages
from .policies import POLICIES

LANGUAGE_MODES = ['en-IN', 'ta-IN,en-IN']
DIFFICULTIES = ['beginner', 'intermediate', 'advanced']


def exercise_metadata() -> list[dict]:
    return [{'exercise_id': p['exercise_id'], 'title': p['title'], 'description': p['description'],
             'difficulty': p['difficulty'], 'spec_version': p['default_spec_version'],
             'topics': p['tags']} for p in catalog_packages() if p['catalog_status'] == 'READY']


def get_catalog() -> dict:
    exercises = exercise_metadata()
    return {'topics': {'dsa': sorted({t for p in exercises for t in p['topics']}),
                       **{kind: list(policy.TOPICS) for kind, policy in POLICIES.items() if kind != 'dsa'}},
            'dsa_exercises': exercises}


def get_config() -> dict:
    return {'types': list(POLICIES), 'difficulties': DIFFICULTIES,
            'duration_minutes': {'minimum': 5, 'maximum': 60, 'default': 15},
            'language_modes': LANGUAGE_MODES, 'camera_default': False,
            'camera_policy': 'Explicit permission, local preview only; never uploaded or assessed.',
            'assessment_policy': 'No correctness, scores or reference answers before completion.',
            'language_policy': 'Language mode is a voice preference. Deterministic question text is English; multilingual semantic validity is unassessed.'}


def build_plan(kind: str, difficulty: str, topics: list[str], minutes: int) -> list[dict]:
    catalog = get_catalog()
    invalid = set(topics) - set(catalog['topics'][kind])
    if invalid:
        raise ValueError('Choose topics from the interview catalog')
    if kind == 'dsa':
        pool = [p for p in catalog['dsa_exercises'] if not topics or set(topics).intersection(p['topics'])]
        # Difficulty tunes prompts; do not invent advanced metadata for beginner exercises.
        pool = sorted(pool, key=lambda p: (p['difficulty'] != difficulty, p['exercise_id']))
        plan = POLICIES[kind].questions(pool, difficulty)
    else:
        plan = POLICIES[kind].questions(topics or catalog['topics'][kind], difficulty)
    if not plan:
        raise ValueError('No catalog questions are available for this configuration')
    limit = min(8, max(2, minutes // 5))
    return [{**q, 'kind': 'primary', 'parent_id': None} for q in plan[:limit]]
