"""Synthetic provider admission; no live credentials or network requests."""
import asyncio
from types import SimpleNamespace
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.tests.integration.test_codebase_mentor import mentor_env
from backend.app.coaching.model_budget import daily_count
from backend.app.db.migrations import open_connection
from backend.app.repo_learning import provider_dispatch as dispatch
from backend.app.speech.gatekeeper import accounted_speech_totals


def context(env):
    client = env['client']
    client.app.state.speech = SimpleNamespace(gatekeeper=SimpleNamespace(max_stt_seconds_budget=7200, max_tts_chars_budget=250000))
    response = client.post('/api/v1/codebase-learning/sessions', headers=env['headers'], json={
        'snapshot_id': env['snap_id'], 'repo_url': 'https://example.test/repo', 'repo_name': 'synthetic'})
    assert response.status_code == 201, response.text
    async def receive():
        await asyncio.sleep(10)
        return {'type': 'http.request'}
    request = Request({'type': 'http', 'app': client.app, 'headers': [(k.lower().encode(), v.encode()) for k,v in env['headers'].items()]}, receive)
    return request, response.json()['session_id']


def test_atomic_shared_model_quota_and_uncertain_lease(mentor_env):
    req, sid = context(mentor_env)
    req.app.state.settings.model_daily_call_limit = 1
    target = mentor_env['db_path']
    rid = dispatch.reserve(target, req, 'ws_mentor', sid, 'MODEL', 0, 0)
    dispatch.settle(target, rid, 'MODEL', 'UNCERTAIN')
    with pytest.raises(HTTPException) as error:
        dispatch.reserve(target, req, 'ws_mentor', sid, 'MODEL', 0, 0)
    assert error.value.status_code == 429
    with open_connection(target) as db:
        assert daily_count(db, datetime.now(timezone.utc).isoformat()) == 1
        assert db.execute('SELECT status FROM model_dispatch_leases WHERE id=?', (rid,)).fetchone()[0] == 'UNCERTAIN'


def test_idempotency_and_concurrent_turn_admission(mentor_env):
    req, sid = context(mentor_env)
    target = mentor_env['db_path']
    key = dispatch.begin(target, req, 'ws_mentor', sid)
    with pytest.raises(HTTPException):
        dispatch.begin(target, req, 'ws_mentor', sid)
    dispatch.finish(target, key)
    replay = Request({**req.scope, 'headers': req.scope['headers'] + [(b'idempotency-key', key.split(':', 1)[1].encode())]})
    with pytest.raises(HTTPException):
        dispatch.begin(target, replay, 'ws_mentor', sid)


@pytest.mark.asyncio
async def test_uncertain_provider_never_retried_and_counted(mentor_env):
    req, sid = context(mentor_env)
    key = dispatch.begin(mentor_env['db_path'], req, 'ws_mentor', sid)
    token = dispatch.fence_token(mentor_env['db_path'], key)
    calls = []
    async def provider():
        calls.append(1)
        raise TimeoutError('synthetic unknown completion')
    with pytest.raises(TimeoutError):
        await dispatch.run(mentor_env['db_path'], req, 'ws_mentor', sid, 'MODEL', provider, request_key=key, token=token)
    assert len(calls) == 1
    with open_connection(mentor_env['db_path']) as db:
        assert db.execute('SELECT status FROM codebase_model_usage').fetchone()[0] == 'UNCERTAIN'


@pytest.mark.asyncio
async def test_deleted_owner_rejects_completed_stale_response(mentor_env):
    req, sid = context(mentor_env)
    key = dispatch.begin(mentor_env['db_path'], req, 'ws_mentor', sid)
    token = dispatch.fence_token(mentor_env['db_path'], key)
    async def provider():
        with open_connection(mentor_env['db_path']) as db:
            db.execute('UPDATE codebase_learning_sessions SET deleted_at=? WHERE id=?', (datetime.now(timezone.utc).isoformat(), sid))
        return 'stale private response'
    with pytest.raises(HTTPException) as error:
        await dispatch.run(mentor_env['db_path'], req, 'ws_mentor', sid, 'MODEL', provider, request_key=key, token=token)
    assert error.value.status_code == 404
    with open_connection(mentor_env['db_path']) as db:
        assert db.execute('SELECT status FROM codebase_model_usage').fetchone()[0] == 'COMMITTED'


def test_foreign_owner_no_reservation_and_speech_shared_totals(mentor_env):
    req, sid = context(mentor_env)
    with pytest.raises(HTTPException):
        dispatch.reserve(mentor_env['db_path'], req, 'foreign', sid, 'MODEL', 0, 0)
    rid = dispatch.reserve(mentor_env['db_path'], req, 'ws_mentor', sid, 'TTS', 0, 100)
    dispatch.settle(mentor_env['db_path'], rid, 'TTS', 'COMMITTED')
    with open_connection(mentor_env['db_path']) as db:
        assert db.execute('SELECT count(*) FROM codebase_model_usage').fetchone()[0] == 0
        assert accounted_speech_totals(db)[1] == 100


def test_parallel_sessions_share_atomic_model_limit(mentor_env):
    from concurrent.futures import ThreadPoolExecutor
    req, sid = context(mentor_env)
    req2, sid2 = context(mentor_env)
    req.app.state.settings.model_daily_call_limit = 1
    def attempt(owner):
        try:
            return dispatch.reserve(mentor_env['db_path'], req, 'ws_mentor', owner, 'MODEL', 0, 0)
        except HTTPException as exc:
            assert exc.status_code == 429
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [sid, sid2]))
    assert sum(result is not None for result in results) == 1


@pytest.mark.asyncio
async def test_cancelled_dispatch_retains_credit_and_prevents_fresh_key(mentor_env):
    req, sid = context(mentor_env)
    key = dispatch.begin(mentor_env['db_path'], req, 'ws_mentor', sid)
    token = dispatch.fence_token(mentor_env['db_path'], key)
    started = asyncio.Event()
    async def provider():
        started.set()
        await asyncio.Event().wait()
    task = asyncio.create_task(dispatch.run(mentor_env['db_path'], req, 'ws_mentor', sid, 'MODEL', provider, request_key=key, token=token))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(HTTPException) as error:
        dispatch.begin(mentor_env['db_path'], req, 'ws_mentor', sid)
    assert error.value.status_code == 409
    with open_connection(mentor_env['db_path']) as db:
        assert db.execute('SELECT status FROM codebase_model_usage').fetchone()[0] == 'UNCERTAIN'


def test_cloud_creation_replay_keeps_complete_greeting_without_redispatch(mentor_env, monkeypatch):
    from pydantic import SecretStr
    from backend.app.repo_learning.mentor_service import CodebaseMentorService
    client = mentor_env['client']
    client.app.state.settings.gnani_api_key = SecretStr('synthetic-no-network-key')
    calls = []
    async def synthetic_timeout(self, *args, **kwargs):
        calls.append(1)
        raise HTTPException(503, 'Synthetic provider timeout')
    monkeypatch.setattr(CodebaseMentorService, '_synthesize_audio', synthetic_timeout)
    payload = {'snapshot_id': mentor_env['snap_id'], 'repo_url': 'https://example.test/synthetic', 'repo_name': 'synthetic'}
    headers = {**mentor_env['headers'], 'X-Idempotency-Key': 'stable-create-key'}
    assert client.post('/api/v1/codebase-learning/sessions', headers=headers, json=payload).status_code == 503
    assert client.post('/api/v1/codebase-learning/sessions', headers=headers, json=payload).status_code == 409
    assert calls == [1]
    with open_connection(mentor_env['db_path']) as db:
        assert db.execute('SELECT count(*) FROM codebase_learning_sessions').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM codebase_learning_messages WHERE role=?', ('mentor',)).fetchone()[0] == 1


def test_conflicting_idempotency_headers_rejected(mentor_env):
    req, _ = context(mentor_env)
    ambiguous = Request({**req.scope, 'headers': req.scope['headers'] + [(b'x-idempotency-key', b'a'), (b'idempotency-key', b'b')]})
    with pytest.raises(HTTPException) as error:
        dispatch.idempotency_key(ambiguous)
    assert error.value.status_code == 422


def test_fence_prepared_reservation_prevents_late_dispatch(mentor_env):
    req, sid = context(mentor_env)
    target = mentor_env['db_path']
    key = dispatch.begin(target, req, 'ws_mentor', sid)
    token = dispatch.fence_token(target, key)
    rid = dispatch.reserve(target, req, 'ws_mentor', sid, 'MODEL', 0, 0, request_key=key, token=token)
    dispatch.recover_fenced_request(target, key)
    with pytest.raises(HTTPException):
        dispatch.mark_dispatching(target, rid, key, token)
    with open_connection(target) as db:
        assert db.execute('SELECT count(*) FROM codebase_model_usage WHERE id=?', (rid,)).fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM model_dispatch_leases WHERE id=?', (rid,)).fetchone()[0] == 0
        with pytest.raises(HTTPException):
            dispatch.check_fence(db, key, token)


def test_fence_dispatched_reservation_retains_unknown_cost(mentor_env):
    req, sid = context(mentor_env)
    target = mentor_env['db_path']
    key = dispatch.begin(target, req, 'ws_mentor', sid)
    token = dispatch.fence_token(target, key)
    rid = dispatch.reserve(target, req, 'ws_mentor', sid, 'MODEL', 0, 0, request_key=key, token=token)
    dispatch.mark_dispatching(target, rid, key, token)
    dispatch.recover_fenced_request(target, key)
    dispatch.settle(target, rid, 'MODEL', 'COMMITTED')  # late worker cannot overwrite uncertainty
    with open_connection(target) as db:
        assert db.execute('SELECT status FROM codebase_model_usage WHERE id=?', (rid,)).fetchone()[0] == 'UNCERTAIN'
        assert db.execute('SELECT status FROM model_dispatch_leases WHERE id=?', (rid,)).fetchone()[0] == 'UNCERTAIN'
    with pytest.raises(HTTPException):
        dispatch.begin(target, req, 'ws_mentor', sid)


@pytest.mark.parametrize('phase', ['PREPARED', 'DISPATCHING'])
def test_killed_worker_recovery_at_dispatch_boundary(mentor_env, tmp_path, phase):
    import os
    import subprocess
    import sys

    req, sid = context(mentor_env)
    target = mentor_env['db_path']
    key = dispatch.begin(target, req, 'ws_mentor', sid)
    token = dispatch.fence_token(target, key)
    rid = dispatch.reserve(target, req, 'ws_mentor', sid, 'MODEL', 0, 0, request_key=key, token=token)
    counter = tmp_path / 'synthetic-provider-calls'
    script = '''
import sys, time
from backend.app.repo_learning.provider_dispatch import mark_dispatching
target, rid, key, token, phase, counter = sys.argv[1:]
if phase == "DISPATCHING":
    mark_dispatching(target, rid, key, token)
    with open(counter, "a") as f:
        f.write("call\\n")
print("ready", flush=True)
time.sleep(60)
'''
    proc = subprocess.Popen([sys.executable, '-c', script, str(target), rid, key, token, phase, str(counter)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=os.environ.copy())
    try:
        assert proc.stdout.readline().strip() == 'ready'
        proc.kill()
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
    dispatch.recover_fenced_request(target, key)
    with pytest.raises(HTTPException):
        dispatch.mark_dispatching(target, rid, key, token)
    with open_connection(target) as db:
        usage = db.execute('SELECT status FROM codebase_model_usage WHERE id=?', (rid,)).fetchone()
        if phase == 'PREPARED':
            assert usage is None
            assert not counter.exists()
        else:
            assert usage[0] == 'UNCERTAIN'
            assert counter.read_text().splitlines() == ['call']
            with pytest.raises(HTTPException):
                dispatch.begin(target, req, 'ws_mentor', sid)
