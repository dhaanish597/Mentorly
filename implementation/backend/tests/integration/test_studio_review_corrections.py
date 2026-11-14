"""Independent-review regressions: provenance, corrected phase evidence, leases."""
import asyncio
from contextlib import closing
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from backend.app.db.migrations import open_connection
from backend.app.studio.routes import event
from backend.app.studio.speech import NeutralAdapter
from backend.tests.integration.test_studio_corrections import candidate, studio, submit


@pytest.mark.parametrize('field', ['question','uncertainty'])
def test_invisible_format_characters_do_not_bypass_forbidden_claims(field):
    from backend.app.studio.feedback import validate_candidate
    prose='As a cert​ified strong​ hire, what would you build next?'
    value=candidate(**{field:prose})
    with pytest.raises(ValueError,match='Unsafe or unsupported claim'):
        validate_candidate(value,{'turn'},3,set())


def test_prose_validation_does_not_rewrite_original_text():
    from backend.app.studio.feedback import validate_candidate
    prose='What trade​off would you measure?'
    value=candidate(question=prose)
    assert validate_candidate(value,{'turn'},3,set()).question==prose


@pytest.mark.parametrize('operation', ['delete','retention'])
def test_workspace_cleanup_cancels_live_import_after_commit(tmp_path, monkeypatch, operation):
    import threading
    from backend.app.repo_learning import lifecycle
    from backend.app.studio.retention import sweep
    entered=threading.Event(); cancelled=threading.Event(); calls=[]
    original=lifecycle.cancel_workspace
    with studio(tmp_path) as (c, settings, wid, _, _):
        async def importing():
            lifecycle.register(settings.database_path,'live-snapshot',wid)
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
                lifecycle.unregister(settings.database_path,'live-snapshot')
        def checked_cancel(database_path,workspace_id):
            with closing(open_connection(database_path)) as db:
                db.execute('PRAGMA busy_timeout=25')
                db.execute('BEGIN IMMEDIATE')
                assert db.execute('SELECT deleted_at FROM studio_workspaces WHERE id=?',(workspace_id,)).fetchone()[0] is not None
                db.rollback()
            calls.append((str(database_path),workspace_id))
            original(database_path,workspace_id)
        monkeypatch.setattr(lifecycle,'cancel_workspace',checked_cancel)
        pending=c.portal.start_task_soon(importing)
        assert entered.wait(1)
        try:
            if operation=='delete':
                response=c.delete(f'/api/v1/studio/workspaces/{wid}',headers={'Authorization':'Bearer '+'w'*48,'X-Idempotency-Key':'delete-live-import'})
                assert response.status_code==200
            else:
                with closing(open_connection(settings.database_path)) as db:
                    db.execute("UPDATE studio_workspaces SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",(wid,))
                sweep(settings.database_path)
            assert calls==[(str(settings.database_path),wid)]
            assert cancelled.wait(1), 'Workspace cleanup must cancel the existing import task'
        finally:
            original(settings.database_path,wid)
            pending.cancel()


@pytest.mark.parametrize('operation', ['delete','retention'])
def test_workspace_cleanup_cancels_actual_mocked_public_fetch(tmp_path, monkeypatch, operation):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    import backend.app.repo_learning.routes as repository_routes
    from backend.app.repo_learning import lifecycle
    from backend.app.studio.retention import sweep
    entered=threading.Event(); closed=threading.Event()
    async def fetch(locator):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()
    monkeypatch.setattr(repository_routes,'fetch_public_archive',fetch)
    with studio(tmp_path) as (c, settings, wid, _, _):
        headers={'X-Workspace-Id':wid,'X-Workspace-Token':'w'*48,'X-Idempotency-Key':'mocked-public-import'}
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(c.post,'/api/v1/repos/ingest',
                                json={'source_kind':'public_git_url','source_locator':'https://github.com/example/repository'},
                                headers=headers)
            try:
                assert entered.wait(2), 'Actual repository route must enter mocked public fetch'
                if operation=='delete':
                    response=c.delete(f'/api/v1/studio/workspaces/{wid}',headers={'Authorization':'Bearer '+'w'*48,'X-Idempotency-Key':'delete-public-fetch'})
                    assert response.status_code==200
                else:
                    with closing(open_connection(settings.database_path)) as db:
                        db.execute("UPDATE studio_workspaces SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",(wid,))
                    sweep(settings.database_path)
                assert closed.wait(1), 'Deletion/expiry must immediately cancel the mocked public fetch'
                assert pending.result(timeout=2).status_code==202
                assert lifecycle.active_imports(settings.database_path)==[]
                with closing(open_connection(settings.database_path)) as db:
                    assert db.execute('SELECT count(*) FROM repo_snapshots WHERE workspace_id=?',(wid,)).fetchone()[0]==0
            finally:
                lifecycle.cancel_workspace(settings.database_path,wid)


def test_failed_workspace_cleanup_does_not_cancel_import(tmp_path, monkeypatch):
    from backend.app.repo_learning import lifecycle
    import backend.app.studio.routes as routes
    calls=[]
    monkeypatch.setattr(lifecycle,'cancel_workspace',lambda *args:calls.append(args))
    def fail(*args): raise RuntimeError('synthetic transaction failure')
    monkeypatch.setattr(routes,'purge_speech_usage',fail)
    with studio(tmp_path) as (c, settings, wid, _, _):
        with pytest.raises(RuntimeError,match='synthetic transaction failure'):
            c.delete(f'/api/v1/studio/workspaces/{wid}',headers={'Authorization':'Bearer '+'w'*48,'X-Idempotency-Key':'failed-delete-import'})
        assert calls==[]
        with closing(open_connection(settings.database_path)) as db:
            assert db.execute('SELECT deleted_at FROM studio_workspaces WHERE id=?',(wid,)).fetchone()[0] is None


@pytest.mark.parametrize('missing', ['diagram_revision','constraint_index'])
def test_missing_feedback_provenance_abstains_after_graph_or_stage_edit(tmp_path, missing):
    with studio(tmp_path) as (c, settings, _, sid, h):
        path=f'/api/v1/studio/sessions/{sid}'
        turns=[submit(c,path,h,key=f'provenance-turn-{i}') for i in range(3)]
        value={**candidate().model_dump(),'epoch':1,'turn_id':turns[-1]['turn_id'],
               'diagram_revision':0,'constraint_index':0}
        payload={key:value for key,value in value.items() if key!=missing}
        payload={**payload,'criteria':[{'dimension':'technical_communication','status':'observed_signal',
                                       'evidence_ids':[t['turn_id'] for t in turns]}]}
        with closing(open_connection(settings.database_path)) as db:
            event(db,sid,'feedback.ready',payload)
        if missing=='diagram_revision':
            response=c.put(path+'/diagram',json={'base_revision':0,'nodes':[],'edges':[], 'assumptions':{}},
                           headers={**h,'X-Idempotency-Key':'edit-provenance'})
        else:
            response=c.post(path+'/coach',json={'action':'skip'},headers={**h,'X-Idempotency-Key':'skip-provenance'})
        assert response.status_code==200
        summary=c.get(path+'/summary',headers=h).json()
        assert all(d['status']=='abstained_insufficient_signal' for d in summary['dimensions'])


def test_corrected_teachback_and_transfer_keep_recorded_phase_positions(tmp_path):
    with studio(tmp_path) as (c, settings, _, sid, h):
        path=f'/api/v1/studio/sessions/{sid}'
        with closing(open_connection(settings.database_path)) as db:
            db.execute('UPDATE studio_sessions SET constraint_index=3 WHERE id=?',(sid,))
        c.post(path+'/coach',json={'action':'teachback'},headers={**h,'X-Idempotency-Key':'teachback-chain'})
        restatement=submit(c,path,h,key='restatement-chain')
        c.post(path+'/coach',json={'action':'transfer'},headers={**h,'X-Idempotency-Key':'transfer-chain'})
        transfer=submit(c,path,h,key='transfer-response-chain')
        epoch=1
        latest_transfer=None
        for original in (restatement,transfer):
            response=c.post(path+'/turns/'+original['turn_id']+'/correction',
                            json={'epoch':epoch,'base_revision':1,'text':'corrected response'},
                            headers={**h,'X-Idempotency-Key':'correct-'+original['turn_id']})
            assert response.status_code==200
            corrected=response.json(); epoch=corrected['epoch']
            if original==transfer:
                latest_transfer=c.post(path+'/turns/'+corrected['turn_id']+'/correction',
                                       json={'epoch':epoch,'base_revision':2,'text':'second correction'},
                                       headers={**h,'X-Idempotency-Key':'second-transfer-correction'}).json()
                epoch=latest_transfer['epoch']
        finished=c.post(path+'/coach',json={'action':'finish'},headers={**h,'X-Idempotency-Key':'finish-corrected-chain'})
        assert finished.status_code==200, finished.text
        assert finished.json()['epoch']==epoch+1
        with closing(open_connection(settings.database_path)) as db:
            card=db.execute('SELECT evidence_json FROM studio_review_cards WHERE session_id=?',(sid,)).fetchone()
            assert latest_transfer['turn_id'] in card['evidence_json']
            assert transfer['turn_id'] not in card['evidence_json']


@pytest.mark.parametrize('operation', ['stt','tts'])
def test_total_provider_deadline_cancels_trickle_before_releasing_slot(tmp_path, monkeypatch, operation):
    import base64
    import threading
    import backend.app.studio.speech as speech
    from backend.app.speech.audio_utils import generate_sine_wav_bytes
    closed=threading.Event()
    active_during_close=[]
    gate=None
    async def trickle(self,*args,**kwargs):
        try:
            for _ in range(100):
                await asyncio.sleep(0.01)
            return SimpleNamespace(wav_bytes=b'wav',raw_transcript='late',normalized_transcript='late')
        finally:
            active_during_close.append(gate.get_capacity_status().active_requests)
            closed.set()
    monkeypatch.setattr(NeutralAdapter,'transcribe_rest',trickle)
    monkeypatch.setattr(NeutralAdapter,'synthesize_tts',trickle)
    monkeypatch.setattr(speech,'PROVIDER_DEADLINE_SECONDS',0.04,raising=False)
    with studio(tmp_path) as (c, settings, _, sid, h):
        settings.gnani_api_key=SecretStr('valid-mocked-key-123456')
        gate=c.app.state.speech.gatekeeper
        path=f'/api/v1/studio/sessions/{sid}'
        body={'epoch':1,'audio_base64':base64.b64encode(generate_sine_wav_bytes()).decode()}
        if operation=='tts':
            c.post(path+'/coach',json={'action':'clarify'},headers={**h,'X-Idempotency-Key':'deadline-clarify'})
            sequence=c.get(path,headers=h).json()['events'][-1]['sequence']
            body={'epoch':1,'event_sequence':sequence}
        response=c.post(path+'/speech/'+operation,json=body,headers={**h,'X-Idempotency-Key':'trickle-deadline'})
        assert response.status_code==502, response.text
        assert closed.is_set() and active_during_close==[1]
        assert gate.get_capacity_status().active_requests==0
        with closing(open_connection(settings.database_path)) as db:
            assert db.execute('SELECT status FROM studio_speech_usage').fetchone()[0]=='UNCERTAIN'
