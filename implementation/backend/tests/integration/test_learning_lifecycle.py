"""Lifecycle protocol/state regressions, never learner execution evidence.

The broker double supplies fixed records only; it does not execute source code.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.db.repository import SQLiteRepository, RevisionConflictError
from backend.app.models.domain import (
    ExecutionObservation, JobHandle, OutputPredictionClaim, InvariantOrMechanismClaim,
    VerificationReport,
)
from backend.app.models.enums import ChallengePurpose, ExtractionMethod, SpecVersion
from backend.app.orchestration.state_machine import CoordinatorStateMachine


class ProtocolBroker:
    """Fixed protocol responses; not a sandbox and not execution evidence."""
    def __init__(self, returned=2, counterexample=None, unavailable=False):
        self.returned = returned
        self.counterexample = counterexample
        self.unavailable = unavailable
        self.requests = []

    def submit_execution(self, req):
        self.requests.append(req)
        obs = ExecutionObservation(kind='UNAVAILABLE' if self.unavailable else 'RETURN',
            return_value=None if self.unavailable else self.returned, duration_ms=0)
        return JobHandle(job_id=req.job_id, revision=req.revision, status='COMPLETE', observation=obs)

    def submit_verify(self, req):
        self.requests.append(req)
        report = VerificationReport(status='EXECUTION_UNAVAILABLE' if self.unavailable else
            ('COUNTEREXAMPLE_CONFIRMED' if self.counterexample else 'NO_FAILURE_FOUND'),
            curated_cases_run=0 if self.unavailable else 1, curated_cases_total=1,
            generated_cases_run=0, generated_cases_target=req.generated_cases_target,
            terminal_reason='Fixed protocol fixture, not execution evidence', runtime_version='protocol-fixture',
            counterexample_input=self.counterexample,
            student_observation=ExecutionObservation(kind='RETURN',return_value=987654,duration_ms=0)
                if self.counterexample else None,
            reference_output=123456 if self.counterexample else None)
        return JobHandle(job_id=req.job_id, revision=req.revision, status='COMPLETE', verification_report=report)

    def submit_trace(self, req):
        self.requests.append(req)
        return JobHandle(job_id=req.job_id, revision=req.revision, status='FAILED')


@pytest.fixture
def lifecycle(tmp_path):
    repo = SQLiteRepository(tmp_path/'lifecycle.db')
    repo.initialize()
    sid = str(uuid4())
    source = 'def shortest_subarray_ge_target(nums, target):\n    return 2\n'
    repo.create_session(session_id=sid, token_hash='protocol-only', exercise_id='ex1_shortest_subarray',
        spec_version='v1_positive_only', language_mode='en-IN', interaction_mode='TEXT', starter_code=source,
        starter_code_hash=hashlib.sha256(source.encode()).hexdigest(),
        expires_at=(datetime.now(timezone.utc)+timedelta(hours=24)).isoformat())
    machine = CoordinatorStateMachine(repo, worker_client=ProtocolBroker())
    return repo, sid, machine


def challenge_and_turn(lifecycle):
    repo, sid, machine = lifecycle
    c = machine.issue_challenge(sid, purpose=ChallengePurpose.DIAGNOSTIC,
        expected_revision=machine.build_revision_ref(sid), requested_input={'nums':[1,2,3], 'target':5})
    claim = OutputPredictionClaim(challenge_id=c.challenge_id, predicted_output=2,
        extraction_method=ExtractionMethod.USER_EDITED, confirmed_at=datetime.now(timezone.utc))
    turn, attempt = repo.create_or_reuse_turn(session_id=sid, code_version_id=c.revision.code_version_id,
        challenge_id=str(c.challenge_id), transport_mode='TEXT', state='AWAITING_CLAIM_CONFIRMATION',
        normalized_transcript='It returns 2', claim_json=claim.model_dump_json())
    return c, turn, attempt, claim


def confirm(lifecycle):
    repo, sid, machine = lifecycle
    c, turn, attempt, claim = challenge_and_turn(lifecycle)
    return machine.confirm_claim_and_execute(sid, turn_id=turn.id, challenge_id=c.challenge_id,
        expected_revision=c.revision, claim=claim)


def test_confirmation_returns_authoritative_revealed_challenge(lifecycle):
    result = confirm(lifecycle)
    assert result["challenge"]["reveal_state"] == "REVEALED"
    assert result["challenge"]["revision"] == result["artifact"]["revision"]
    assert result["challenge"]["case_hash"] == result["artifact"]["case_hash"]


def test_save_resets_learning_and_preserves_previous_failure(lifecycle):
    repo, sid, machine = lifecycle
    machine.worker_client = ProtocolBroker(counterexample={'nums':[9], 'target':9})
    result = confirm(lifecycle)
    old = machine.build_revision_ref(sid)
    source = 'def shortest_subarray_ge_target(nums, target):\n    return 1\n'
    repo.save_code_version(sid, expected_code_version_id=old.code_version_id, source_code=source,
        code_hash=hashlib.sha256(source.encode()).hexdigest())
    assert repo.get_session(sid).learning_state == 'EXPLAINING'
    assert machine.build_revision_ref(sid).turn_generation > old.turn_generation
    machine.worker_client = ProtocolBroker()
    confirm(lifecycle)
    verifies = [r for r in machine.worker_client.requests if hasattr(r,'prior_failing_input')]
    assert verifies[0].prior_failing_input == {'nums':[9], 'target':9}


def test_spec_switch_invalidates_active_turn_and_learning(lifecycle):
    repo, sid, machine = lifecycle
    c, turn, _, _ = challenge_and_turn(lifecycle)
    repo.update_session_states(sid, learning_state='PRACTICE_CHECKPOINT_COMPLETED')
    repo.update_spec(sid, spec_version='v2_negatives_allowed', expected_code_version_id=1)
    assert repo.get_session(sid).learning_state == 'EXPLAINING'
    assert repo.get_turn(sid,turn.id).state == 'SUPERSEDED'
    assert machine.build_revision_ref(sid).turn_generation > c.revision.turn_generation


def test_other_counterexample_gets_new_hidden_challenge_without_answer_leak(lifecycle):
    repo, sid, machine = lifecycle
    machine.worker_client = ProtocolBroker(counterexample={'nums':[9], 'target':9})
    result = confirm(lifecycle)
    diagnostic = result['diagnostic_challenge']
    assert diagnostic['input_args'] == {'nums':[9], 'target':9}
    assert diagnostic['reveal_state'] == 'HIDDEN'
    assert result['artifact']['canonical_input'] == {'nums':[1,2,3], 'target':5}
    assert result['artifact']['confirmed_prediction'] == 2
    assert result['artifact']['actual_observation']['return_value'] == 2
    assert result['artifact']['verification_report']['reference_output'] is None
    assert result['artifact']['verification_report']['student_observation'] is None
    assert '987654' not in json.dumps(repo.export_session_bundle(sid))
    assert '123456' not in json.dumps(repo.export_session_bundle(sid))


def test_cancelled_turn_cannot_be_confirmed_or_revived(lifecycle):
    repo, sid, machine = lifecycle
    c, turn, _, claim = challenge_and_turn(lifecycle)
    machine.cancel_active_work(sid)
    with pytest.raises(RevisionConflictError):
        machine.confirm_claim_and_execute(sid, turn_id=turn.id, challenge_id=c.challenge_id,
            expected_revision=c.revision, claim=claim)
    with pytest.raises(RevisionConflictError):
        repo.update_turn(sid,turn.id,state='AWAITING_CLAIM_CONFIRMATION')
    assert repo.get_challenge(sid,str(c.challenge_id))['reveal_state'] == 'HIDDEN'


def test_stale_capture_cannot_confirm_new_proposal(lifecycle):
    repo, sid, machine = lifecycle
    c, turn, attempt, claim = challenge_and_turn(lifecycle)
    repo.create_or_reuse_turn(session_id=sid, code_version_id=1, challenge_id=str(c.challenge_id),
        state='AWAITING_CLAIM_CONFIRMATION', claim_json=claim.model_dump_json())
    with pytest.raises(RevisionConflictError):
        machine.confirm_claim_and_execute(sid, turn_id=turn.id, challenge_id=c.challenge_id,
            expected_revision=c.revision, claim=claim, capture_attempt_id=attempt)
    assert repo.get_challenge(sid,str(c.challenge_id))['reveal_state'] == 'HIDDEN'


def test_explanation_confirmation_does_not_execute_or_reveal(lifecycle):
    repo, sid, machine = lifecycle
    c, turn, _, _ = challenge_and_turn(lifecycle)
    claim = InvariantOrMechanismClaim(challenge_id=c.challenge_id, mechanism_summary='The window shrinks',
        extraction_method=ExtractionMethod.USER_EDITED, confirmed_at=datetime.now(timezone.utc))
    result = machine.confirm_claim_and_execute(sid,turn_id=turn.id,challenge_id=c.challenge_id,
        expected_revision=c.revision,claim=claim,capture_attempt_id=turn.latest_capture_attempt_id)
    assert result['requires_prediction'] is True
    assert result['executed'] is False
    assert 'artifact' not in result and 'trace_report' not in result
    assert machine.worker_client.requests == []
    assert repo.get_challenge(sid,str(c.challenge_id))['reveal_state'] == 'HIDDEN'


def test_retry_unavailable_reuses_confirmed_claim_and_rejects_evaluated_retry(lifecycle):
    repo, sid, machine = lifecycle
    machine.worker_client = ProtocolBroker(unavailable=True)
    c, turn, _, claim = challenge_and_turn(lifecycle)
    machine.confirm_claim_and_execute(sid,turn_id=turn.id,challenge_id=c.challenge_id,
        expected_revision=c.revision,claim=claim)
    saved = repo.get_turn(sid,turn.id).claim_json
    machine.worker_client = ProtocolBroker()
    result = machine.retry_execution(sid,turn_id=turn.id,expected_revision=c.revision)
    assert result['artifact']['confirmed_prediction'] == 2
    assert repo.get_turn(sid,turn.id).claim_json == saved
    with pytest.raises(RevisionConflictError):
        machine.retry_execution(sid,turn_id=turn.id,expected_revision=c.revision)


def test_transfer_wrong_prediction_is_not_a_code_repair(lifecycle):
    repo, sid, machine = lifecycle
    confirm(lifecycle)
    c = machine.issue_challenge(sid,purpose=ChallengePurpose.TRANSFER,expected_revision=machine.build_revision_ref(sid))
    from backend.app.exercises import registry
    machine.worker_client = ProtocolBroker(returned=registry.evaluate('ex1_shortest_subarray','v1_positive_only',c.canonical_input_copy()))
    claim = OutputPredictionClaim(challenge_id=c.challenge_id,predicted_output=-999,
        extraction_method=ExtractionMethod.USER_EDITED,confirmed_at=datetime.now(timezone.utc))
    result = machine.confirm_claim_and_execute(sid,turn_id=None,challenge_id=c.challenge_id,
        expected_revision=c.revision,claim=claim)
    assert result['learning_state'] == 'PREDICTION_REVIEW'


def test_http_restore_verify_retry_and_sequential_hints(tmp_path):
    from backend.app.main import create_app
    from backend.app.core.config import Settings
    settings = Settings(_env_file=None,database_path=tmp_path/'http.db',tts_cache_dir=tmp_path/'tts')
    with TestClient(create_app(settings)) as client:
        created = client.post('/api/v1/sessions',json={'exercise_id':'ex1_shortest_subarray','spec_version':'v1_positive_only'}).json()
        path = '/api/v1/sessions/'+created['session_id']
        auth = {'Authorization':'Bearer '+created['session_token']}
        def post(suffix, data):
            return client.post(path+suffix,json=data,headers={**auth,'X-Idempotency-Key':str(uuid4())})
        c = post('/challenges',{'revision':created['revision'],'purpose':'DIAGNOSTIC'}).json()
        turn = post('/turns/text',{'revision':c['revision'],'challenge_id':c['challenge_id'],'text':'It returns 2'}).json()
        snapshot = client.get(path,headers=auth).json()
        assert snapshot['active_turn']['turn_id'] == turn['turn_id']
        assert snapshot['active_turn']['capture_attempt_id'] == turn['capture_attempt_id']
        claim = {**turn['proposed_claim'],'confirmed_at':datetime.now(timezone.utc).isoformat()}
        confirmed = post('/turns/'+turn['turn_id']+'/confirm-claim',{'revision':c['revision'],'challenge_id':c['challenge_id'],'claim':claim})
        assert confirmed.status_code == 200, confirmed.text
        artifact = confirmed.json()['artifact']
        skipped = post('/hints',{'revision':c['revision'],'artifact_id':artifact['artifact_id'],'requested_level':3})
        assert skipped.status_code == 409, skipped.text
        retried = post('/turns/'+turn['turn_id']+'/retry-execution',{'revision':c['revision']})
        assert retried.status_code == 200, retried.text
        source = 'def shortest_subarray_ge_target(nums,target):\n    return 1\n'
        saved = client.put(path+'/code',json={'expected_code_version_id':1,'code':source,'client_edit_sequence':1},headers={**auth,'X-Idempotency-Key':str(uuid4())})
        assert saved.status_code == 200, saved.text
        snapshot = client.get(path,headers=auth).json()
        assert snapshot['challenges'] == []
        assert snapshot['evidence_artifacts'] == []
        assert snapshot['active_turn'] is None
        assert snapshot['trace_report'] is None
        assert snapshot['coaching'] is None
        verified = post('/verify',{'revision':saved.json()['revision'],'prior_artifact_id':artifact['artifact_id']})
        assert verified.status_code == 200, verified.text
        assert verified.json()['verification_report']['status'] == 'EXECUTION_UNAVAILABLE'
        hidden = post('/challenges',{'revision':snapshot['revision'],'purpose':'DIAGNOSTIC'}).json()
        draft = post('/turns/text',{'revision':hidden['revision'],'challenge_id':hidden['challenge_id'],'text':'It returns 1'}).json()
        cancelled = post('/cancel',{'scope':'TURN','reason':'Cancel active capture'})
        assert cancelled.status_code == 200, cancelled.text
        rejected = post('/turns/'+draft['turn_id']+'/confirm-claim',{
            'revision':hidden['revision'],'challenge_id':hidden['challenge_id'],'capture_attempt_id':draft['capture_attempt_id'],
            'claim':{**draft['proposed_claim'],'confirmed_at':datetime.now(timezone.utc).isoformat()}})
        assert rejected.status_code == 409,rejected.text


def test_transfer_exhaustion_is_explicit_unavailable_and_cases_are_unseen(lifecycle):
    from backend.app.exercises import registry
    from backend.app.api.routes_sessions import _translate_repo_error
    repo, sid, machine = lifecycle
    confirm(lifecycle)
    seen = set()
    for _ in registry.cases('ex1_shortest_subarray','v1_positive_only','holdout'):
        c = machine.issue_challenge(sid,purpose=ChallengePurpose.TRANSFER,expected_revision=machine.build_revision_ref(sid))
        assert c.case_hash not in seen
        seen.add(c.case_hash)
    with pytest.raises(RevisionConflictError) as error:
        machine.issue_challenge(sid,purpose=ChallengePurpose.TRANSFER,expected_revision=machine.build_revision_ref(sid))
    assert _translate_repo_error(error.value).code == 'TRANSFER_UNAVAILABLE'


def test_evaluated_target_is_preserved_when_later_worker_call_fails(lifecycle):
    from backend.app.orchestration.worker_client import BrokerCommunicationError
    repo, sid, machine = lifecycle
    class PartialBroker(ProtocolBroker):
        def submit_verify(self, req):
            raise BrokerCommunicationError('protocol transport unavailable')
    machine.worker_client = PartialBroker()
    c, turn, _, claim = challenge_and_turn(lifecycle)
    result = machine.confirm_claim_and_execute(sid,turn_id=turn.id,challenge_id=c.challenge_id,
        expected_revision=c.revision,claim=claim)
    assert result['artifact']['actual_observation']['return_value'] == 2
    assert result['artifact']['prediction_status'] == 'MATCH'
    assert result['artifact']['verification_report']['status'] == 'EXECUTION_UNAVAILABLE'
    with pytest.raises(RevisionConflictError):
        machine.retry_execution(sid,turn_id=turn.id,expected_revision=c.revision)


def test_late_capture_completion_cannot_overwrite_rerecord(lifecycle):
    repo, sid, machine = lifecycle
    c, turn, attempt, claim = challenge_and_turn(lifecycle)
    newer, current_attempt = repo.create_or_reuse_turn(session_id=sid,code_version_id=1,
        challenge_id=str(c.challenge_id),state='AWAITING_CLAIM_CONFIRMATION',normalized_transcript='New draft')
    with pytest.raises(RevisionConflictError):
        repo.update_turn(sid,turn.id,normalized_transcript='Late old speech',expected_capture_attempt_id=attempt)
    assert repo.get_turn(sid,turn.id).normalized_transcript == 'New draft'
    assert current_attempt == attempt + 1


def test_prior_failure_owned_by_session_and_spec_and_retained_after_reload(lifecycle):
    repo, sid, machine = lifecycle
    machine.worker_client = ProtocolBroker(counterexample={'nums':[9],'target':9})
    confirm(lifecycle)
    rev = machine.build_revision_ref(sid)
    artifact_id = repo.get_prior_failing_artifact_id(sid,rev)
    assert repo.get_prior_failing_input(sid,rev,artifact_id) == {'nums':[9],'target':9}
    from backend.app.db.repository import RepositoryError
    with pytest.raises(RepositoryError):
        repo.get_prior_failing_input(sid,rev,str(uuid4()))
    repo.update_spec(sid,spec_version='v2_negatives_allowed',expected_code_version_id=1)
    new_rev = machine.build_revision_ref(sid)
    assert repo.get_prior_failing_artifact_id(sid,new_rev) is None
    assert repo.get_prior_failing_input(sid,new_rev) is None
    with pytest.raises(RevisionConflictError):
        repo.get_prior_failing_input(sid,new_rev,artifact_id)


def test_hidden_diagnostic_redaction_in_http_idempotency_restore_hints_and_speech(tmp_path,monkeypatch):
    from backend.app.main import create_app
    from backend.app.core.config import Settings
    from backend.app.api import routes_sessions
    settings = Settings(_env_file=None,database_path=tmp_path/'redaction.db',tts_cache_dir=tmp_path/'tts')
    class ProjectionCoach:
        def build_coaching_turn_response(self,**kwargs):
            serialized = kwargs['artifact'].model_dump_json()
            assert '987654' not in serialized and '123456' not in serialized
            return {'display_text':'Predict the different failing input first.','speakable_text':'Predict first.'}
    with TestClient(create_app(settings)) as client:
        created = client.post('/api/v1/sessions',json={'exercise_id':'ex1_shortest_subarray','spec_version':'v1_positive_only'}).json()
        sid = created['session_id']; path = '/api/v1/sessions/'+sid
        auth = {'Authorization':'Bearer '+created['session_token']}
        repo = SQLiteRepository(settings.database_path)
        machine = CoordinatorStateMachine(repo,worker_client=ProtocolBroker(counterexample={'nums':[9],'target':9}),coach_engine=ProjectionCoach())
        monkeypatch.setattr(routes_sessions,'_get_repo_and_machine',lambda:(repo,machine))
        def post(suffix, data, key=None):
            return client.post(path+suffix,json=data,headers={**auth,'X-Idempotency-Key':key or str(uuid4())})
        c = post('/challenges',{'purpose':'DIAGNOSTIC','revision':created['revision'],
            'requested_input':{'nums':[1,2,3],'target':5}}).json()
        turn = post('/turns/text',{'revision':c['revision'],'challenge_id':c['challenge_id'],'text':'It returns 2'}).json()
        key = str(uuid4())
        body = {'revision':c['revision'],'challenge_id':c['challenge_id'],'capture_attempt_id':turn['capture_attempt_id'],
            'claim':{**turn['proposed_claim'],'confirmed_at':datetime.now(timezone.utc).isoformat()}}
        response = post('/turns/'+turn['turn_id']+'/confirm-claim',body,key)
        assert response.status_code == 200,response.text
        assert '987654' not in response.text and '123456' not in response.text
        assert post('/turns/'+turn['turn_id']+'/confirm-claim',body,key).json() == response.json()
        snapshot = client.get(path,headers=auth)
        assert '987654' not in snapshot.text and '123456' not in snapshot.text
        snapshot = snapshot.json()
        assert len(snapshot['challenges']) == 1
        assert snapshot['challenges'][0]['reveal_state'] == 'HIDDEN'
        hidden = snapshot['evidence_artifacts'][0]
        assert hidden['reveal_state'] == 'HIDDEN'
        assert snapshot['prior_artifact_id'] is not None
        assert post('/hints',{'revision':snapshot['revision'],'artifact_id':hidden['artifact_id'],'requested_level':1}).status_code == 409
        assert post('/speech/tts',{'revision':snapshot['revision'],'artifact_id':hidden['artifact_id']}).status_code == 409
        exported = client.get(path+'/export',headers=auth)
        assert '987654' not in exported.text and '123456' not in exported.text
        diagnostic = response.json()['diagnostic_challenge']
        machine.worker_client = ProtocolBroker(returned=987654)
        second = post('/turns/text',{'revision':diagnostic['revision'],'challenge_id':diagnostic['challenge_id'],'text':'It returns 987654'}).json()
        second_body = {'revision':diagnostic['revision'],'challenge_id':diagnostic['challenge_id'],
            'capture_attempt_id':second['capture_attempt_id'],'claim':{**second['proposed_claim'],'confirmed_at':datetime.now(timezone.utc).isoformat()}}
        machine.coach_engine = None
        assert post('/turns/'+second['turn_id']+'/confirm-claim',second_body).status_code == 200
        exported = client.get(path+'/export',headers=auth).json()
        original = next(a for a in exported['evidence_artifacts'] if a['challenge_id'] == c['challenge_id'])
        assert original['confirmed_prediction'] == 2
        assert original['verification_report']['reference_output'] == 123456


def test_hint_access_is_graduated_and_speech_cannot_skip(lifecycle):
    repo, sid, machine = lifecycle
    result = confirm(lifecycle)
    rev = machine.build_revision_ref(sid)
    artifact_id = result['artifact']['artifact_id']
    with pytest.raises(RevisionConflictError):
        repo.advance_hint(sid,artifact_id,rev,3)
    repo.advance_hint(sid,artifact_id,rev,1)
    repo.advance_hint(sid,artifact_id,rev,2)
    with pytest.raises(RevisionConflictError):
        repo.require_unlocked_hint(sid,artifact_id,3)
    repo.advance_hint(sid,artifact_id,rev,3)
    repo.require_unlocked_hint(sid,artifact_id,3)


def test_verify_options_forwarded_to_worker_without_executing_target(lifecycle):
    repo, sid, machine = lifecycle
    result = machine.verify_revision(sid,expected_revision=machine.build_revision_ref(sid),
        run_curated_suite=False,generated_cases_target=0)
    assert result['verification_report']['reference_output'] is None
    assert len(machine.worker_client.requests) == 1
    request = machine.worker_client.requests[0]
    assert request.run_curated_suite is False
    assert request.generated_cases_target == 0
    assert request.target_input is None


def test_explanation_without_challenge_is_capture_bound(lifecycle):
    repo, sid, machine = lifecycle
    turn, attempt = repo.create_or_reuse_turn(session_id=sid,code_version_id=1,challenge_id=None,
        state='AWAITING_CLAIM_CONFIRMATION',normalized_transcript='Unicode mechanism λ',transport_mode='TEXT')
    claim = InvariantOrMechanismClaim(mechanism_summary='Unicode mechanism λ',extraction_method='USER_EDITED',
        confirmed_at=datetime.now(timezone.utc))
    rev = machine.build_revision_ref(sid)
    with pytest.raises(RevisionConflictError):
        machine.confirm_claim_and_execute(sid,turn_id=turn.id,challenge_id=None,expected_revision=rev,claim=claim)
    result = machine.confirm_claim_and_execute(sid,turn_id=turn.id,challenge_id=None,expected_revision=rev,
        claim=claim,capture_attempt_id=attempt)
    assert result['executed'] is False
    assert result['turn_id'] == turn.id
    assert result['proposed_claim']['mechanism_summary'] == 'Unicode mechanism λ'
    assert machine.worker_client.requests == []


def test_foreign_worker_trace_cannot_be_misattributed_to_predicted_case(lifecycle):
    from backend.app.models.domain import TraceExecutionReport
    repo, sid, machine = lifecycle
    class ForeignTraceBroker(ProtocolBroker):
        def submit_trace(self, req):
            trace = TraceExecutionReport(trace_id=req.trace_id,revision=req.revision,case_hash='f'*64,
                status='COMPLETED',total_observed=0,termination_reason='foreign protocol fixture',
                runtime_version='protocol-fixture',observation=ExecutionObservation(kind='RETURN',return_value=987654,duration_ms=0))
            return JobHandle(job_id=req.job_id,revision=req.revision,status='COMPLETE',trace_report=trace)
    machine.worker_client = ForeignTraceBroker()
    result = confirm(lifecycle)
    assert result['trace_report'] is None
    assert result['artifact']['trace_id'] is None
    assert '987654' not in json.dumps(result)


def test_spec_update_cas_rejects_racing_same_code_spec_change(lifecycle):
    repo, sid, machine = lifecycle
    old = machine.build_revision_ref(sid)
    repo.update_spec(sid,spec_version='v2_negatives_allowed',expected_code_version_id=1)
    with pytest.raises(RevisionConflictError):
        repo.update_spec(sid,spec_version='v1_positive_only',expected_code_version_id=1,
            expected_revision=old,spec_acknowledged=True)


class BoundedProgressBroker(ProtocolBroker):
    """Fixed complete report records only; not verification execution evidence."""
    def submit_verify(self, req):
        from backend.app.exercises import registry
        self.requests.append(req)
        cases = registry.cases(req.revision.exercise_id.value,req.revision.spec_version.value,'curriculum') if req.run_curated_suite else []
        hashes = {registry.case_key(req.revision.exercise_id.value,req.revision.spec_version.value,c) for c in cases}
        stages = ['curated_suite'] if req.run_curated_suite else []
        if req.prior_failing_input is not None:
            hashes.add(registry.case_key(req.revision.exercise_id.value,req.revision.spec_version.value,req.prior_failing_input))
            stages = ['prior_failing_input',*stages]
        report = VerificationReport(status='NO_FAILURE_FOUND',curated_cases_run=len(cases),curated_cases_total=len(cases),
            generated_cases_run=0,generated_cases_target=req.generated_cases_target,completed_stages=stages,
            executed_case_hashes=sorted(hashes),terminal_reason='Fixed bounded progress protocol fixture',runtime_version='protocol-fixture',
            student_observation=ExecutionObservation(kind='RETURN',return_value=987654,duration_ms=0),reference_output=123456)
        return JobHandle(job_id=req.job_id,revision=req.revision,status='COMPLETE',verification_report=report)


def test_repaired_verification_unlocks_transfer_and_restores_exact_revision(lifecycle):
    from backend.app.orchestration.restore import build_learning_snapshot
    repo, sid, machine = lifecycle
    machine.worker_client = ProtocolBroker(counterexample={'nums':[9],'target':9})
    confirm(lifecycle)
    old = machine.build_revision_ref(sid)
    source = 'def shortest_subarray_ge_target(nums,target):\n    return 1\n'
    repo.save_code_version(sid,expected_code_version_id=old.code_version_id,source_code=source,
        code_hash=hashlib.sha256(source.encode()).hexdigest())
    rev = machine.build_revision_ref(sid)
    machine.worker_client = BoundedProgressBroker()
    result = machine.verify_revision(sid,expected_revision=rev,generated_cases_target=0)
    assert result['session_state'] == 'READY'
    assert result['learning_state'] == 'FRESH_CASE_CHECK'
    assert result['challenge'] is None and result['artifact'] is None and result['trace_report'] is None
    assert result['verification_report']['reference_output'] is None
    assert result['verification_report']['student_observation'] is None
    assert '987654' not in json.dumps(result) and '123456' not in json.dumps(result)
    with repo._connect() as conn:
        row = conn.execute("SELECT payload_json FROM session_events WHERE session_id=? AND event_type='VERIFICATION_COMPLETED'",(sid,)).fetchone()
        assert row is not None
        event = json.loads(row[0])
        assert event['revision'] == rev.model_dump(mode='json')
        assert event['verification_report'] == result['verification_report']
        assert conn.execute('SELECT count(*) FROM evidence_artifacts WHERE session_id=? AND code_version_id=?',(sid,rev.code_version_id)).fetchone()[0] == 0
    restored = build_learning_snapshot(repo,machine,sid)
    assert restored['verification_report'] == result['verification_report']
    transfer = machine.issue_challenge(sid,purpose=ChallengePurpose.TRANSFER,expected_revision=rev)
    assert transfer.reveal_state.value == 'HIDDEN'
    assert build_learning_snapshot(repo,machine,sid)['verification_report'] is None
    next_transfer = machine.issue_challenge(sid,purpose=ChallengePurpose.TRANSFER,expected_revision=transfer.revision)
    assert next_transfer.case_hash != transfer.case_hash
    current = machine.build_revision_ref(sid)
    repo.save_code_version(sid,expected_code_version_id=current.code_version_id,source_code=source+'# changed\n',
        code_hash=hashlib.sha256((source+'# changed\n').encode()).hexdigest())
    with pytest.raises(RevisionConflictError):
        machine.issue_challenge(sid,purpose=ChallengePurpose.TRANSFER,expected_revision=machine.build_revision_ref(sid))


@pytest.mark.parametrize('run_curated,target,drop_hashes', [(False,0,False),(True,0,True),(True,2,False)])
def test_empty_or_incomplete_verification_cannot_claim_success_or_unlock_transfer(lifecycle,run_curated,target,drop_hashes):
    from backend.app.orchestration.restore import build_learning_snapshot
    repo, sid, machine = lifecycle
    class IncompleteProgressBroker(BoundedProgressBroker):
        def submit_verify(self, req):
            handle = super().submit_verify(req)
            if drop_hashes:
                handle = handle.model_copy(update={'verification_report':handle.verification_report.model_copy(update={'executed_case_hashes':[]})})
            return handle
    machine.worker_client = IncompleteProgressBroker()
    rev = machine.build_revision_ref(sid)
    result = machine.verify_revision(sid,expected_revision=rev,run_curated_suite=run_curated,generated_cases_target=target)
    assert result['verification_report']['status'] == 'VERIFICATION_INCOMPLETE'
    assert result['learning_state'] != 'FRESH_CASE_CHECK'
    assert build_learning_snapshot(repo,machine,sid)['verification_report']['status'] == 'VERIFICATION_INCOMPLETE'
    with pytest.raises(RevisionConflictError):
        machine.issue_challenge(sid,purpose=ChallengePurpose.TRANSFER,expected_revision=rev)


@pytest.mark.parametrize('failed_stage', ['verify','trace'])
@pytest.mark.parametrize('failure_kind', ['invalid_model','malformed_json','timeout'])
def test_worker_report_failures_preserve_evaluated_target_and_reject_retry(lifecycle,failed_stage,failure_kind):
    import httpx
    from backend.app.orchestration.worker_client import WorkerClient
    repo, sid, machine = lifecycle
    cancelled = []
    class ReportTransport:
        def post(self,url,**kwargs):
            if '/cancel/' in url:
                cancelled.append(url)
                return httpx.Response(200,json={'cancelled':True})
            if url.endswith('/'+failed_stage):
                if failure_kind == 'timeout':
                    raise httpx.ReadTimeout('fixed protocol timeout')
                if failure_kind == 'malformed_json':
                    return httpx.Response(200,content=b'not-json')
                return httpx.Response(200,json={'private_payload':'DO_NOT_ECHO_WORKER_PAYLOAD','status':'invented'})
            if url.endswith('/execute'):
                return httpx.Response(200,json=ExecutionObservation(kind='RETURN',return_value=2,duration_ms=0).model_dump(mode='json'))
            if url.endswith('/verify'):
                report = VerificationReport(status='VERIFICATION_INCOMPLETE',curated_cases_run=0,curated_cases_total=1,
                    generated_cases_run=0,generated_cases_target=20,terminal_reason='fixed protocol fixture',runtime_version='protocol-fixture')
                return httpx.Response(200,json=report.model_dump(mode='json'))
            return httpx.Response(200,json={'private_payload':'DO_NOT_ECHO_WORKER_PAYLOAD'})
    machine.worker_client = WorkerClient(base_url='http://protocol-only.invalid',internal_worker_secret='protocol-fixture',
        http_client=ReportTransport(),session_repository=repo)
    c, turn, _, claim = challenge_and_turn(lifecycle)
    result = machine.confirm_claim_and_execute(sid,turn_id=turn.id,challenge_id=c.challenge_id,
        expected_revision=c.revision,claim=claim,capture_attempt_id=turn.latest_capture_attempt_id)
    assert result['artifact']['actual_observation']['return_value'] == 2
    assert result['artifact']['prediction_status'] == 'MATCH'
    assert result['trace_report'] is None
    assert 'DO_NOT_ECHO_WORKER_PAYLOAD' not in json.dumps(result)
    with pytest.raises(RevisionConflictError):
        machine.retry_execution(sid,turn_id=turn.id,expected_revision=c.revision)
    if failure_kind == 'timeout':
        assert any('/internal/cancel/' in url for url in cancelled)
