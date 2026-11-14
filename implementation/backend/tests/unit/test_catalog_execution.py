"""Inert authored fixture checks and typed protocol tests; no learner execution."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from uuid import uuid4

import pytest

from backend.app.coaching.claim_extractor import extract_claim_deterministic
from backend.app.coaching.coach_engine import CoachEngine
from backend.app.db.repository import SQLiteRepository
from backend.app.exercises import registry
from backend.app.models.domain import ExecutionObservation, JobHandle, OutputPredictionClaim, VerificationReport
from backend.app.models.enums import ChallengePurpose
from backend.app.orchestration.restore import build_learning_snapshot
from backend.app.orchestration.state_machine import CoordinatorStateMachine
from backend.app.verification.hypothesis_strategies import generate_property_batch
from backend.app.verification.minimizer import shrink_counterexample

PACKAGES = registry.catalog_packages()
SPECS = registry.list_specs()


@pytest.mark.parametrize('package', PACKAGES, ids=lambda p: p['exercise_id'])
def test_authored_fixtures_are_inert_complete_data_and_oracles_cover_cases(package):
    ex, version = package['exercise_id'], package['default_spec_version']
    registry.validate_catalog([package])
    cases = package['curriculum'] + package['holdout'] + [e['input_args'] for e in package['examples']]
    generated = generate_property_batch(ex, version, count=5, seed=17).cases
    for case in cases + list(generated):
        registry.validate_output(ex, version, registry.evaluate(ex, version, case))
    # Validation parses fixture AST and signatures only. No compile/exec/eval,
    # subprocess, or local invocation of imported fixture source is permitted.
    for fixture in package['known_bugs']:
        registry.validate_input(ex, version, fixture['witness'])
        assert type(fixture['source_code']) is str


class TypedProtocolBroker:
    """Trusted oracle records only, not student execution or isolation evidence."""
    def __init__(self, output):
        self.output = output
        self.requests = []

    def submit_execution(self, req):
        self.requests.append(req)
        return JobHandle(job_id=req.job_id, revision=req.revision, status='COMPLETE',
                         observation=ExecutionObservation(kind='RETURN', return_value=self.output, duration_ms=0))

    def submit_verify(self, req):
        self.requests.append(req)
        ex, version = str(req.revision.exercise_id), str(req.revision.spec_version)
        curated = registry.cases(ex, version, 'curriculum')
        hashes = {registry.case_key(ex, version, c) for c in curated}
        generated = generate_property_batch(ex, version, count=req.generated_cases_target, seed=42, exclude_hashes=hashes).cases
        hashes |= {registry.case_key(ex, version, c) for c in generated}
        return JobHandle(job_id=req.job_id, revision=req.revision, status='COMPLETE', verification_report=VerificationReport(
            status='NO_FAILURE_FOUND', curated_cases_run=len(curated), curated_cases_total=len(curated),
            generated_cases_run=len(generated), generated_cases_target=req.generated_cases_target,
            completed_stages=['curated_suite', 'generated_suite'], executed_case_hashes=sorted(hashes),
            terminal_reason='Fixed typed protocol records, not executed student code', runtime_version='protocol-only'))

    def submit_trace(self, req):
        self.requests.append(req)
        return JobHandle(job_id=req.job_id, revision=req.revision, status='FAILED')


@pytest.mark.parametrize('spec', SPECS, ids=lambda s: f'{s.exercise_id}-{s.spec_version}')
def test_all_specs_typed_prediction_result_db_coaching_restore_transfer(spec, tmp_path):
    ex, version = spec.exercise_id, spec.spec_version
    repo = SQLiteRepository(tmp_path/'typed.db')
    repo.initialize()
    sid = str(uuid4())
    package = next(p for p in PACKAGES if p['exercise_id'] == ex)
    source = package['starter_code']
    repo.create_session(session_id=sid, token_hash='typed-protocol-only', exercise_id=ex, spec_version=version,
        language_mode='en-IN', interaction_mode='TYPED_FALLBACK', starter_code=source,
        starter_code_hash=hashlib.sha256(source.encode()).hexdigest(),
        expires_at=(datetime.now(timezone.utc)+timedelta(hours=24)).isoformat())
    case = registry.cases(ex, version, 'curriculum')[0]
    expected = registry.evaluate(ex, version, case)
    broker = TypedProtocolBroker(expected)
    machine = CoordinatorStateMachine(repo, worker_client=broker, coach_engine=CoachEngine(llm_api_key='', llm_model=''))
    challenge = machine.issue_challenge(sid, purpose=ChallengePurpose.DIAGNOSTIC, expected_revision=machine.build_revision_ref(sid))
    claim = OutputPredictionClaim(challenge_id=challenge.challenge_id, predicted_output=expected,
        extraction_method='USER_EDITED', confirmed_at=datetime.now(timezone.utc))
    turn, _ = repo.create_or_reuse_turn(session_id=sid, code_version_id=challenge.revision.code_version_id,
        challenge_id=str(challenge.challenge_id), transport_mode='TEXT', state='AWAITING_CLAIM_CONFIRMATION',
        normalized_transcript='Typed value', claim_json=claim.model_dump_json())
    wrong_type = {'integer': False, 'boolean': 1, 'string': [], 'list': 'not a list'}[spec.output_schema['kind']]
    bad_claim = claim.model_copy(update={'predicted_output': wrong_type})
    with pytest.raises(ValueError):
        machine.confirm_claim_and_execute(sid, turn_id=turn.id, challenge_id=challenge.challenge_id,
            expected_revision=challenge.revision, claim=bad_claim)
    assert not broker.requests
    assert repo.get_challenge(sid, str(challenge.challenge_id))['reveal_state'] == 'HIDDEN'
    result = machine.confirm_claim_and_execute(sid, turn_id=turn.id, challenge_id=challenge.challenge_id,
        expected_revision=challenge.revision, claim=claim)
    artifact = result['artifact']
    assert artifact['prediction_status'] == 'MATCH'
    assert registry.compare_output(artifact['confirmed_prediction'], expected)
    assert registry.compare_output(artifact['actual_observation']['return_value'], expected)
    assert 'maximum contiguous subarray product' not in result['coaching']['display_text'] or ex == 'ex3_max_product'
    with repo._connect() as conn:
        row = conn.execute('SELECT confirmed_prediction_json FROM evidence_artifacts WHERE id=?', (artifact['artifact_id'],)).fetchone()
    assert registry.compare_output(json.loads(row[0]), expected)
    snapshot = build_learning_snapshot(repo, machine, sid)
    assert registry.compare_output(snapshot['evidence_artifacts'][0]['confirmed_prediction'], expected)
    transfer = machine.issue_challenge(sid, purpose=ChallengePurpose.TRANSFER, expected_revision=machine.build_revision_ref(sid))
    assert transfer.reveal_state.value == 'HIDDEN'
    assert transfer.case_hash != challenge.case_hash


@pytest.mark.parametrize('value', [False, True, '', 'hello', [1, -2], ['a', 'b'], [True, False]])
def test_typed_json_prediction_extraction_preserves_exact_types(value):
    claim = extract_claim_deterministic(f'It returns {json.dumps(value)} because I traced the values', challenge_id=uuid4())
    assert isinstance(claim, OutputPredictionClaim)
    assert registry.compare_output(claim.predicted_output, value)
    assert claim.confirmed_at is None


def test_finite_domain_underfill_is_explicit_and_recommendation_is_achievable():
    package = next(p for p in registry.public_catalog() if p['exercise_id'] == 'ex24_factorial')
    spec = package['spec_versions'][0]
    assert spec['recommended_generated_cases'] == 6 and spec['available_fresh_cases'] == 2
    ex, version = package['exercise_id'], package['default_spec_version']
    excluded = {registry.case_key(ex, version, c) for c in registry.cases(ex, version, 'curriculum')}
    batch = generate_property_batch(ex, version, count=20, exclude_hashes=excluded)
    assert len(batch.cases) == 6 and batch.stop_reason == 'hypothesis_exhausted'


@pytest.mark.parametrize('ex,case', [('ex15_reverse_words', {'text': 'abc def'}), ('ex30_invert_flags', {'flags': [True, False, True]})])
def test_typed_shrinking_stays_in_domain_and_within_budget(ex, case):
    probes = []
    best, status = shrink_counterexample(ex, 'v1_typed_bounded', case,
        lambda candidate: probes.append(candidate) is None, max_probes=8)
    registry.validate_input(ex, 'v1_typed_bounded', best)
    assert len(probes) <= 8
