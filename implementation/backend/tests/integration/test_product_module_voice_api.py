"""Source-bound voice never submits drafts, reads hidden answers, or bypasses quotas."""
from __future__ import annotations

import asyncio
import base64
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
import pytest

from backend.app.db.migrations import apply_migrations, open_connection
from backend.app.speech.audio_utils import generate_sine_wav_bytes
from backend.app.studio.security import digest_token


class Gate:
    max_stt_seconds_budget = 7200
    max_tts_chars_budget = 250000

    def __init__(self):
        self.active = 0
        self.acquired = 0

    async def _acquire_single_slot(self):
        assert self.active == 0
        self.active += 1
        self.acquired += 1

    def _release_single_slot(self):
        self.active -= 1


@pytest.fixture
def voice(tmp_path, monkeypatch):
    from backend.app.learning_voice.routes import router
    from backend.app.learning_voice import provider

    path = tmp_path / 'voice.sqlite'
    apply_migrations(path)
    app = FastAPI()
    app.state.settings = SimpleNamespace(database_path=path, gnani_api_key=SecretStr('test-key-not-live'),
        gnani_base_url='https://speech.invalid', gnani_tts_model='timbre-v3.0', gnani_tts_voice='Avinash',
        max_stt_seconds_per_session=180, max_tts_chars_per_session=4000, global_daily_call_limit=800)
    gate = Gate()
    app.state.speech = SimpleNamespace(gatekeeper=gate)
    app.include_router(router, prefix='/api/v1')
    now = datetime.now(timezone.utc)
    wid, sid, mid = (str(uuid4()) for _ in range(3))
    token = 'w' * 48
    with closing(open_connection(path)) as db:
        db.execute('INSERT INTO studio_workspaces VALUES(?,?,?,?,NULL)',
                   (wid, digest_token(token), now.isoformat(), (now + timedelta(days=1)).isoformat()))
        db.execute('INSERT INTO interview_sessions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (sid, wid, 'cs', 'beginner', '["databases"]', 15, 'en-IN', 1, 'active',
                    now.isoformat(), (now + timedelta(minutes=15)).isoformat(), None, None, '{}'))
        db.execute('INSERT INTO interview_questions VALUES(?,?,?,?,?,?)',
                   (mid, sid, 1, 1, json.dumps({'id':mid, 'text':'Explain an index tradeoff.',
                    'indicator_ids':['PRIVATE-ANSWER'], 'probe_target':'hidden answer'}), now.isoformat()))
    calls = []
    audio = generate_sine_wav_bytes(duration_sec=.1)

    class Adapter:
        async def transcribe_rest(self, request, wav):
            calls.append(('STT', request, wav))
            return SimpleNamespace(raw_transcript='my draft', normalized_transcript='My draft')

        async def synthesize_tts(self, request):
            calls.append(('TTS', request))
            return SimpleNamespace(wav_bytes=audio)

    monkeypatch.setattr(provider, 'adapter', lambda request: Adapter())
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, app=app, path=path, wid=wid, sid=sid, mid=mid,
            headers={'X-Workspace-Id':wid, 'X-Workspace-Token':token}, audio=audio,
            calls=calls, gate=gate, provider=provider)


def post(v, operation='stt', **patch):
    body = {'epoch':1, 'audio_base64':base64.b64encode(v.audio).decode(), 'language_mode':'en-IN'} if operation == 'stt' else {
        'epoch':1, 'message_id':v.mid, 'language':'ta-IN', 'voice':'Shivani'}
    return v.client.post(f'/api/v1/module-voice/interview/{v.sid}/{operation}',
                         headers=v.headers, json={**body, **patch})


def usage(v):
    with closing(open_connection(v.path)) as db:
        return [dict(row) for row in db.execute('SELECT * FROM module_speech_usage')]


def test_transcription_is_final_draft_without_source_submission_or_audio_retention(voice):
    result = post(voice)
    assert result.status_code == 200, result.text
    assert result.json() == {'raw_transcript':'my draft', 'normalized_transcript':'My draft',
                             'requires_confirmation':True, 'epoch':1}
    assert result.headers['cache-control'] == 'no-store'
    assert voice.gate.acquired == 1 and voice.gate.active == 0
    assert usage(voice)[0]['status'] == 'COMMITTED'
    assert usage(voice)[0]['stt_seconds'] == .1
    with closing(open_connection(voice.path)) as db:
        assert db.execute('SELECT count(*) FROM interview_answers').fetchone()[0] == 0
        assert db.execute('SELECT epoch FROM interview_sessions').fetchone()[0] == 1
    assert all('audio' not in key and 'transcript' not in key for key in usage(voice)[0])


def test_tts_only_uses_owned_persisted_question_and_requested_documented_selection(voice):
    result = post(voice, 'tts')
    assert result.status_code == 200, result.text
    request = voice.calls[0][1]
    assert request.text == 'Explain an index tradeoff.'
    assert request.language == 'ta-IN' and request.voice == 'Shivani'
    assert 'PRIVATE' not in request.text and 'hidden' not in request.text
    assert base64.b64decode(result.json()['audio_base64']) == voice.audio
    assert usage(voice)[0]['tts_chars'] > 0


@pytest.mark.parametrize('patch', [{'epoch':True}, {'epoch':0}, {'audio_base64':'not base64'},
    {'audio_base64':base64.b64encode(b'not wav').decode()}, {'language_mode':'unsupported'}, {'text':'arbitrary'}])
def test_stt_rejects_invalid_dto_or_audio_before_admission(voice, patch):
    assert post(voice, **patch).status_code == 422
    assert voice.calls == [] and usage(voice) == []


@pytest.mark.parametrize('patch', [{'text':'speak my arbitrary text'}, {'message_id':'hidden'},
    {'language':'unknown'}, {'voice':'unknown'}, {'epoch':0}])
def test_tts_rejects_hidden_arbitrary_text_and_unsupported_selection(voice, patch):
    assert post(voice, 'tts', **patch).status_code in (404, 422)
    assert voice.calls == [] and usage(voice) == []


def test_workspace_isolation_stale_epoch_and_completed_stt(voice):
    voice.headers = {**voice.headers, 'X-Workspace-Token':'wrong'}
    assert post(voice).status_code == 401
    voice.headers = {**voice.headers, 'X-Workspace-Token':'w' * 48}
    assert post(voice, epoch=2).status_code == 409
    with closing(open_connection(voice.path)) as db:
        db.execute('UPDATE interview_sessions SET state=\'completed\',completed_at=? WHERE id=?',
                   (datetime.now(timezone.utc).isoformat(), voice.sid))
    assert post(voice).status_code == 409
    assert voice.calls == [] and usage(voice) == []


def test_missing_or_placeholder_credential_is_text_only_503(voice):
    for key in (None, SecretStr('your-gnani-api-key')):
        voice.app.state.settings.gnani_api_key = key
        assert post(voice).status_code == 503
    assert usage(voice) == [] and voice.calls == []


def test_all_counted_usage_statuses_exhaust_daily_quota(voice):
    now = datetime.now(timezone.utc).isoformat()
    with closing(open_connection(voice.path)) as db:
        for status in ('RESERVED','COMMITTED','UNCERTAIN'):
            db.execute('INSERT INTO module_speech_usage VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (str(uuid4()), voice.wid, 'other-source', 'lesson', 1, 'TTS', 0, 1, 1, status, now, now))
    voice.app.state.settings.global_daily_call_limit = 3
    assert post(voice).status_code == 429
    assert voice.calls == []


@pytest.mark.parametrize('operation', ['stt','tts'])
def test_legacy_and_studio_budgets_are_included_in_module_admission(voice, operation):
    now = datetime.now(timezone.utc).isoformat()
    with closing(open_connection(voice.path)) as db:
        db.execute('INSERT INTO sessions(id,token_hash,exercise_id,spec_version,language_mode,interaction_mode,created_at,updated_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?)',
            ('legacy','legacy-token','exercise','v1','en-IN','text',now,now,'2099-01-01T00:00:00+00:00'))
        db.execute('INSERT INTO usage_reservations(id,session_id,operation_type,stt_seconds,tts_chars,request_count,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
            ('legacy-usage','legacy','STT',.2,20,1,'COMMITTED',now,now))
        db.execute('INSERT INTO studio_sessions(id,workspace_id,token_hash,mode,posture,scenario_id,scenario_version,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?)',
            ('studio',voice.wid,'studio-token','system_design','practice','scenario','v1',now,'2099-01-01T00:00:00+00:00'))
        db.execute('INSERT INTO studio_speech_usage VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            ('studio-usage','studio',1,'STT','key','digest',.2,20,1,'UNCERTAIN',now,now))
    if operation == 'stt':
        voice.gate.max_stt_seconds_budget = .45
    else:
        voice.gate.max_tts_chars_budget = 50
    assert post(voice, operation).status_code == 429
    assert voice.calls == [] and usage(voice) == []
    voice.gate.max_stt_seconds_budget = 7200
    voice.gate.max_tts_chars_budget = 250000
    voice.app.state.settings.global_daily_call_limit = 2
    assert post(voice, operation).status_code == 429
    assert voice.calls == [] and usage(voice) == []


def test_source_changes_during_dispatch_discard_result_but_commit_real_usage(voice, monkeypatch):
    class StaleAdapter:
        async def transcribe_rest(self, request, wav):
            with closing(open_connection(voice.path)) as db:
                db.execute('UPDATE interview_sessions SET epoch=2 WHERE id=?', (voice.sid,))
            return SimpleNamespace(raw_transcript='stale', normalized_transcript='stale')
    monkeypatch.setattr(voice.provider, 'adapter', lambda request: StaleAdapter())
    assert post(voice).status_code == 409
    assert usage(voice)[0]['status'] == 'COMMITTED'
    assert voice.gate.active == 0


def test_provider_timeout_awaits_cleanup_and_retains_uncertain_usage(voice, monkeypatch):
    cleaned = []
    class HangingAdapter:
        async def transcribe_rest(self, request, wav):
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.append(True)
    monkeypatch.setattr(voice.provider, 'adapter', lambda request: HangingAdapter())
    monkeypatch.setattr(voice.provider, 'PROVIDER_DEADLINE_SECONDS', .01)
    assert post(voice).status_code == 503
    assert cleaned == [True] and usage(voice)[0]['status'] == 'UNCERTAIN'
    assert voice.gate.active == 0


def test_lesson_persisted_question_scope_and_explanation_are_safe_sources(voice):
    from backend.app.learning.service import create_session
    with closing(open_connection(voice.path)) as db:
        session = create_session(db, voice.wid, 'dsa-complexity', 'en-IN')
    identifiers = [m['id'] for m in session['coach_messages']] + [session['question']['id']]
    for identifier in identifiers:
        result = voice.client.post(f"/api/v1/module-voice/lesson/{session['id']}/tts",
            headers=voice.headers, json={'epoch':session['epoch'], 'message_id':identifier})
        assert result.status_code == 200, result.text
    for call in voice.calls:
        assert 'accepted_answers' not in call[1].text and 'correct_answer' not in call[1].text
    with closing(open_connection(voice.path)) as db:
        assert db.execute('SELECT count(*) FROM learning_answers').fetchone()[0] == 0


def test_redrive_plan_fences_independent_epoch_and_never_speaks_expected_facts(voice):
    from backend.app.repo_learning import service, rederive
    snapshot = service.create(str(voice.path), voice.wid, 'zip_upload',
        {'main.py':'def run():\n    return 1\n\nif __name__ == "__main__":\n    run()\n'},
        {'total':1,'skipped':0})
    plan = rederive.create_plan(str(voice.path), voice.wid, snapshot['snapshot_id'])
    step = plan['current_step']
    url = f"/api/v1/module-voice/redrive/{plan['plan_id']}/tts"
    for message_id, text in ((step['step_id'],step['question']),
                             (step['step_id'] + ':explanation',step['explanation'])):
        result = voice.client.post(url, headers=voice.headers,
                                   json={'epoch':plan['epoch'], 'message_id':message_id})
        assert result.status_code == 200, result.text
        assert voice.calls[-1][1].text == text
    assert voice.client.post(url, headers=voice.headers,
        json={'epoch':plan['epoch'], 'message_id':step['step_id'] + ':facts'}).status_code == 404
    rederive.answer_plan(str(voice.path), voice.wid, plan['plan_id'], plan['epoch'], 'unsure')
    assert voice.client.post(url, headers=voice.headers,
        json={'epoch':plan['epoch'], 'message_id':step['step_id']}).status_code == 409
    with closing(open_connection(voice.path)) as db:
        assert db.execute('SELECT count(*) FROM repo_learning_attempts').fetchone()[0] == 1


def test_redrive_source_tampering_blocks_voice(voice):
    from backend.app.repo_learning import service, rederive
    snapshot = service.create(str(voice.path), voice.wid, 'zip_upload',
        {'main.py':'def run():\n    return 1\n'}, {'total':1,'skipped':0})
    plan = rederive.create_plan(str(voice.path), voice.wid, snapshot['snapshot_id'])
    with closing(open_connection(voice.path)) as db:
        db.execute('UPDATE repo_chunks SET text=? WHERE snapshot_id=?', ('tampered',snapshot['snapshot_id']))
    result = voice.client.post(f"/api/v1/module-voice/redrive/{plan['plan_id']}/tts",
        headers=voice.headers, json={'epoch':plan['epoch'], 'message_id':plan['current_step']['step_id']})
    assert result.status_code == 409 and voice.calls == []


def test_owned_other_workspace_source_returns_not_found(voice):
    with closing(open_connection(voice.path)) as db:
        now = datetime.now(timezone.utc)
        db.execute('INSERT INTO studio_workspaces VALUES(?,?,?,?,NULL)',
            ('other',digest_token('o' * 48),now.isoformat(),(now+timedelta(days=1)).isoformat()))
    voice.headers = {'X-Workspace-Id':'other', 'X-Workspace-Token':'o' * 48}
    assert post(voice).status_code == 404
    assert voice.calls == []


def test_tts_changed_persisted_text_is_discarded_after_provider(voice, monkeypatch):
    class ChangedAdapter:
        async def synthesize_tts(self, request):
            with closing(open_connection(voice.path)) as db:
                db.execute('UPDATE interview_questions SET question_json=? WHERE id=?',
                    (json.dumps({'text':'replacement'}), voice.mid))
            return SimpleNamespace(wav_bytes=voice.audio)
    monkeypatch.setattr(voice.provider, 'adapter', lambda request:ChangedAdapter())
    assert post(voice, 'tts').status_code == 409
    assert usage(voice)[0]['status'] == 'COMMITTED'


def test_busy_slot_rejection_does_not_reserve(voice, monkeypatch):
    from backend.app.speech.gatekeeper import SpeechBusyError
    async def busy():
        raise SpeechBusyError('busy')
    monkeypatch.setattr(voice.gate,'_acquire_single_slot',busy)
    assert post(voice).status_code == 429
    assert usage(voice) == [] and voice.calls == []


def test_disconnect_awaits_provider_cleanup_and_retains_uncertain_usage(voice, monkeypatch):
    from backend.app.speech.routes import _await_connected_voice
    cleaned = []
    class HangingAdapter:
        async def transcribe_rest(self, request, wav):
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.append(True)
    async def disconnected(request, operation):
        async def gone():
            return True
        request.is_disconnected = gone
        return await _await_connected_voice(request, operation)
    monkeypatch.setattr(voice.provider,'adapter',lambda request:HangingAdapter())
    monkeypatch.setattr(voice.provider,'_await_connected_voice',disconnected)
    assert post(voice).status_code == 409
    assert cleaned == [True] and voice.gate.active == 0
    assert usage(voice)[0]['status'] == 'UNCERTAIN'


def test_unexpected_provider_failure_is_sanitized_and_counted(voice, monkeypatch):
    class BrokenAdapter:
        async def transcribe_rest(self, request, wav):
            raise RuntimeError('private upstream details')
    monkeypatch.setattr(voice.provider,'adapter',lambda request:BrokenAdapter())
    result = post(voice)
    assert result.status_code == 503 and 'private upstream' not in result.text
    assert usage(voice)[0]['status'] == 'UNCERTAIN'


def test_soft_workspace_deletion_purges_source_linkage_without_resetting_budget(voice):
    assert post(voice).status_code == 200
    with closing(open_connection(voice.path)) as db:
        db.execute('UPDATE studio_workspaces SET deleted_at=? WHERE id=?',
            (datetime.now(timezone.utc).isoformat(), voice.wid))
        assert db.execute('SELECT count(*) FROM module_speech_usage').fetchone()[0] == 0
        assert db.execute('SELECT SUM(request_count) FROM studio_speech_deleted_daily').fetchone()[0] == 1
    assert post(voice).status_code == 401


def test_cancellation_during_sqlite_admission_never_orphans_reservation(voice, monkeypatch):
    import threading
    from backend.app.learning_voice.sources import Capability, current
    from fastapi import HTTPException
    admitted, release = threading.Event(), threading.Event()
    original = voice.provider.usage.reserve
    def slow_reserve(*args):
        rid = original(*args)
        admitted.set()
        assert release.wait(2)
        return rid
    monkeypatch.setattr(voice.provider.usage, 'reserve', slow_reserve)
    async def scenario():
        request = SimpleNamespace(app=voice.app)
        capability = Capability(voice.wid, 'w' * 48)
        source = current(request, capability, 'interview', voice.sid, 1)
        async def dispatch():
            pytest.fail('Cancelled admission must never dispatch')
        task = asyncio.create_task(voice.provider.run(request, capability, 'interview', voice.sid,
            1, None, source, .1, 0, 1, dispatch))
        assert await asyncio.to_thread(admitted.wait, 2)
        task.cancel()
        release.set()
        with pytest.raises(HTTPException) as raised:
            await task
        assert raised.value.status_code == 409
    asyncio.run(scenario())
    assert usage(voice)[0]['status'] == 'UNCERTAIN'
    assert voice.gate.active == 0


def test_reservation_serializes_shared_daily_budget_across_workers(voice):
    from concurrent.futures import ThreadPoolExecutor
    from backend.app.learning_voice.sources import Capability, current
    from fastapi import HTTPException
    request = SimpleNamespace(app=voice.app)
    capability = Capability(voice.wid, 'w' * 48)
    source = current(request, capability, 'interview', voice.sid, 1)
    voice.app.state.settings.global_daily_call_limit = 1
    def attempt(_):
        try:
            voice.provider.usage.reserve(request, capability, 'interview', voice.sid, 1,
                                         None, source, .1, 0, 1)
            return 200
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt,range(2))) == [200,429]
    assert len(usage(voice)) == 1


@pytest.mark.parametrize('status', ['RESERVED','COMMITTED','UNCERTAIN'])
@pytest.mark.parametrize('hard_delete', [False, True])
def test_deleted_paid_audio_usage_still_bounds_another_workspace(voice, status, hard_delete):
    now = datetime.now(timezone.utc).isoformat()
    with closing(open_connection(voice.path)) as db:
        db.execute('INSERT INTO module_speech_usage VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            ('paid-delete',voice.wid,'private-source','lesson',1,'TTS',.5,1234,1,status,now,now))
        if hard_delete:
            db.execute('DELETE FROM studio_workspaces WHERE id=?', (voice.wid,))
        else:
            db.execute('UPDATE studio_workspaces SET deleted_at=? WHERE id=?', (now,voice.wid))
        new_wid = str(uuid4())
        db.execute('INSERT INTO studio_workspaces VALUES(?,?,?,?,NULL)',
            (new_wid,digest_token('n' * 48),now,'2099-01-01T00:00:00+00:00'))
        from backend.app.learning.service import create_session
        session = create_session(db,new_wid,'dsa-complexity','en-IN')
    voice.provider.usage.settle(SimpleNamespace(app=voice.app),'paid-delete','COMMITTED')
    voice.gate.max_tts_chars_budget = 1234
    result = voice.client.post(f"/api/v1/module-voice/lesson/{session['id']}/tts",
        headers={'X-Workspace-Id':new_wid,'X-Workspace-Token':'n' * 48},
        json={'epoch':1,'message_id':session['coach_messages'][0]['id']})
    assert result.status_code == 429 and voice.calls == []
    with closing(open_connection(voice.path)) as db:
        total = db.execute('SELECT SUM(stt_seconds),SUM(tts_chars) FROM module_speech_deleted_totals').fetchone()
        assert tuple(total) == (.5,1234)
        assert db.execute('SELECT SUM(request_count) FROM studio_speech_deleted_daily').fetchone()[0] == 1


def test_privacy_upgrade_conservatively_retains_already_deleted_unknown_quantities(tmp_path):
    import shutil
    from pathlib import Path
    from backend.app.db import migrations
    path = tmp_path / 'upgrade.sqlite'
    previous = tmp_path / 'old-migrations'
    previous.mkdir()
    for sql in Path(migrations.__file__).with_name('migrations').glob('*.sql'):
        if int(sql.name.split('_')[0]) <= 22:
            shutil.copy2(sql, previous / sql.name)
    apply_migrations(path,previous)
    with closing(open_connection(path)) as db:
        db.execute('INSERT INTO studio_speech_deleted_daily VALUES(?,?)', ('2026-01-01',2))
    apply_migrations(path)
    with closing(open_connection(path)) as db:
        row = db.execute('SELECT * FROM module_speech_deleted_totals WHERE day=?', ('2026-01-01',)).fetchone()
        assert row['stt_seconds'] == 60 and row['tts_chars'] == 16000
        assert db.execute('SELECT SUM(request_count) FROM studio_speech_deleted_daily').fetchone()[0] == 2


@pytest.mark.parametrize('status', ['RESERVED','COMMITTED','UNCERTAIN'])
def test_studio_usage_deletion_cannot_reset_shared_paid_character_allowance(voice, status):
    from backend.app.studio.security import purge_speech_usage
    from backend.app.studio.speech import reserve as studio_reserve
    from fastapi import HTTPException
    now = datetime.now(timezone.utc).isoformat()
    with closing(open_connection(voice.path)) as db:
        db.execute('INSERT INTO studio_sessions(id,workspace_id,token_hash,mode,posture,scenario_id,scenario_version,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?)',
            ('studio-retained',voice.wid,digest_token('s' * 48),'system_design','practice','scenario','v1',now,'2099-01-01T00:00:00+00:00'))
        db.execute('INSERT INTO studio_speech_usage VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            ('studio-deleted','studio-retained',1,'TTS','old-idempotency','digest',.5,1234,1,status,now,now))
        purge_speech_usage(db, 'studio-retained')
    voice.gate.max_tts_chars_budget = 1234
    with pytest.raises(HTTPException) as raised:
        studio_reserve(SimpleNamespace(app=voice.app),'studio-retained','Bearer ' + 's' * 48,
            1,'new-idempotency','TTS','digest',0,1,1)
    assert raised.value.status_code == 429
    with closing(open_connection(voice.path)) as db:
        assert tuple(db.execute('SELECT SUM(stt_seconds),SUM(tts_chars) FROM module_speech_deleted_totals').fetchone()) == (.5,1234)
        assert db.execute('SELECT SUM(request_count) FROM studio_speech_deleted_daily').fetchone()[0] == 1


def test_workspace_deletion_preserves_anonymous_daily_budget(voice):
    assert post(voice).status_code == 200
    with closing(open_connection(voice.path)) as db:
        db.execute('DELETE FROM studio_workspaces WHERE id=?', (voice.wid,))
        assert db.execute('SELECT count(*) FROM module_speech_usage').fetchone()[0] == 0
        assert db.execute('SELECT SUM(request_count) FROM studio_speech_deleted_daily').fetchone()[0] == 1
