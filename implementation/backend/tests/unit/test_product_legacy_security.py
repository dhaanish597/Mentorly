"""Unsafe legacy personalization must fail closed without touching user data."""
from contextlib import closing

from fastapi.testclient import TestClient
import pytest

from backend.app.core.config import Settings
from backend.app.db.migrations import open_connection
from backend.app.db.repository import SQLiteRepository
from backend.app.main import create_app


@pytest.mark.parametrize('method,path,payload', [
    ('GET', '/api/v1/gamification/dashboard?user_id=victim', None),
    ('GET', '/api/v1/gamification/leaderboard?user_id=new-user', None),
    ('POST', '/api/v1/gamification/quiz/submit', {'user_id': 'victim', 'quiz_id': 'anything', 'selected_option_index': -1}),
])
def test_legacy_personalization_is_retired_without_database_changes(tmp_path, method, path, payload):
    db_path = tmp_path / 'test.db'
    SQLiteRepository(db_path).initialize()
    with closing(open_connection(db_path)) as db:
        before = db.execute('SELECT COUNT(*) FROM user_profiles').fetchone()[0]
    client = TestClient(create_app(Settings(_env_file=None, database_path=db_path, env='test')))
    response = client.request(method, path, json=payload)
    assert response.status_code == 410
    assert 'learning' in response.json()['detail']
    with closing(open_connection(db_path)) as db:
        assert db.execute('SELECT COUNT(*) FROM user_profiles').fetchone()[0] == before
        assert db.execute('SELECT COUNT(*) FROM daily_quiz_attempts').fetchone()[0] == 0
