"""Catalog expansion acceptance; authored data never executes on import."""
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.app.exercises import registry
from backend.app.models.domain import ExecutionObservation, OutputPredictionClaim
from exec_worker.runner.protocol import build_execute_envelope, emit_runner_frame, parse_runner_frame


def test_catalog_has_thirty_distinct_complete_original_problems():
    catalog = registry.public_catalog()
    assert len(catalog) >= 30
    assert len({p['exercise_id'] for p in catalog}) == len(catalog)
    assert len({p['function_name'] for p in catalog}) == len(catalog)
    for problem in catalog:
        assert problem['examples'] and problem['input_schema'] and problem['output_schema']
        assert problem['provenance']['status'] == 'ORIGINAL_AUTHORED'
        assert problem['catalog_status'] == 'READY'
        assert not {'oracle', 'curriculum', 'holdout', 'known_bugs', 'alternatives', 'boundary', 'generated'} & problem.keys()
        for spec in problem['spec_versions']:
            key = problem['exercise_id'], spec['spec_version']
            curriculum, holdout = registry.cases(*key, 'curriculum'), registry.cases(*key, 'holdout')
            assert len(curriculum) >= 5 and len(holdout) >= 2
            assert not {registry.case_key(*key, x) for x in curriculum} & {registry.case_key(*key, x) for x in holdout}
            for case in curriculum + holdout:
                registry.validate_output(*key, registry.evaluate(*key, case))
        for example in problem['examples']:
            assert registry.compare_output(example['output'], registry.evaluate(problem['exercise_id'], problem['default_spec_version'], example['input_args']))


@pytest.mark.parametrize('value', [False, True, '', 'தமிழ்', [], [1, -2], [True, False], ['a', 'b']])
def test_typed_outputs_roundtrip_models_and_untrusted_protocol(value):
    observation = ExecutionObservation(kind='RETURN', return_value=value, duration_ms=1)
    assert type(observation.model_dump(mode='json')['return_value']) is type(value)
    claim = OutputPredictionClaim(challenge_id=uuid4(), predicted_output=value, extraction_method='USER_EDITED', confirmed_at=datetime.now(timezone.utc))
    assert type(claim.model_dump(mode='json')['predicted_output']) is type(value)
    parsed = parse_runner_frame(emit_runner_frame(build_execute_envelope(kind='RETURN', return_value=value)))
    assert parsed.kind == 'RETURN' and registry.compare_output(parsed.return_value, value)


@pytest.mark.parametrize('value', [1.0, None, {}, (1,), [[1]], [None], 2**53, 'x'*257])
def test_output_bounds_reject_unsupported_types(value):
    with pytest.raises(ValidationError):
        ExecutionObservation(kind='RETURN', return_value=value, duration_ms=0)
    assert parse_runner_frame(emit_runner_frame(build_execute_envelope(kind='RETURN', return_value=value))).kind == 'INVALID_RESULT'


def test_strict_structural_comparator_rejects_boolean_integer_aliasing():
    assert not registry.compare_output(True, 1)
    assert not registry.compare_output([True], [1])
    assert not registry.compare_output([1.0], [1])
    assert registry.compare_output(['x', False, 2], ['x', False, 2])


def test_data_import_rejects_duplicate_incomplete_and_unsupported_packages():
    packages = registry.catalog_packages()
    registry.validate_catalog(packages)
    with pytest.raises(ValueError):
        registry.validate_catalog(packages + [deepcopy(packages[0])])
    for field in ('examples', 'known_bugs', 'alternatives', 'hints', 'provenance', 'boundary', 'generated'):
        bad = deepcopy(packages)
        del bad[0][field]
        with pytest.raises(ValueError):
            registry.validate_catalog(bad)
    bad = deepcopy(packages)
    bad[0]['output_schema'] = {'kind': 'float'}
    with pytest.raises(ValueError):
        registry.validate_catalog(bad)
    bad = deepcopy(packages)
    bad[0]['examples'][0]['output'] = 1.0
    with pytest.raises(ValueError):
        registry.validate_catalog(bad)


def test_data_only_json_import_never_executes_source(tmp_path):
    import json
    packages = registry.catalog_packages()
    marker = tmp_path / 'must-not-exist'
    fixture = packages[0]['alternatives'][0]
    fixture['source_code'] = f'import pathlib\npathlib.Path({str(marker)!r}).write_text("unsafe")\n' + fixture['source_code']
    path = tmp_path / 'catalog.json'
    path.write_text(json.dumps(packages))
    assert len(registry.load_catalog(path)) == len(packages)
    assert not marker.exists()
    path.write_text('[{"exercise_id":"x", "exercise_id":"y"}]')
    with pytest.raises(ValueError, match='Duplicate JSON'):
        registry.load_catalog(path)


@pytest.mark.parametrize('field,value', [
    ('comparator', 'loose'), ('difficulty', 'unknown'), ('catalog_status', 'DRAFT'),
    ('provenance', {'source': 'external'}), ('generated', {'kind': 'python_eval'}),
    ('hints', {'1': 'Only one hint'}), ('holdout', []), ('curriculum', []),
    ('spec_versions', []), ('starter_code', 'def wrong(): pass'),
    ('input_schema', {'nums': {'kind': 'list', 'items': {'kind': 'float'}}}),
])
def test_import_gate_rejects_incomplete_or_unsupported_metadata(field, value):
    package = registry.catalog_packages()[0]
    package[field] = value
    with pytest.raises(ValueError):
        registry.validate_catalog([package])


def test_import_cannot_expand_trusted_oracle_domain():
    package = next(p for p in registry.catalog_packages() if p['exercise_id'] == 'ex24_factorial')
    package['input_schema']['number']['maximum'] = 2**53-1
    with pytest.raises(ValueError, match='pinned server'):
        registry.validate_catalog([package])


def test_typed_output_lists_are_immutable_and_serialize_as_json_arrays():
    observation = ExecutionObservation(kind='RETURN', return_value=[True, 2], duration_ms=0)
    with pytest.raises(TypeError):
        observation.return_value.append(3)
    assert observation.model_dump(mode='json')['return_value'] == [True, 2]


def test_stack_oracle_distinguishes_nesting_from_counts():
    for text, expected in [('([)]', False), ('([{}])', True), ('x', True), ('(', False), (']', False)]:
        assert registry.evaluate('ex31_balanced_brackets', 'v1_typed_bounded', {'text': text}) is expected


def test_typed_input_rules_reject_coercion_and_return_independent_copy():
    key = 'ex29_all_true', 'v1_typed_bounded'
    assert registry.validate_input(*key, {'flags': [True, False]}) == {'flags': [True, False]}
    with pytest.raises(ValueError):
        registry.validate_input(*key, {'flags': [1]})
    with pytest.raises(ValueError):
        registry.validate_input(*key, {'flags': [False]*17})
    key = 'ex15_reverse_words', 'v1_typed_bounded'
    with pytest.raises(ValueError):
        registry.validate_input(*key, {'text': 4})
