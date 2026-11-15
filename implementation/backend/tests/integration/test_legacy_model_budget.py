"""The legacy extraction/phrasing adapters share durable model limits."""
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.coaching.claim_extractor import ModelAssistedClaimExtractor
from backend.app.coaching.coach_engine import CoachEngine
from backend.app.coaching.model_budget import daily_count
from backend.app.core.config import Settings
from backend.app.db.migrations import open_connection
from backend.app.db.repository import RevisionConflictError
from backend.app.main import create_app
from backend.app.models.domain import EvidenceArtifact, ExecutionObservation, RevisionRef, VerificationReport
from backend.app.models.enums import LearningState


@pytest.fixture
def learner(tmp_path):
    settings=Settings(_env_file=None,database_url=None,env='test',database_path=tmp_path/'legacy.db',tts_cache_dir=tmp_path/'cache',
                      gnani_api_key=None,groq_api_key='mock-model-account',llm_model='mock-model')
    with TestClient(create_app(settings)) as client:
        response=client.post('/api/v1/sessions',json={'exercise_id':'ex1_shortest_subarray','spec_version':'v1_positive_only'})
        assert response.status_code == 200, response.text
        data=response.json()
        yield settings,client,data,RevisionRef.model_validate(data['revision'])


class ModelClient:
    def __init__(self, content=None, error=None, after=None, status=200):
        self.content=content; self.error=error; self.after=after; self.status=status; self.calls=0
    def post(self,url,**kwargs):
        self.calls+=1
        if self.error: raise self.error
        if self.after: self.after()
        return httpx.Response(self.status,request=httpx.Request('POST',url),
                              json={'choices':[{'message':{'content':self.content}}]})


@pytest.mark.parametrize('content,error,status,expected',[
    (json.dumps({'claim_type':'INVARIANT_OR_MECHANISM_CLAIM','mechanism_summary':'Maintain a prefix sum.',
                 'extraction_method':'MODEL_ASSISTED'}),None,200,'MODEL_ASSISTED'),
    ('invalid',None,200,'MODEL_INVALID_RESPONSE'),
    ('{}',None,429,'MODEL_RATE_LIMITED'),
    (None,httpx.ReadTimeout('private-model-error'),200,'MODEL_TIMEOUT'),
])
def test_extraction_has_honest_status_and_conservative_spend(learner,content,error,status,expected):
    settings,_,data,revision=learner
    fake=ModelClient(content,error,status=status)
    extractor=ModelAssistedClaimExtractor(api_key='mock-model-account',model='mock-model',http_client=fake,settings=settings)
    claim=extractor.extract('Maintain a prefix sum.',session_id=data['session_id'],revision=revision)
    assert claim.model_status == expected and claim.confirmed_at is None
    assert 'private-model-error' not in claim.model_dump_json()
    with open_connection(settings.database_path) as db:
        row=db.execute('SELECT operation,status FROM legacy_model_usage').fetchone()
        assert row['operation']=='claim_extraction'
        assert row['status']==('UNCERTAIN' if expected=='MODEL_TIMEOUT' else 'COMMITTED')
        assert daily_count(db,'2099-01-01T00:00:00+00:00')==0


def test_legacy_usage_blocks_other_legacy_operations_at_shared_limit(learner):
    settings,_,data,revision=learner; settings.model_daily_call_limit=1
    fake=ModelClient('{}')
    extractor=ModelAssistedClaimExtractor(api_key='mock-model-account',model='mock-model',http_client=fake,settings=settings)
    assert extractor.extract('loop',session_id=data['session_id'],revision=revision).model_status=='MODEL_INVALID_RESPONSE'
    assert extractor.extract('loop',session_id=data['session_id'],revision=revision).model_status=='MODEL_RATE_LIMITED'
    assert fake.calls==1


def test_post_dispatch_revision_change_never_returns_stale_claim(learner):
    settings,_,data,revision=learner
    def edit():
        with open_connection(settings.database_path) as db:
            db.execute('UPDATE sessions SET active_turn_generation=active_turn_generation+1 WHERE id=?',(data['session_id'],))
    fake=ModelClient('{}',after=edit)
    extractor=ModelAssistedClaimExtractor(api_key='mock-model-account',model='mock-model',http_client=fake,settings=settings)
    with pytest.raises(RevisionConflictError): extractor.extract('loop',session_id=data['session_id'],revision=revision)
    with open_connection(settings.database_path) as db:
        assert db.execute('SELECT status FROM legacy_model_usage').fetchone()[0]=='COMMITTED'


def test_delete_keeps_anonymous_spend_and_removes_private_linkage(learner):
    from datetime import datetime,timezone
    settings,client,data,revision=learner
    extractor=ModelAssistedClaimExtractor(api_key='mock-model-account',model='mock-model',http_client=ModelClient('{}'),settings=settings)
    extractor.extract('loop',session_id=data['session_id'],revision=revision)
    response=client.delete('/api/v1/sessions/'+data['session_id'],headers={'Authorization':'Bearer '+data['session_token'],'X-Idempotency-Key':'delete-legacy-model-owner'})
    assert response.status_code==200,response.text
    with open_connection(settings.database_path) as db:
        assert db.execute('SELECT count(*) FROM legacy_model_usage').fetchone()[0]==0
        assert db.execute('SELECT sum(request_count) FROM legacy_model_deleted_daily').fetchone()[0]==1
        assert daily_count(db,datetime.now(timezone.utc).isoformat())==1


@pytest.mark.parametrize('content,error,expected', [('[]',None,'MODEL_INVALID_RESPONSE'),
    ('{"choice":1}',None,'MODEL_ASSISTED'), (None,httpx.ReadTimeout('private-error'),'MODEL_TIMEOUT')])
def test_coach_rephrasing_reports_status_and_cannot_invent_evidence(learner,content,error,expected):
    settings,_,_,revision=learner
    artifact=EvidenceArtifact(artifact_id=uuid4(),revision=revision,challenge_id=uuid4(),canonical_input={'nums':[1],'target':1},case_hash='a'*64,
        actual_observation=ExecutionObservation(kind='UNAVAILABLE',duration_ms=0,error_type='ExecutionUnavailable'),reference_output=1,prediction_status='NOT_EVALUATED',
        verification_report=VerificationReport(status='EXECUTION_UNAVAILABLE',curated_cases_run=0,curated_cases_total=1,
        generated_cases_run=0,generated_cases_target=0,terminal_reason='Protocol fixture: worker unavailable',runtime_version='protocol-fixture'))
    engine=CoachEngine(llm_api_key='mock-model-account',llm_model='mock-model',http_client=ModelClient(content,error),settings=settings)
    response=engine.build_coaching_turn_response(artifact=artifact,trace_report=None,learning_state=LearningState.EXPLAINING)
    assert response['model_status']==expected
    assert 'unavailable' in response['display_text'].lower()


def test_native_model_without_selected_settings_never_uses_ambient_credentials(monkeypatch):
    monkeypatch.setenv('VCC_GROQ_API_KEY','ambient-secret-must-not-be-used')
    monkeypatch.setenv('VCC_LLM_MODEL','ambient-model')
    extractor=ModelAssistedClaimExtractor()
    assert extractor.api_key=='' and extractor.model==''
    assert extractor.extract('loop').model_status=='MODEL_NOT_CONFIGURED'


def test_selected_disabled_settings_override_explicit_client_credentials(learner):
    settings,_,data,revision=learner; settings.llm_provider='deterministic'
    fake=ModelClient('{}')
    extractor=ModelAssistedClaimExtractor(api_key='other-account',model='other-model',http_client=fake,settings=settings)
    assert extractor.extract('loop',session_id=data['session_id'],revision=revision).model_status=='MODEL_DISABLED'
    assert fake.calls==0 and extractor.api_key==''
