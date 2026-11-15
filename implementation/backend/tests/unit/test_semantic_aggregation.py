"""Model aggregates cannot outrank their exact answer-bound criteria."""
import pytest
from backend.app.assessments.review import validate_candidate
from backend.app.assessments.schemas import ModelInterpretation

CONTEXT = {'question': 'Negative values are allowed.', 'answer': 'I assume all values are positive.'}


def result(criterion_status, aggregate='SUPPORTED', source='answer'):
    text = CONTEXT[source]
    refs = [{'source': source, 'start': 0, 'end': len(text), 'excerpt': text}]
    if criterion_status == 'CONTRADICTED_BY_EVIDENCE':
        refs.append({'source': 'question', 'start': 0, 'end': len(CONTEXT['question']), 'excerpt': CONTEXT['question']})
    return ModelInterpretation.model_validate({
        'status': aggregate,
        'criteria': [{'id': 'assumptions', 'status': criterion_status, 'explanation': 'Evidence-bound assumption signal.', 'evidence_refs': refs}],
        'uncertainty': 'Quality signal only; execution is unassessed.',
        'explanation': 'A bounded interpretation of the stated assumptions.',
        'followup': 'Where is this assumption stated in the question?',
    })


@pytest.mark.parametrize('criterion', ['CONTRADICTED_BY_EVIDENCE', 'INSUFFICIENT_EVIDENCE', 'PARTIALLY_SUPPORTED'])
def test_aggregate_supported_rejects_weaker_or_contradicted_criterion(criterion):
    with pytest.raises(ValueError, match='aggregate'):
        validate_candidate(result(criterion), CONTEXT)


def test_question_only_citation_cannot_support_answer_reasoning():
    with pytest.raises(ValueError, match='submitted answer'):
        validate_candidate(result('SUPPORTED', source='question'), CONTEXT)


def test_consistent_answer_bound_criterion_is_accepted_without_execution_claim():
    assert validate_candidate(result('SUPPORTED'), CONTEXT).status == 'SUPPORTED'
    assert validate_candidate(result('CONTRADICTED_BY_EVIDENCE', 'CONTRADICTED_BY_EVIDENCE'), CONTEXT).status == 'CONTRADICTED_BY_EVIDENCE'
