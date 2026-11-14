"""Regression coverage for studio lifecycle, corrected transcripts and safe voice."""
import json
import uuid
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.db.migrations import open_connection
from backend.app.main import create_app
from backend.app.studio.feedback import DIMENSIONS, ModelFeedback, validate_candidate


@contextmanager
def studio(tmp_path, **options):
    settings = Settings(database_path=tmp_path/'studio.db', tts_cache_dir=tmp_path/'audio',
                        env='test', groq_api_key=None, gnani_api_key=None, **options)
    with TestClient(create_app(settings)) as client:
        wid, sid = str(uuid.uuid4()), str(uuid.uuid4())
        client.post('/api/v1/studio/workspaces', json={'workspace_id':wid,'workspace_token':'w'*48},
                    headers={'X-Idempotency-Key':'workspace-create'})
        created = client.post('/api/v1/studio/sessions', json={'workspace_id':wid,'session_id':sid,
                              'session_token':'s'*48,'mode':'dsa_to_system_bridge',
                              'posture':'teaching','scenario_id':'SD-BR-01'},
                              headers={'Authorization':'Bearer '+'w'*48,'X-Idempotency-Key':'session-create'})
        assert created.status_code == 200
        yield client, settings, wid, sid, {'Authorization':'Bearer '+'s'*48}


def submit(client, path, headers, text='My explanation', key='original-turn', epoch=1):
    response = client.post(path+'/turns', json={'epoch':epoch,'text':text},
                           headers={**headers,'X-Idempotency-Key':key})
    assert response.status_code == 200, response.text
    return response.json()


def candidate(question='What evidence would change your decision?', uncertainty='Not independently verified'):
    return ModelFeedback(question=question, uncertainty=uncertainty,
                         criteria=[{'dimension':d,'status':'abstained_insufficient_signal','evidence_ids':[]}
                                   for d in DIMENSIONS])


@pytest.mark.parametrize('claim', ['strong hire','senior level','certified','guaranteed pass',
                                   'strong-hire','senior-level','guaranteed to pass',
                                   'See backend/app/main.py:20', 'Read `src/cache.ts`',
                                   'Consult main.py', 'See /etc/passwd', 'strong\nhire',
                                   'senior\tlevel', 'strong‐hire', 'Main.PY',
                                   'Ｃｅｒｔｉｆｉｅｄ'])
def test_candidate_rejects_forbidden_claims_and_prose_file_citations(claim):
    with pytest.raises(ValueError):
        validate_candidate(candidate(uncertainty=claim), {'turn'}, 3, set())


def test_deterministic_provider_remains_stopped_even_with_key_and_consent(tmp_path, monkeypatch):
    calls = []
    async def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError('Provider explicitly stopped')
    monkeypatch.setattr('backend.app.studio.feedback.httpx.AsyncClient.post', forbidden)
    with studio(tmp_path, llm_provider='deterministic', llm_model='test-model') as (c, settings, _, sid, h):
        from pydantic import SecretStr
        settings.groq_api_key = SecretStr('valid-mocked-key-123456')
        path = f'/api/v1/studio/sessions/{sid}'
        turn = submit(c, path, h)
        response = c.post(path+'/feedback', json={'epoch':1,'turn_id':turn['turn_id'],'allow_external':True},
                          headers={**h,'X-Idempotency-Key':'feedback-stopped'})
        assert response.status_code == 200
        assert calls == []
        assert response.json()['source'] == 'deterministic_fallback'
        with open_connection(settings.database_path) as db:
            assert db.execute('SELECT count(*) FROM studio_model_usage').fetchone()[0] == 0


def test_model_context_uses_corrected_evidence_authored_facts_and_completion_summary(tmp_path, monkeypatch):
    from pydantic import SecretStr
    from backend.app.studio.scenario_content import get_content
    contexts = []
    class Response:
        def __init__(self, value): self.value = value
        def raise_for_status(self): pass
        def json(self): return {'choices':[{'message':{'content':json.dumps(self.value)}}]}
    class Client:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs):
            context = json.loads(kwargs['json']['messages'][-1]['content'])
            contexts.append(context)
            value = candidate().model_dump()
            value['criteria'] = [{**criterion,'status':'observed_signal',
                                  'evidence_ids':[t['id'] for t in context['turns']]}
                                 if criterion['dimension']=='technical_communication' else criterion
                                 for criterion in value['criteria']]
            return Response(value)
    monkeypatch.setattr('backend.app.studio.feedback.httpx.AsyncClient', Client)
    with studio(tmp_path, llm_model='mock-model') as (c, settings, _, sid, h):
        settings.groq_api_key = SecretStr('valid-mocked-key-123456')
        path = f'/api/v1/studio/sessions/{sid}'
        with open_connection(settings.database_path) as db:
            db.execute('UPDATE studio_sessions SET constraint_index=3 WHERE id=?', (sid,))
        original = submit(c, path, h, text='obsolete explanation')
        c.post(path+'/coach', json={'action':'teachback'}, headers={**h,'X-Idempotency-Key':'teachback-context'})
        submit(c, path, h, text='A restatement', key='restated-context')
        c.post(path+'/coach', json={'action':'transfer'}, headers={**h,'X-Idempotency-Key':'transfer-context'})
        transfer = submit(c, path, h, text='Transfer reasoning', key='transferred-context')
        fixed = c.post(path+'/turns/'+original['turn_id']+'/correction',
                       json={'epoch':1,'base_revision':1,'text':'corrected evidence','kind':'answer'},
                       headers={**h,'X-Idempotency-Key':'correct-model-context'}).json()
        response = c.post(path+'/feedback', json={'epoch':2,'turn_id':fixed['turn_id'],'allow_external':True},
                          headers={**h,'X-Idempotency-Key':'model-current-context'})
        assert response.status_code == 200 and response.json()['source']=='model_assisted'
        assert original['turn_id'] not in {t['id'] for t in contexts[0]['turns']}
        assert contexts[0]['scenario']['clarification_facts'] == get_content('SD-BR-01')['clarification_facts']
        finished = c.post(path+'/coach', json={'action':'finish'}, headers={**h,'X-Idempotency-Key':'finish-context'})
        assert finished.status_code == 200 and finished.json()['epoch']==3
        summary = c.get(path+'/summary', headers=h).json()
        signal = next(d for d in summary['dimensions'] if d['dimension']=='technical_communication')
        assert signal['status']=='observed_signal' and original['turn_id'] not in signal['evidence_ids']
        correction = c.post(path+'/turns/'+transfer['turn_id']+'/correction',
                            json={'epoch':3,'base_revision':1,'text':'changed transfer'},
                            headers={**h,'X-Idempotency-Key':'correct-completed-context'})
        assert correction.status_code == 200
        summary = c.get(path+'/summary', headers=h).json()
        assert all(d['status']=='abstained_insufficient_signal' for d in summary['dimensions'])
        with open_connection(settings.database_path) as db:
            assert db.execute('SELECT count(*) FROM studio_review_cards WHERE session_id=?', (sid,)).fetchone()[0]==0


@pytest.mark.parametrize('cleanup', ['session','workspace','retention'])
def test_model_cleanup_retains_only_anonymous_daily_spend(tmp_path, cleanup):
    from backend.app.studio.retention import sweep
    with studio(tmp_path) as (c, settings, wid, sid, h):
        with open_connection(settings.database_path) as db:
            db.execute("INSERT INTO studio_model_usage VALUES('request',?,1,'private-key','RESERVED',datetime('now'))", (sid,))
        if cleanup == 'session':
            assert c.delete(f'/api/v1/studio/sessions/{sid}', headers={**h,'X-Idempotency-Key':'delete-session'}).status_code == 200
        elif cleanup == 'workspace':
            assert c.delete(f'/api/v1/studio/workspaces/{wid}', headers={'Authorization':'Bearer '+'w'*48,
                            'X-Idempotency-Key':'delete-workspace'}).status_code == 200
        else:
            with open_connection(settings.database_path) as db:
                db.execute("UPDATE studio_sessions SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (sid,))
            sweep(settings.database_path)
            sweep(settings.database_path)
        with open_connection(settings.database_path) as db:
            assert db.execute('SELECT count(*) FROM studio_model_usage').fetchone()[0] == 0
            assert db.execute('SELECT request_count FROM studio_model_deleted_daily').fetchone()[0] == 1
            from backend.app.studio.model_budget import reserve
            from fastapi import HTTPException
            db.execute('BEGIN IMMEDIATE')
            with pytest.raises(HTTPException) as exhausted:
                reserve(db,sid,1,'new-admission',settings.model_copy(update={'model_daily_call_limit':1}))
            assert exhausted.value.status_code==429
            db.rollback()


def test_model_restart_recovers_reserved_without_redispatch(tmp_path):
    with studio(tmp_path) as (_, settings, _, sid, _):
        with open_connection(settings.database_path) as db:
            db.execute("INSERT INTO studio_model_usage VALUES('request',?,1,'private-key','RESERVED',datetime('now'))", (sid,))
    with TestClient(create_app(settings)):
        with open_connection(settings.database_path) as db:
            assert db.execute('SELECT status FROM studio_model_usage').fetchone()[0] == 'UNCERTAIN'
            from backend.app.studio.model_budget import reserve
            db.execute('BEGIN IMMEDIATE')
            assert reserve(db,sid,1,'post-restart-admission',settings)
            db.rollback()


def test_correction_fences_revisions_preserves_audit_and_survives_restart(tmp_path):
    with studio(tmp_path) as (c, settings, _, sid, h):
        path = f'/api/v1/studio/sessions/{sid}'
        original = submit(c, path, h, text='uncorrected')
        assert original['transcript_revision'] == 1
        body = {'epoch':1,'base_revision':1,'text':'corrected'}
        url = path+'/turns/'+original['turn_id']+'/correction'
        headers = {**h,'X-Idempotency-Key':'correct-transcript'}
        fixed = c.post(url, json=body, headers=headers)
        assert fixed.status_code == 200, fixed.text
        result = fixed.json()
        assert result['epoch'] == 2 and result['transcript_revision'] == 2
        assert c.post(url, json=body, headers=headers).json() == result
        assert c.post(url, json=body, headers={**h,'X-Idempotency-Key':'stale-correction'}).status_code == 409
        assert c.post(url, json={**body,'epoch':2}, headers={**h,'X-Idempotency-Key':'stale-revision'}).status_code == 409
        assert c.post(url, json=body, headers={'Authorization':'Bearer invalid','X-Idempotency-Key':'wrong-owner'}).status_code == 401
        snap = c.get(path, headers=h).json()
        old = next(t for t in snap['turns'] if t['id'] == original['turn_id'])
        assert old['content'] == 'uncorrected' and old['superseded_by'] == result['turn_id']
        assert c.get(path+'/summary', headers=h).json()['turn_count'] == 1
        assert c.post(path+'/feedback', json={'epoch':2,'turn_id':original['turn_id']},
                      headers={**h,'X-Idempotency-Key':'feedback-old-turn'}).status_code == 404
        latest = c.post(path+'/feedback', json={'epoch':2,'turn_id':result['turn_id']},
                        headers={**h,'X-Idempotency-Key':'feedback-new-turn'}).json()
        assert latest['evidence_turn_ids'] == [result['turn_id']]
    with TestClient(create_app(settings)) as c:
        assert c.post(url, json=body, headers=headers).json() == result
        assert len(c.get(path+'/export', headers=h).json()['turns']) == 2


def test_correction_atomic_cas_only_one_wins(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    with studio(tmp_path) as (c, _, _, sid, h):
        path = f'/api/v1/studio/sessions/{sid}'
        original = submit(c, path, h)
        def correct(i):
            return c.post(path+'/turns/'+original['turn_id']+'/correction',
                          json={'epoch':1,'base_revision':1,'text':str(i)},
                          headers={**h,'X-Idempotency-Key':f'correction-{i}'}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(correct, (1,2))) == [200,409]


def test_summary_preserves_valid_feedback_through_completion_not_correction(tmp_path):
    from backend.app.studio.routes import encode, event
    with studio(tmp_path) as (c, settings, _, sid, h):
        path = f'/api/v1/studio/sessions/{sid}'
        turns = [submit(c, path, h, key=f'learner-turn-{i}') for i in range(3)]
        with open_connection(settings.database_path) as db:
            event(db, sid, 'feedback.ready', {'turn_id':turns[-1]['turn_id'],'epoch':1,
                  'diagram_revision':0,'constraint_index':0,'criteria':[{'dimension':'technical_communication','status':'observed_signal',
                               'evidence_ids':[t['turn_id'] for t in turns]}]})
            db.execute("UPDATE studio_sessions SET state='completed',epoch=2 WHERE id=?", (sid,))
        summary = c.get(path+'/summary', headers=h).json()
        dimension = next(d for d in summary['dimensions'] if d['dimension'] == 'technical_communication')
        assert dimension['status'] == 'observed_signal'
        response = c.post(path+'/turns/'+turns[0]['turn_id']+'/correction',
                          json={'epoch':2,'base_revision':1,'text':'changed evidence'},
                          headers={**h,'X-Idempotency-Key':'completion-correction'})
        assert response.status_code == 200
        dimension = next(d for d in c.get(path+'/summary', headers=h).json()['dimensions']
                         if d['dimension'] == 'technical_communication')
        assert dimension['status'] == 'abstained_insufficient_signal'


def test_tts_speaks_validated_feedback_not_arbitrary_or_superseded_events(tmp_path, monkeypatch):
    from pydantic import SecretStr
    from types import SimpleNamespace
    from backend.app.studio.routes import event
    from backend.app.studio.speech import NeutralAdapter
    seen = []
    async def fake(self, req, **kwargs):
        seen.append(req.text)
        return SimpleNamespace(wav_bytes=b'wav')
    monkeypatch.setattr(NeutralAdapter, 'synthesize_tts', fake)
    with studio(tmp_path) as (c, settings, _, sid, h):
        settings.gnani_api_key = SecretStr('valid-mocked-key-123456')
        path = f'/api/v1/studio/sessions/{sid}'
        turn = submit(c, path, h)
        response = c.post(path+'/feedback', json={'epoch':1,'turn_id':turn['turn_id']},
                          headers={**h,'X-Idempotency-Key':'speak-feedback'})
        assert response.status_code == 200
        feedback = response.json()
        body = {'epoch':1,'event_sequence':feedback['event_sequence']}
        headers = {**h,'X-Idempotency-Key':'tts-feedback'}
        assert c.post(path+'/speech/tts', json=body,
                      headers={'Authorization':'Bearer invalid','X-Idempotency-Key':'tts-wrong-owner'}).status_code == 401
        spoken = c.post(path+'/speech/tts', json=body, headers=headers)
        assert spoken.status_code == 200, spoken.text
        assert seen == [feedback['question']]
        assert c.post(path+'/speech/tts', json=body, headers=headers).status_code == 409
        assert c.post(path+'/speech/tts', json={**body,'text':'arbitrary'},
                      headers={**h,'X-Idempotency-Key':'tts-arbitrary'}).status_code == 422
        with open_connection(settings.database_path) as db:
            forged = event(db, sid, 'feedback.ready', {'epoch':1,'turn_id':turn['turn_id'],
                          'question':'You are a certified strong hire?', 'criteria':[]})
        assert c.post(path+'/speech/tts', json={'epoch':1,'event_sequence':forged},
                      headers={**h,'X-Idempotency-Key':'tts-forged'}).status_code == 422
        with open_connection(settings.database_path) as db:
            unsafe=event(db,sid,'feedback.ready',{'epoch':1,'turn_id':turn['turn_id'],'validated':True,
                         'diagram_revision':0,'constraint_index':0,'source':'model_assisted',**candidate(uncertainty='certified strong hire').model_dump()})
        assert c.post(path+'/speech/tts',json={'epoch':1,'event_sequence':unsafe},
                      headers={**h,'X-Idempotency-Key':'tts-unsafe'}).status_code == 422
        assert c.post(path+'/speech/tts', json={'epoch':1,'event_sequence':1},
                      headers={**h,'X-Idempotency-Key':'tts-other-event'}).status_code == 404
        correction = c.post(path+'/turns/'+turn['turn_id']+'/correction',
                            json={'epoch':1,'base_revision':1,'text':'corrected'},
                            headers={**h,'X-Idempotency-Key':'tts-correction'})
        assert correction.status_code == 200
        assert c.post(path+'/speech/tts', json={**body,'epoch':2},
                      headers={**h,'X-Idempotency-Key':'tts-old-event'}).status_code == 409
        assert len(seen) == 1


@pytest.mark.parametrize('operation', ['stt','tts'])
def test_studio_speech_uses_shared_bounded_queue_and_times_out(tmp_path, monkeypatch, operation):
    import base64
    import time
    from concurrent.futures import ThreadPoolExecutor
    from pydantic import SecretStr
    from backend.app.speech.audio_utils import generate_sine_wav_bytes
    from backend.app.studio.speech import NeutralAdapter
    calls = []
    async def forbidden(self, *args, **kwargs):
        calls.append(True)
        raise AssertionError('Full or timed-out queue must not dispatch')
    monkeypatch.setattr(NeutralAdapter, 'transcribe_rest', forbidden)
    monkeypatch.setattr(NeutralAdapter, 'synthesize_tts', forbidden)
    with studio(tmp_path) as (c, settings, _, sid, h):
        settings.gnani_api_key = SecretStr('valid-mocked-key-123456')
        gate = c.app.state.speech.gatekeeper
        gate.max_waiting = 1
        gate.queue_wait_timeout_sec = 0.5
        session_path = f'/api/v1/studio/sessions/{sid}'
        body = {'epoch':1,'audio_base64':base64.b64encode(generate_sine_wav_bytes()).decode()}
        if operation=='tts':
            c.post(session_path+'/coach', json={'action':'clarify'}, headers={**h,'X-Idempotency-Key':'queue-clarify'})
            sequence=c.get(session_path, headers=h).json()['events'][-1]['sequence']
            body={'epoch':1,'event_sequence':sequence}
        c.portal.call(gate._acquire_single_slot)
        released = False
        try:
            path = session_path+'/speech/'+operation
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending=pool.submit(c.post,path,json=body,headers={**h,'X-Idempotency-Key':'queue-timeout'})
                try:
                    deadline=time.monotonic()+1
                    while gate.get_capacity_status().queued_requests!=1 and time.monotonic()<deadline:
                        time.sleep(0.005)
                    assert gate.get_capacity_status().queued_requests==1
                    full=c.post(path,json=body,headers={**h,'X-Idempotency-Key':'queue-full'})
                    assert full.status_code==429
                    timed_out=pending.result(timeout=1)
                    assert timed_out.status_code==429, timed_out.text
                finally:
                    c.portal.call(gate._release_single_slot)
                    released=True
            assert calls==[]
        finally:
            if not released:
                c.portal.call(gate._release_single_slot)
        assert gate.get_capacity_status().active_requests==0
        assert gate.get_capacity_status().queued_requests==0
        with open_connection(settings.database_path) as db:
            assert db.execute("SELECT count(*) FROM studio_speech_usage WHERE status='RESERVED'").fetchone()[0]==0
            assert db.execute('SELECT count(*) FROM studio_speech_usage').fetchone()[0]==0


@pytest.mark.parametrize('posture', ['teaching','assessment'])
def test_authored_clarification_has_no_solution_leaks(tmp_path, posture):
    from backend.app.studio.scenario_content import get_content
    with studio(tmp_path) as (c, settings, _, sid, h):
        path = f'/api/v1/studio/sessions/{sid}'
        with open_connection(settings.database_path) as db:
            db.execute('UPDATE studio_sessions SET posture=? WHERE id=?', (posture,sid))
        facts = get_content('SD-BR-01')['clarification_facts']
        response = c.get(path+'/clarifications', headers=h)
        assert response.status_code == 200
        assert response.json()['facts'] == facts
        result = c.post(path+'/coach', json={'action':'clarify'},
                        headers={**h,'X-Idempotency-Key':'clarify-action'})
        assert result.status_code == 200
        assert result.json()['facts'] == facts and result.json()['assistance'] is False
        public = c.get(path+'/scenario', headers=h).json()
        assert public['clarification_facts'] == facts
        assert 'hint_ladder' not in public and 'valid_architecture_families' not in public
        assert c.get(path+'/clarifications', headers={'Authorization':'Bearer invalid'}).status_code == 401
