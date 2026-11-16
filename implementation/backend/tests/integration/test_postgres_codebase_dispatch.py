"""Provider accounting against a disposable PostgreSQL schema, without providers."""
import os
from contextlib import closing

import pytest
from starlette.requests import Request
from fastapi import HTTPException

from backend.tests.integration.test_postgres_runtime import runtime, _workspace
from backend.app.db.migrations import open_connection
from backend.app.repo_learning.ingest import golden
from backend.app.repo_learning.service import create, queue
from backend.app.repo_learning import provider_dispatch as dispatch
from backend.app.speech.gatekeeper import accounted_speech_totals

pytestmark = pytest.mark.skipif(not os.environ.get('VIVA_POSTGRES_TEST_DSN'), reason='Dedicated disposable PostgreSQL DSN required')


def test_postgres_codebase_admission_and_retained_usage(runtime):
    client, target = runtime
    workspace, _, headers = _workspace(client)
    files, coverage = golden('REPO-EXP-01')
    snapshot = queue(target, workspace, 'golden_curated', 'REPO-EXP-01')
    create(target, workspace, 'golden_curated', files, coverage, snapshot)
    response = client.post('/api/v1/codebase-learning/sessions', headers=headers, json={
        'snapshot_id': snapshot, 'repo_url': 'https://example.test/synthetic', 'repo_name': 'synthetic'})
    assert response.status_code == 201, response.text
    sid = response.json()['session_id']
    request = Request({'type': 'http', 'app': client.app, 'headers': [(k.lower().encode(),v.encode()) for k,v in headers.items()]})
    key = dispatch.begin(target, request, workspace, sid)
    with pytest.raises(HTTPException):
        dispatch.begin(target, request, workspace, sid)
    rid = dispatch.reserve(target, request, workspace, sid, 'TTS', 0, 20)
    dispatch.settle(target, rid, 'TTS', 'UNCERTAIN')
    dispatch.finish(target, key)
    with pytest.raises(HTTPException):
        dispatch.begin(target, request, workspace, sid)
    with closing(open_connection(target)) as db:
        assert accounted_speech_totals(db)[1] == 20
        assert db.execute('SELECT status FROM codebase_speech_usage WHERE id=?', (rid,)).fetchone()[0] == 'UNCERTAIN'


@pytest.mark.parametrize('dispatched', [False, True])
def test_postgres_fenced_dispatch_recovery(runtime, dispatched):
    client, target = runtime
    workspace, _, headers = _workspace(client)
    files, coverage = golden('REPO-EXP-01')
    snapshot = queue(target, workspace, 'golden_curated', 'REPO-EXP-01')
    create(target, workspace, 'golden_curated', files, coverage, snapshot)
    response = client.post('/api/v1/codebase-learning/sessions', headers=headers, json={
        'snapshot_id': snapshot, 'repo_url': 'https://example.test/synthetic', 'repo_name': 'synthetic'})
    assert response.status_code == 201
    sid = response.json()['session_id']
    request = Request({'type': 'http', 'app': client.app, 'headers': [(k.lower().encode(), v.encode()) for k, v in headers.items()]})
    key = dispatch.begin(target, request, workspace, sid)
    token = dispatch.fence_token(target, key)
    rid = dispatch.reserve(target, request, workspace, sid, 'MODEL', 0, 0, request_key=key, token=token)
    if dispatched:
        dispatch.mark_dispatching(target, rid, key, token)
    dispatch.recover_fenced_request(target, key)
    with pytest.raises(HTTPException):
        dispatch.mark_dispatching(target, rid, key, token)
    with closing(open_connection(target)) as db:
        usage = db.execute('SELECT status FROM codebase_model_usage WHERE id=?', (rid,)).fetchone()
        assert (usage[0] if usage else None) == ('UNCERTAIN' if dispatched else None)
