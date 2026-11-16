"""Exercise the codebase mentor against a disposable PostgreSQL schema."""
from backend.tests.integration.test_postgres_runtime import runtime as runtime  # noqa: F401
from backend.tests.integration.test_product_learning_api import workspace
from backend.app.db.migrations import open_connection


def test_codebase_mentor_uses_postgres_for_session_lifecycle(runtime, monkeypatch):
    client, target = runtime
    headers = workspace(client)
    imported = client.post('/api/v1/repos/ingest', headers=headers, json={
        'source_kind': 'golden_curated', 'source_locator': 'REPO-EXP-01',
    })
    assert imported.status_code == 202, imported.text
    snapshot = imported.json()['snapshot_id']
    created = client.post('/api/v1/codebase-learning/sessions', headers=headers, json={
        'snapshot_id': snapshot, 'repo_url': 'https://github.com/example/repo',
        'repo_name': 'example/repo',
    })
    assert created.status_code == 201, created.text
    session = created.json()['session_id']
    assert client.get(f'/api/v1/codebase-learning/sessions/{session}', headers={
        'X-Workspace-Id': headers['X-Workspace-Id'], 'X-Workspace-Token': 'wrong',
    }).status_code == 401
    listed = client.get('/api/v1/codebase-learning/sessions', headers=headers)
    assert listed.status_code == 200, listed.text
    assert any(item['session_id'] == session for item in listed.json()['sessions'])
    from backend.app.repo_learning.audio_storage import store_audio, cleanup_expired_audio
    from backend.app.main import create_app
    from fastapi.testclient import TestClient
    from datetime import datetime, timedelta, timezone
    with open_connection(target) as db:
        audio_url = store_audio(db, session, b'RIFF-test')
        db.execute('UPDATE codebase_learning_messages SET audio_path=? WHERE session_id=?', (audio_url, session))
    # A separate application instance and empty cache share the database.
    settings = client.app.state.settings.model_copy(update={'tts_cache_dir': client.app.state.settings.tts_cache_dir / 'second'})
    with TestClient(create_app(settings)) as second:
        response = second.get(audio_url, headers=headers)
        assert response.status_code == 200 and response.content == b'RIFF-test'
        assert second.head(audio_url, headers=headers).status_code == 200
        other = workspace(client, 'z')
        assert second.get(audio_url, headers=other).status_code == 404
        assert second.get(audio_url).status_code == 422
        with open_connection(target) as db:
            db.execute('UPDATE codebase_learning_audio SET expires_at=?', ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),))
        assert second.get(audio_url, headers=headers).status_code == 404
        with open_connection(target) as db:
            cleanup_expired_audio(db)
            assert db.execute('SELECT count(*) FROM codebase_learning_audio').fetchone()[0] == 0
    # Two connections racing at the global cap must not both commit.
    from concurrent.futures import ThreadPoolExecutor
    from backend.app.repo_learning import audio_storage
    monkeypatch.setattr(audio_storage, 'MAX_TOTAL_AUDIO_BYTES', 6)
    def write_audio(_):
        with open_connection(target) as db:
            try:
                db.execute('BEGIN')
                store_audio(db, session, b'1234')
                db.commit()
                return 'stored'
            except ValueError:
                db.rollback()
                return 'full'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write_audio, range(2))) == ['full', 'stored']
    with open_connection(target) as db:
        assert db.execute('SELECT sum(length(wav)) FROM codebase_learning_audio').fetchone()[0] == 4
    import pytest
    with open_connection(target) as db:
        db.execute('BEGIN')
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        with pytest.raises(ValueError, match='read committed'):
            store_audio(db, session, b'1234')
        db.rollback()
    from backend.app.repo_learning.mentor_service import CodebaseMentorService
    def forbidden_provider(*args, **kwargs):
        raise AssertionError('foreign session must not reach the provider')
    monkeypatch.setattr(CodebaseMentorService, '_get_adapter', forbidden_provider)
    voice = client.post(f'/api/v1/codebase-learning/sessions/{session}/voice-turn', headers=other,
                        files={'file': ('turn.wav', b'RIFF', 'audio/wav')}, data={'locale': 'en-IN'})
    assert voice.status_code == 404


def test_scheduled_maintenance_removes_expired_audio_without_new_writes(runtime):
    import asyncio
    from datetime import datetime, timedelta, timezone
    from backend.app.db.postgres.maintenance import run_once
    from backend.app.repo_learning.audio_storage import store_audio

    client, target = runtime
    headers = workspace(client)
    imported = client.post('/api/v1/repos/ingest', headers=headers, json={
        'source_kind': 'golden_curated', 'source_locator': 'REPO-EXP-01',
    })
    created = client.post('/api/v1/codebase-learning/sessions', headers=headers, json={
        'snapshot_id': imported.json()['snapshot_id'], 'repo_url': 'https://github.com/example/repo',
        'repo_name': 'example/repo',
    })
    assert created.status_code == 201
    with open_connection(target) as db:
        store_audio(db, created.json()['session_id'], b'audio')
        db.execute('UPDATE codebase_learning_audio SET expires_at=?', ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),))
    report = asyncio.run(run_once(client.app))
    assert report['status'] == 'COMPLETE'
    assert report['expired_mentor_audio'] == 1
    with open_connection(target) as db:
        assert db.execute('SELECT count(*) FROM codebase_learning_audio').fetchone()[0] == 0
