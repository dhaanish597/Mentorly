from contextlib import closing

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.db.repository import SQLiteRepository
from backend.app.db.migrations import open_connection
from backend.app.main import create_app


def test_voice_selection_persists_and_snapshot_restores_without_credentials(tmp_path):
    path = tmp_path / 'test.db'
    repo = SQLiteRepository(path)
    repo.initialize()
    client = TestClient(create_app(Settings(_env_file=None, database_path=path, env='test')))
    response = client.post('/api/v1/sessions', json={'exercise_id':'ex2_binary_search', 'spec_version':'v1_sorted_with_duplicates', 'language_mode':'hi-IN', 'spoken_language':'hi-IN', 'voice':'Shivani'})
    assert response.status_code == 200
    created = response.json()
    assert created['voice'] == 'Shivani'
    with closing(open_connection(path)) as db:
        row = db.execute('SELECT voice,spoken_language FROM sessions WHERE id=?', (created['session_id'],)).fetchone()
        assert tuple(row) == ('Shivani','hi-IN')
    snapshot = client.get('/api/v1/sessions/' + created['session_id'], headers={'Authorization':'Bearer ' + created['session_token']}).json()
    assert snapshot['voice'] == 'Shivani'
    assert snapshot['spoken_language'] == 'hi-IN'
    repo.initialize()
    assert repo.get_session(created['session_id']).voice == 'Shivani'
