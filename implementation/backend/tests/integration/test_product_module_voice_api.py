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
        db.execute('INSERT INTO interview_sessions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
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


def test_workspace_deletion_preserves_anonymous_daily_budget(voice):
    assert post(voice).status_code == 200
    with closing(open_connection(voice.path)) as db:
        db.execute('DELETE FROM studio_workspaces WHERE id=?', (voice.wid,))
        assert db.execute('SELECT count(*) FROM module_speech_usage').fetchone()[0] == 0
        assert db.execute('SELECT SUM(request_count) FROM studio_speech_deleted_daily').fetchone()[0] == 1
