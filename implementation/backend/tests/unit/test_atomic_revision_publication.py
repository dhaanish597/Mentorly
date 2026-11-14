"""Persistence races and cancellation checks use trusted records only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
from uuid import uuid4
import pytest
from backend.app.db.repository import SQLiteRepository, RevisionConflictError, SessionDeletedError
from backend.app.models.enums import ChallengePurpose, SpecVersion
from backend.app.orchestration.state_machine import CoordinatorStateMachine


@pytest.fixture
def session(tmp_path):
    repo=SQLiteRepository(tmp_path/'state.sqlite3');repo.initialize()
    sid=str(uuid4());source='def shortest_subarray_ge_target(nums,target):\n    return 0\n'
    repo.create_session(session_id=sid,token_hash='test-token',exercise_id='ex1_shortest_subarray',
        spec_version='v1_positive_only',language_mode='en-IN',interaction_mode='TEXT',
        starter_code=source,starter_code_hash=hashlib.sha256(source.encode()).hexdigest(),
        expires_at=(datetime.now(timezone.utc)+timedelta(hours=24)).isoformat())
    return repo,sid,CoordinatorStateMachine(repo)


def run_twice(fn):
    def call(_):
        try:return fn()
        except RevisionConflictError:return 'CONFLICT'
    with ThreadPoolExecutor(max_workers=2) as pool:return list(pool.map(call,range(2)))


def test_concurrent_challenge_publication_allocates_one_bound_generation(session):
    repo,sid,machine=session;rev=machine.build_revision_ref(sid)
    results=run_twice(lambda:machine.issue_challenge(sid,purpose=ChallengePurpose.DIAGNOSTIC,expected_revision=rev))
    assert sum(x=='CONFLICT' for x in results)==1
    challenge=next(x for x in results if x!='CONFLICT')
    assert challenge.revision.code_hash==rev.code_hash
    assert challenge.revision.turn_generation==rev.turn_generation+1
    conn=repo._connect()
    try:
        assert conn.execute('SELECT count(*) FROM challenges').fetchone()[0]==1
        assert conn.execute('SELECT count(*) FROM turns').fetchone()[0]==1
    finally:conn.close()


def test_confirmation_cas_accepts_exactly_one_request(session):
    repo,sid,machine=session
    c=machine.issue_challenge(sid,purpose=ChallengePurpose.DIAGNOSTIC,expected_revision=machine.build_revision_ref(sid))
    results=run_twice(lambda:repo.reveal_challenge(sid,str(c.challenge_id),expected_revision=c.revision))
    assert sum(x=='CONFLICT' for x in results)==1


def test_old_trace_retains_original_spec_after_domain_switch(session):
    repo,sid,machine=session
    c=machine.issue_challenge(sid,purpose=ChallengePurpose.DIAGNOSTIC,expected_revision=machine.build_revision_ref(sid))
    repo.reveal_challenge(sid,str(c.challenge_id),expected_revision=c.revision)
    trace=str(uuid4())
    repo.save_trace_report(trace_id=trace,session_id=sid,code_version_id=c.revision.code_version_id,
        turn_generation=c.revision.turn_generation,case_hash=c.case_hash,status='COMPLETED',
        total_observed=0,trace_truncated=False,termination_reason='trusted protocol fixture',
        runtime_version='fixture',steps_json='[]',revision=c.revision,challenge_id=str(c.challenge_id))
    repo.update_spec(sid,spec_version='v2_negatives_allowed',expected_code_version_id=c.revision.code_version_id)
    assert repo.get_trace_report(sid,trace)['revision']==c.revision.model_dump(mode='json')


def test_old_client_sequence_rejected_even_with_current_code_version(session):
    repo,sid,machine=session;rev=machine.build_revision_ref(sid)
    cv=repo.get_code_version(sid,rev.code_version_id)
    repo.save_code_version(sid,expected_code_version_id=rev.code_version_id,source_code=cv.source_code,
        code_hash=cv.code_hash,client_edit_sequence=2)
    with pytest.raises(RevisionConflictError):
        repo.save_code_version(sid,expected_code_version_id=rev.code_version_id,source_code=cv.source_code,
            code_hash=cv.code_hash,client_edit_sequence=1)


def test_cancel_is_persisted_and_late_job_completion_rejected(session):
    repo,sid,machine=session
    c=machine.issue_challenge(sid,purpose=ChallengePurpose.DIAGNOSTIC,expected_revision=machine.build_revision_ref(sid))
    job=str(uuid4());repo.register_execution_job(sid,job,'EXECUTE',c.revision,str(c.challenge_id))
    class Broker:
        def cancel(self,jid):return str(jid)==job
    machine.worker_client=Broker()
    result=machine.cancel_active_work(sid)
    assert result=={'cancelled_job_ids':[job],'unconfirmed_job_ids':[]}
    with pytest.raises(RevisionConflictError):repo.finish_execution_job(sid,job,'COMPLETE')
    with pytest.raises(RevisionConflictError):repo.register_execution_job(sid,str(uuid4()),'VERIFY',c.revision,str(c.challenge_id))


def test_delete_tombstones_before_remote_cancel_and_reports_failure_honestly(session):
    repo,sid,machine=session
    c=machine.issue_challenge(sid,purpose=ChallengePurpose.DIAGNOSTIC,expected_revision=machine.build_revision_ref(sid))
    job=str(uuid4());repo.register_execution_job(sid,job,'EXECUTE',c.revision,str(c.challenge_id))
    class Broker:
        def cancel(self,jid):
            assert repo.get_session(sid,include_deleted=True).deleted_at is not None
            return False
    machine.worker_client=Broker()
    result=machine.cancel_active_work(sid,tombstone=True)
    assert result=={'cancelled_job_ids':[],'unconfirmed_job_ids':[job]}
    with pytest.raises(SessionDeletedError):repo.finish_execution_job(sid,job,'COMPLETE')


def test_worker_transport_failure_is_unavailable_not_a_wrong_prediction(session):
    from backend.app.orchestration.worker_client import BrokerCommunicationError
    from backend.app.models.domain import OutputPredictionClaim
    from backend.app.models.enums import ClaimPolarity, ExtractionMethod
    repo,sid,machine=session
    c=machine.issue_challenge(sid,purpose=ChallengePurpose.DIAGNOSTIC,expected_revision=machine.build_revision_ref(sid))
    class OfflineBroker:
        def submit_execution(self, req):raise BrokerCommunicationError('network unavailable')
    machine.worker_client=OfflineBroker()
    claim=OutputPredictionClaim(challenge_id=c.challenge_id,predicted_output=0,
        reason_summary='trusted fixture',polarity=ClaimPolarity.AFFIRMATIVE,
        extraction_method=ExtractionMethod.USER_EDITED,confirmed_at=datetime.now(timezone.utc))
    result=machine.confirm_claim_and_execute(sid,turn_id=None,challenge_id=c.challenge_id,
        expected_revision=c.revision,claim=claim)
    assert result['artifact']['prediction_status']=='NOT_EVALUATED'
    assert result['artifact']['verification_report']['status']=='EXECUTION_UNAVAILABLE'
