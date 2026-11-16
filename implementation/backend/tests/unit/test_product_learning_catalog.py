"""Authored curriculum validation and exact objective scoring."""
from copy import deepcopy
import pytest


def curriculum():
    from backend.app.learning.catalog import curriculum
    return curriculum()


def validate(value, **kwargs):
    from backend.app.learning.catalog import validate_catalog
    return validate_catalog(value, **kwargs)


def test_versioned_catalog_and_all_verified_question_answers():
    from backend.app.learning.catalog import evaluate_answer, public_catalog
    value = curriculum()
    validate(value)
    assert public_catalog(value)['version'] == '1.1.0'
    for track in value['tracks']:
        for lesson in track['lessons']:
            question = lesson['question']
            assert question['correct_answer'] in question['options']
            assert evaluate_answer(question, question['correct_answer'])['correct'] is True
            assert evaluate_answer(question, '  ' + question['correct_answer'].lower() + '  ')['correct'] is True
            assert all(evaluate_answer(question, wrong)['correct'] is False
                       for wrong in question['options'] if wrong != question['correct_answer'])
            assert evaluate_answer(question, 'I think ' + question['correct_answer'])['correct'] is False
            assert len(question['rationale']) >= 40
            assert lesson['explanation_rubric']['status'] == 'unassessed'
    leaked = public_catalog(value)
    leaked['tracks'][0]['lessons'][0]['title'] = 'mutated'
    assert curriculum()['tracks'][0]['lessons'][0]['title'] != 'mutated'


@pytest.mark.parametrize('damage,match', [
    ('cycle', 'cycle'), ('dangling', 'prerequisite'), ('duplicate', 'Duplicate'),
    ('answer', 'answer'), ('url', 'target'), ('blank', 'content'),
    ('question', 'question'), ('version', 'version'),
])
def test_rejects_dangling_cycles_duplicate_ids_invalid_targets(damage, match):
    value = curriculum()
    lessons = value['tracks'][0]['lessons']
    if damage == 'cycle':
        lessons[0]['prerequisites'] = [lessons[1]['id']]
        lessons[1]['prerequisites'] = [lessons[0]['id']]
    elif damage == 'dangling':
        lessons[0]['prerequisites'] = ['missing']
    elif damage == 'duplicate':
        lessons[1]['id'] = lessons[0]['id']
    elif damage == 'answer':
        lessons[0]['question']['correct_answer'] = 'invented'
    elif damage == 'url':
        lessons[0]['practice_url'] = '/practice/missing?spec=unknown'
    elif damage == 'blank':
        lessons[0]['explanation'] = 'TBD'
    elif damage == 'question':
        lessons[1]['question']['id'] = lessons[0]['question']['id']
    elif damage == 'version':
        value['version'] = 'latest'
    with pytest.raises(ValueError, match=match):
        validate(value)


def test_expanded_curriculum_covers_independent_missing_topic_lessons():
    value = curriculum()
    ids = {lesson['id'] for track in value['tracks'] for lesson in track['lessons']}
    required = {'dsa-strings', 'dsa-queue', 'dsa-recursion', 'dsa-backtracking', 'dsa-bst',
                'dsa-trie', 'dsa-topological', 'dsa-dijkstra', 'dsa-mst', 'dsa-union-find',
                'dsa-segment-tree', 'dsa-bits', 'dsa-number-theory', 'dsa-amortized',
                'cs-synchronization', 'cs-page-replacement', 'cs-sql', 'cs-isolation',
                'cs-recovery', 'cs-normal-forms', 'cs-osi', 'cs-dns', 'cs-tls', 'cs-congestion',
                'cs-polymorphism', 'cs-patterns', 'cs-cpu', 'cs-consistency', 'cs-requirements',
                'cs-sdlc', 'apt-profit', 'apt-interest', 'apt-mixtures', 'apt-divisibility',
                'apt-algebra', 'apt-geometry', 'apt-logical-puzzle', 'apt-assumptions',
                'apt-vocabulary', 'apt-di-table', 'apt-di-growth', 'apt-di-pie'}
    assert required <= ids


def test_missing_studio_scenario_and_executable_spec_are_rejected():
    value = curriculum()
    with pytest.raises(ValueError, match='target'):
        validate(value, exercise_targets={}, studio_targets={})
