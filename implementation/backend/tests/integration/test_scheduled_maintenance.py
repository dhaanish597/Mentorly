"""Scheduled maintenance must authenticate before accessing storage."""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.app.core.errors import register_exception_handlers
from backend.app.db.postgres.runtime import PostgresTarget
from backend.app.operations import maintenance


def test_maintenance_authentication_and_repeat(monkeypatch):
    app = FastAPI()
    app.state.settings = SimpleNamespace(operations_token=SecretStr('x' * 32))
    register_exception_handlers(app)
    app.include_router(maintenance.router, prefix='/api/v1')
    calls = []
    target = PostgresTarget('host=localhost dbname=synthetic')
    monkeypatch.setattr(maintenance, 'database_target', lambda _: target)

    async def sweep(application):
        calls.append(application)
        return {'status': 'COMPLETE', 'expired_sessions': 42}

    monkeypatch.setattr(maintenance, 'run_once', sweep)
    with TestClient(app) as client:
        assert client.get('/api/v1/ops/maintenance').status_code == 403
        assert client.get('/api/v1/ops/maintenance', headers={'Authorization': 'Bearer incorrect'}).status_code == 403
        assert not calls
        for _ in range(2):
            response = client.get('/api/v1/ops/maintenance', headers={'Authorization': 'Bearer ' + 'x' * 32})
            assert response.status_code == 200
            assert response.json() == {'status': 'complete'}
    assert calls == [app, app]


def test_maintenance_failure_is_not_reported_as_success(monkeypatch):
    app = FastAPI()
    app.state.settings = SimpleNamespace(operations_token=SecretStr('x' * 32))
    register_exception_handlers(app)
    app.include_router(maintenance.router, prefix='/api/v1')
    monkeypatch.setattr(maintenance, 'database_target', lambda _: PostgresTarget('host=localhost dbname=synthetic'))

    async def busy(_):
        return {'status': 'BUSY', 'errors': 0}

    monkeypatch.setattr(maintenance, 'run_once', busy)
    with TestClient(app) as client:
        response = client.get('/api/v1/ops/maintenance', headers={'Authorization': 'Bearer ' + 'x' * 32})
        assert response.status_code == 503
        assert 'BUSY' not in response.text


from backend.tests.integration.test_postgres_runtime import runtime as runtime  # noqa: F401


def test_scheduled_endpoint_cleans_expired_audio_in_postgres(runtime):
    from datetime import datetime, timedelta, timezone

    from backend.app.db.migrations import open_connection
    from backend.app.repo_learning.audio_storage import store_audio
    from backend.tests.integration.test_product_learning_api import workspace

    client, target = runtime
    client.app.state.settings.operations_token = SecretStr('x' * 32)
    headers = workspace(client)
    imported = client.post('/api/v1/repos/ingest', headers=headers, json={
        'source_kind': 'golden_curated', 'source_locator': 'REPO-EXP-01',
    })
    assert imported.status_code == 202
    created = client.post('/api/v1/codebase-learning/sessions', headers=headers, json={
        'snapshot_id': imported.json()['snapshot_id'], 'repo_url': 'https://example.test/repo',
        'repo_name': 'synthetic',
    })
    assert created.status_code == 201
    with open_connection(target) as db:
        store_audio(db, created.json()['session_id'], b'audio')
        db.execute('UPDATE codebase_learning_audio SET expires_at=?',
                   ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),))
    assert client.get('/api/v1/ops/maintenance').status_code == 403
    with open_connection(target) as db:
        assert db.execute('SELECT count(*) FROM codebase_learning_audio').fetchone()[0] == 1
    for _ in range(2):
        response = client.get('/api/v1/ops/maintenance', headers={'Authorization': 'Bearer ' + 'x' * 32})
        assert response.status_code == 200, response.text
        assert response.json() == {'status': 'complete'}
    with open_connection(target) as db:
        assert db.execute('SELECT count(*) FROM codebase_learning_audio').fetchone()[0] == 0
