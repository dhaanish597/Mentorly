"""Actual HTTP recovery, rotation, replay privacy and record reuse on SQLite."""
from contextlib import closing
import json
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient
from backend.app.core.config import Settings
from backend.app.db.migrations import open_connection
from backend.app.main import create_app


@pytest.fixture
def harness(tmp_path):
    settings = Settings(_env_file=None, env='test', database_path=tmp_path/'records.db', database_url=None,
                        tts_cache_dir=tmp_path/'audio', gnani_api_key=None, groq_api_key=None,
                        retention_interval_seconds=86400)
    with TestClient(create_app(settings)) as client:
        wid, token = str(uuid.uuid4()), secrets.token_urlsafe(32)
        result = client.post('/api/v1/studio/workspaces', json={'workspace_id': wid, 'workspace_token': token},
                             headers={'X-Idempotency-Key': str(uuid.uuid4())})
        assert result.status_code == 200
        yield client, settings.database_target, wid, token


def headers(token, key=None):
    return {'Authorization': 'Bearer '+token, 'X-Idempotency-Key': key or str(uuid.uuid4())}


def setup(client, wid, token):
    recovery = secrets.token_urlsafe(32)
    response = client.put(f'/api/v1/studio/workspaces/{wid}/recovery', headers=headers(token), json={'recovery_token': recovery})
    assert response.status_code == 200, response.text
    assert 'recovery_token' not in response.text
    return recovery


def restore(client, wid, recovery, replacement=None):
    token = replacement or secrets.token_urlsafe(32)
    response = client.post(f'/api/v1/studio/workspaces/{wid}/recover', json={'recovery_token': recovery, 'workspace_token': token})
    return response, token


def test_new_browser_restores_same_learning_records_and_rotates_capability(harness):
    client, db, wid, token = harness
    owner = {'X-Workspace-Id': wid, 'X-Workspace-Token': token}
    session = client.post('/api/v1/learning/sessions', headers=owner, json={'lesson_id': 'dsa-complexity', 'mode': 'practice', 'language_mode': 'english'})
    assert session.status_code == 200
    recovery = setup(client, wid, token)
    client.cookies.clear()
    result, fresh = restore(client, wid, recovery)
    assert result.status_code == 200
    assert result.json()['workspace_id'] == wid
    assert client.get(f'/api/v1/studio/workspaces/{wid}/archive', headers=headers(token)).status_code == 401
    archive = client.get(f'/api/v1/studio/workspaces/{wid}/archive', headers=headers(fresh))
    assert archive.status_code == 200, archive.text
    assert archive.json()['data']['learning_sessions'][0]['id'] == session.json()['id']
    assert all(secret not in archive.text for secret in (token, fresh, recovery, 'token_hash', 'credential_hash'))
    with closing(open_connection(db)) as conn:
        assert conn.execute('SELECT count(*) FROM learning_sessions WHERE workspace_id=?', (wid,)).fetchone()[0] == 1
        stored = json.dumps([dict(row) for row in conn.execute('SELECT * FROM workspace_recovery')])
        replay = json.dumps([dict(row) for row in conn.execute('SELECT * FROM studio_idempotency')])
        assert recovery not in stored + replay and token not in replay


def test_recovery_rotation_revocation_expiry_and_owner_replay(harness):
    client, db, wid, token = harness
    old = setup(client, wid, token)
    current = setup(client, wid, token)
    assert restore(client, wid, old)[0].status_code == 401
    assert restore(client, str(uuid.uuid4()), current)[0].status_code == 401
    key = str(uuid.uuid4())
    url = f'/api/v1/studio/workspaces/{wid}/recovery'
    assert client.delete(url, headers=headers(token, key)).status_code == 200
    assert client.delete(url, headers=headers('wrong'*16, key)).status_code == 401
    assert restore(client, wid, current)[0].status_code == 401
    current = setup(client, wid, token)
    with closing(open_connection(db)) as conn:
        conn.execute("UPDATE workspace_recovery SET expires_at='2000-01-01T00:00:00+00:00' WHERE workspace_id=?", (wid,))
    assert restore(client, wid, current)[0].status_code == 401


def test_invalid_credentials_consume_durable_rate_limit(harness):
    client, db, wid, token = harness
    setup(client, wid, token)
    for _ in range(8):
        assert restore(client, wid, secrets.token_urlsafe(32))[0].status_code == 401
    assert restore(client, wid, secrets.token_urlsafe(32))[0].status_code == 429
    with closing(open_connection(db)) as conn:
        assert conn.execute('SELECT count(*) FROM workspace_recovery_attempts').fetchone()[0] == 8


def test_linked_dsa_restores_ownership_and_deletion_retains_cleanup(harness):
    client, db, wid, token = harness
    created = client.post('/api/v1/sessions', json={'exercise_id': 'ex2_binary_search', 'spec_version': 'v1_sorted_with_duplicates', 'language_mode': 'en-IN', 'interaction_mode': 'TYPED_FALLBACK'})
    assert created.status_code == 200, created.text
    session = created.json(); sid = session['session_id']
    link = f'/api/v1/studio/workspaces/{wid}/dsa-sessions/{sid}/link'
    assert client.post(link, headers=headers(token), json={'session_token': 'wrong'*16}).status_code == 401
    assert client.post(link, headers=headers(token), json={'session_token': session['session_token']}).status_code == 200
    recovery = setup(client, wid, token)
    result, fresh = restore(client, wid, recovery)
    assert result.status_code == 200
    replacement = secrets.token_urlsafe(32)
    assert client.post(f'/api/v1/studio/workspaces/{wid}/sessions/{sid}/capability', headers=headers(fresh), json={'session_token': replacement}).status_code == 200
    assert client.get(f'/api/v1/sessions/{sid}', headers=headers(session['session_token'])).status_code == 401
    assert client.get(f'/api/v1/sessions/{sid}', headers=headers(replacement)).status_code == 200
    deletion = client.delete(f'/api/v1/studio/workspaces/{wid}', headers=headers(fresh))
    assert deletion.status_code == 200, deletion.text
    assert restore(client, wid, recovery)[0].status_code == 401
    with closing(open_connection(db)) as conn:
        assert conn.execute('SELECT deleted_at FROM sessions WHERE id=?', (sid,)).fetchone()[0]
        assert conn.execute('SELECT count(*) FROM code_versions WHERE session_id=?', (sid,)).fetchone()[0] == 0
        assert conn.execute('SELECT audio_pending FROM cleanup_obligations WHERE session_id=?', (sid,)).fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM workspace_recovery WHERE workspace_id=?', (wid,)).fetchone()[0] == 0
