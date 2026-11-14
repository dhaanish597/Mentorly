"""Read-only Studio request paths release their SQLite handles promptly."""
import uuid

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.db.migrations import open_connection
from backend.app.main import create_app
from backend.app.studio import routes


def test_read_endpoints_close_connections_without_waiting_for_gc(tmp_path, monkeypatch):
    settings = Settings(database_path=tmp_path / 'connections.sqlite3', tts_cache_dir=tmp_path / 'audio',
                        env='test', gnani_api_key=None, groq_api_key=None)
    with TestClient(create_app(settings)) as client:
        wid, sid = str(uuid.uuid4()), str(uuid.uuid4())
        client.post('/api/v1/studio/workspaces', json={'workspace_id':wid,'workspace_token':'w'*48},
                    headers={'X-Idempotency-Key':'connection-workspace'})
        created = client.post('/api/v1/studio/sessions', json={'workspace_id':wid,'session_id':sid,
                              'session_token':'s'*48,'mode':'dsa_to_system_bridge','posture':'teaching','scenario_id':'SD-BR-01'},
                              headers={'Authorization':'Bearer '+'w'*48,'X-Idempotency-Key':'connection-session'})
        assert created.status_code == 200
        observed = []

        class ObservedConnection:
            def __init__(self, conn):
                self.conn = conn
                self.closed = False

            def __getattr__(self, name):
                return getattr(self.conn, name)

            def close(self):
                self.conn.close()
                self.closed = True

        def tracked(request):
            conn = ObservedConnection(open_connection(request.app.state.settings.database_path))
            observed.append(conn)
            return conn

        monkeypatch.setattr(routes, 'connection', tracked)
        for suffix in ('', '/scenario', '/evaluation', '/summary', '/diagrams', '/export'):
            response = client.get(f'/api/v1/studio/sessions/{sid}{suffix}', headers={'Authorization':'Bearer '+'s'*48})
            assert response.status_code == 200
        assert len(observed) >= 6
        assert all(conn.closed for conn in observed)
