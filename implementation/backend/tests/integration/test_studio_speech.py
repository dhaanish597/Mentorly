import base64
import uuid
from types import SimpleNamespace
from fastapi.testclient import TestClient
from backend.app.core.config import Settings
from backend.app.db.migrations import open_connection
from backend.app.main import create_app
from backend.app.speech.audio_utils import generate_sine_wav_bytes
from backend.app.studio.speech import NeutralAdapter


def test_studio_stt_mock_reserves_and_rejects_replay(tmp_path,monkeypatch):
    async def fake(self,req,audio):
        return SimpleNamespace(raw_transcript='hello',normalized_transcript='hello')
    monkeypatch.setattr(NeutralAdapter,'transcribe_rest',fake)
    settings=Settings(database_path=tmp_path/'test.db',tts_cache_dir=tmp_path/'audio',env='test',gnani_api_key='test-valid-key-123456')
    with TestClient(create_app(settings)) as c:
        wid,sid=str(uuid.uuid4()),str(uuid.uuid4()); wk,sk='w'*48,'s'*48
        c.post('/api/v1/studio/workspaces',json={'workspace_id':wid,'workspace_token':wk},headers={'X-Idempotency-Key':'workspace1'})
        c.post('/api/v1/studio/sessions',json={'workspace_id':wid,'session_id':sid,'session_token':sk,'mode':'dsa_to_system_bridge','posture':'teaching','scenario_id':'SD-BR-01'},headers={'Authorization':'Bearer '+wk,'X-Idempotency-Key':'sessionkey1'})
        body={'epoch':1,'audio_base64':base64.b64encode(generate_sine_wav_bytes()).decode(),'language_mode':'en-IN'}
        h={'Authorization':'Bearer '+sk,'X-Idempotency-Key':'speechkey1'}
        assert c.post(f'/api/v1/studio/sessions/{sid}/speech/stt',json=body,headers={'Authorization':'Bearer invalid','X-Idempotency-Key':'badtoken1'}).status_code==401
        r=c.post(f'/api/v1/studio/sessions/{sid}/speech/stt',json=body,headers=h)
        assert r.status_code==200,r.text
        assert r.json()['requires_confirmation'] is True
        assert c.post(f'/api/v1/studio/sessions/{sid}/speech/stt',json=body,headers=h).status_code==409
        with open_connection(tmp_path/'test.db') as db:
            assert db.execute('SELECT status FROM studio_speech_usage').fetchone()[0]=='COMMITTED'
            assert db.execute('SELECT count(*) FROM sessions').fetchone()[0]==0


def test_stale_response_charged_and_daily_limit(tmp_path,monkeypatch):
    settings=Settings(database_path=tmp_path/'test.db',tts_cache_dir=tmp_path/'audio',env='test',gnani_api_key='test-valid-key-123456',global_daily_call_limit=1)
    async def fake(self,req,audio):
        with open_connection(settings.database_path) as db:
            db.execute('UPDATE studio_sessions SET epoch=epoch+1 WHERE id=?',(req.session_id,))
        return SimpleNamespace(raw_transcript='late',normalized_transcript='late')
    monkeypatch.setattr(NeutralAdapter,'transcribe_rest',fake)
    with TestClient(create_app(settings)) as c:
        wid,sid=str(uuid.uuid4()),str(uuid.uuid4()); wk,sk='w'*48,'s'*48
        c.post('/api/v1/studio/workspaces',json={'workspace_id':wid,'workspace_token':wk},headers={'X-Idempotency-Key':'workspace2'})
        c.post('/api/v1/studio/sessions',json={'workspace_id':wid,'session_id':sid,'session_token':sk,'mode':'dsa_to_system_bridge','posture':'teaching','scenario_id':'SD-BR-01'},headers={'Authorization':'Bearer '+wk,'X-Idempotency-Key':'sessionkey2'})
        body={'epoch':1,'audio_base64':base64.b64encode(generate_sine_wav_bytes()).decode(),'language_mode':'en-IN'}
        h={'Authorization':'Bearer '+sk,'X-Idempotency-Key':'speechkey2'}
        assert c.post(f'/api/v1/studio/sessions/{sid}/speech/stt',json=body,headers=h).status_code==409
        with open_connection(tmp_path/'test.db') as db:
            assert db.execute('SELECT status FROM studio_speech_usage').fetchone()[0]=='COMMITTED'
        body['epoch']=2
        assert c.post(f'/api/v1/studio/sessions/{sid}/speech/stt',json=body,headers={**h,'X-Idempotency-Key':'speechkey3'}).status_code==429


def test_tts_uses_only_stored_coach_text(tmp_path,monkeypatch):
    seen=[]
    async def fake(self,req,**kwargs):
        seen.append(req.text); return SimpleNamespace(wav_bytes=b'wav')
    monkeypatch.setattr(NeutralAdapter,'synthesize_tts',fake)
    settings=Settings(database_path=tmp_path/'test.db',tts_cache_dir=tmp_path/'audio',env='test',gnani_api_key='test-valid-key-123456')
    with TestClient(create_app(settings)) as c:
        wid,sid=str(uuid.uuid4()),str(uuid.uuid4()); wk,sk='w'*48,'s'*48
        c.post('/api/v1/studio/workspaces',json={'workspace_id':wid,'workspace_token':wk},headers={'X-Idempotency-Key':'workspace3'})
        c.post('/api/v1/studio/sessions',json={'workspace_id':wid,'session_id':sid,'session_token':sk,'mode':'dsa_to_system_bridge','posture':'teaching','scenario_id':'SD-BR-01'},headers={'Authorization':'Bearer '+wk,'X-Idempotency-Key':'sessionkey3'})
        h={'Authorization':'Bearer '+sk}
        action=c.post(f'/api/v1/studio/sessions/{sid}/coach',json={'action':'hint'},headers={**h,'X-Idempotency-Key':'coachkey3'}).json()
        snap=c.get(f'/api/v1/studio/sessions/{sid}',headers=h).json()
        seq=snap['events'][-1]['sequence']
        r=c.post(f'/api/v1/studio/sessions/{sid}/speech/tts',json={'epoch':1,'event_sequence':seq},headers={**h,'X-Idempotency-Key':'ttskey123'})
        assert r.status_code==200,r.text
        assert seen==[action['text']]
        assert c.post(f'/api/v1/studio/sessions/{sid}/speech/tts',json={'epoch':1,'event_sequence':999},headers={**h,'X-Idempotency-Key':'ttskey456'}).status_code==404


def test_interrupt_cancels_inflight_provider_and_charges_uncertain(tmp_path,monkeypatch):
    import asyncio, threading
    from concurrent.futures import ThreadPoolExecutor
    entered=threading.Event(); cancelled=threading.Event()
    async def fake(self,req,audio):
        entered.set()
        try: await asyncio.sleep(20)
        except asyncio.CancelledError:
            cancelled.set(); raise
    monkeypatch.setattr(NeutralAdapter,'transcribe_rest',fake)
    settings=Settings(database_path=tmp_path/'test.db',tts_cache_dir=tmp_path/'audio',env='test',gnani_api_key='test-valid-key-123456')
    with TestClient(create_app(settings),raise_server_exceptions=False) as c:
        wid,sid=str(uuid.uuid4()),str(uuid.uuid4()); wk,sk='w'*48,'s'*48
        c.post('/api/v1/studio/workspaces',json={'workspace_id':wid,'workspace_token':wk},headers={'X-Idempotency-Key':'workspace4'})
        c.post('/api/v1/studio/sessions',json={'workspace_id':wid,'session_id':sid,'session_token':sk,'mode':'dsa_to_system_bridge','posture':'teaching','scenario_id':'SD-BR-01'},headers={'Authorization':'Bearer '+wk,'X-Idempotency-Key':'sessionkey4'})
        h={'Authorization':'Bearer '+sk}
        body={'epoch':1,'audio_base64':base64.b64encode(generate_sine_wav_bytes()).decode(),'language_mode':'en-IN'}
        with ThreadPoolExecutor() as pool:
            pending=pool.submit(c.post,f'/api/v1/studio/sessions/{sid}/speech/stt',json=body,headers={**h,'X-Idempotency-Key':'speechkey4'})
            assert entered.wait(3)
            response=c.post(f'/api/v1/studio/sessions/{sid}/interrupt',json={'expected_epoch':1},headers={**h,'X-Idempotency-Key':'interrupt4'})
            assert response.status_code==200
            assert pending.result(timeout=3).status_code==409
            assert cancelled.wait(3)
        with open_connection(tmp_path/'test.db') as db:
            assert db.execute('SELECT status FROM studio_speech_usage').fetchone()[0]=='UNCERTAIN'


def test_replayed_old_interrupt_does_not_cancel_new_epoch(tmp_path,monkeypatch):
    import asyncio, threading
    from concurrent.futures import ThreadPoolExecutor
    entered=threading.Event(); release=threading.Event(); cancelled=threading.Event()
    async def fake(self,req,audio):
        entered.set()
        try:
            while not release.is_set(): await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            cancelled.set(); raise
        return SimpleNamespace(raw_transcript='valid',normalized_transcript='valid')
    monkeypatch.setattr(NeutralAdapter,'transcribe_rest',fake)
    settings=Settings(database_path=tmp_path/'test.db',tts_cache_dir=tmp_path/'audio',env='test',gnani_api_key='test-valid-key-123456')
    with TestClient(create_app(settings),raise_server_exceptions=False) as c:
        wid,sid=str(uuid.uuid4()),str(uuid.uuid4()); wk,sk='w'*48,'s'*48
        c.post('/api/v1/studio/workspaces',json={'workspace_id':wid,'workspace_token':wk},headers={'X-Idempotency-Key':'workspaceretry'})
        c.post('/api/v1/studio/sessions',json={'workspace_id':wid,'session_id':sid,'session_token':sk,'mode':'dsa_to_system_bridge','posture':'teaching','scenario_id':'SD-BR-01'},headers={'Authorization':'Bearer '+wk,'X-Idempotency-Key':'sessionretry'})
        h={'Authorization':'Bearer '+sk}; interrupt_headers={**h,'X-Idempotency-Key':'interruptretry'}
        interrupt_body={'expected_epoch':1}
        assert c.post(f'/api/v1/studio/sessions/{sid}/interrupt',json=interrupt_body,headers=interrupt_headers).json()['epoch']==2
        body={'epoch':2,'audio_base64':base64.b64encode(generate_sine_wav_bytes()).decode(),'language_mode':'en-IN'}
        with ThreadPoolExecutor() as pool:
            pending=pool.submit(c.post,f'/api/v1/studio/sessions/{sid}/speech/stt',json=body,headers={**h,'X-Idempotency-Key':'new-epoch-speech'})
            try:
                assert entered.wait(3)
                assert c.post(f'/api/v1/studio/sessions/{sid}/interrupt',json=interrupt_body,headers=interrupt_headers).json()['epoch']==2
                assert not cancelled.wait(0.2)
            finally: release.set()
            assert pending.result(timeout=3).status_code==200
