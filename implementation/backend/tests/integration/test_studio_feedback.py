import json
import uuid
from fastapi.testclient import TestClient
from backend.app.core.config import Settings
from backend.app.main import create_app


def test_model_fabricated_citation_abstains(tmp_path,monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'choices':[{'message':{'content':json.dumps({'question':'What next?','uncertainty':'Not verified','criteria':[{'dimension':d,'status':'observed_signal','evidence_ids':['invented']} for d in ('algorithm_correctness','architecture_reasoning','codebase_comprehension','technical_communication')]})}}]}
    class Client:
        def __init__(self,*args,**kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def post(self,*args,**kwargs): return Response()
    monkeypatch.setattr('backend.app.studio.feedback.httpx.AsyncClient',Client)
    settings=Settings(database_path=tmp_path/'test.db',tts_cache_dir=tmp_path/'audio',env='test',groq_api_key='valid-test-key-123456',llm_model='test-model')
    with TestClient(create_app(settings)) as c:
        wid,sid=str(uuid.uuid4()),str(uuid.uuid4()); wk,sk='w'*48,'s'*48
        c.post('/api/v1/studio/workspaces',json={'workspace_id':wid,'workspace_token':wk},headers={'X-Idempotency-Key':'workspace1'})
        c.post('/api/v1/studio/sessions',json={'workspace_id':wid,'session_id':sid,'session_token':sk,'mode':'dsa_to_system_bridge','posture':'teaching','scenario_id':'SD-BR-01'},headers={'Authorization':'Bearer '+wk,'X-Idempotency-Key':'sessionkey1'})
        h={'Authorization':'Bearer '+sk}
        t=c.post(f'/api/v1/studio/sessions/{sid}/turns',json={'epoch':1,'text':'reason'},headers={**h,'X-Idempotency-Key':'turnkey12'}).json()
        result=c.post(f'/api/v1/studio/sessions/{sid}/feedback',json={'epoch':1,'turn_id':t['turn_id'],'allow_external':True},headers={**h,'X-Idempotency-Key':'feedback1'})
        assert result.status_code==200,result.text
        assert result.json()['status']=='abstained_insufficient_signal'
        assert result.json()['evidence_turn_ids']==[t['turn_id']]


def test_interrupt_between_registration_and_dispatch_blocks_external_request(tmp_path,monkeypatch):
    import backend.app.studio.speech as speech
    from backend.app.db.migrations import open_connection
    calls=[]; original=speech.register_task
    def race(sid,epoch):
        entry=original(sid,epoch)
        with open_connection(tmp_path/'test.db') as db: db.execute('UPDATE studio_sessions SET epoch=epoch+1 WHERE id=?',(sid,))
        return entry
    class Client:
        def __init__(self,*args,**kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def post(self,*args,**kwargs): calls.append(True); raise AssertionError('stale context dispatched')
    monkeypatch.setattr(speech,'register_task',race)
    monkeypatch.setattr('backend.app.studio.feedback.httpx.AsyncClient',Client)
    settings=Settings(database_path=tmp_path/'test.db',tts_cache_dir=tmp_path/'audio',env='test',groq_api_key='valid-test-key-123456',llm_model='test-model')
    with TestClient(create_app(settings)) as c:
        wid,sid=str(uuid.uuid4()),str(uuid.uuid4()); wk,sk='w'*48,'s'*48
        c.post('/api/v1/studio/workspaces',json={'workspace_id':wid,'workspace_token':wk},headers={'X-Idempotency-Key':'workspace2'})
        c.post('/api/v1/studio/sessions',json={'workspace_id':wid,'session_id':sid,'session_token':sk,'mode':'dsa_to_system_bridge','posture':'teaching','scenario_id':'SD-BR-01'},headers={'Authorization':'Bearer '+wk,'X-Idempotency-Key':'sessionkey2'})
        h={'Authorization':'Bearer '+sk}
        t=c.post(f'/api/v1/studio/sessions/{sid}/turns',json={'epoch':1,'text':'reason'},headers={**h,'X-Idempotency-Key':'turnkey22'}).json()
        response=c.post(f'/api/v1/studio/sessions/{sid}/feedback',json={'epoch':1,'turn_id':t['turn_id'],'allow_external':True},headers={**h,'X-Idempotency-Key':'feedback2'})
        assert response.status_code==409 and calls==[]
