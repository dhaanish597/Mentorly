"""Remote PostgreSQL configuration must fail closed before network access."""
import sqlite3
import pytest
from backend.app.db.postgres.runtime import PostgresTarget, DatabaseConfigurationError


@pytest.mark.parametrize('dsn,environment', [
    ('host=localhost hostaddr=203.0.113.1 dbname=test', {}),
    ('host=remote.example dbname=test sslmode=require', {}),
    ('host=localhost dbname=test', {'PGHOSTADDR': '203.0.113.1'}),
    ('host=localhost dbname=test', {'PGSERVICE': 'untrusted'}),
])
def test_rejects_tls_bypasses_before_connect(monkeypatch, dsn, environment):
    psycopg = pytest.importorskip('psycopg')
    for key in ('PGHOSTADDR','PGSERVICE','PGOPTIONS'):
        monkeypatch.delenv(key, raising=False)
    for key, value in environment.items(): monkeypatch.setenv(key, value)
    def forbidden(*args, **kwargs): raise AssertionError('network must not be reached')
    monkeypatch.setattr(psycopg, 'connect', forbidden)
    with pytest.raises(DatabaseConfigurationError): PostgresTarget(dsn).connect()


def test_closes_connection_when_session_setup_fails(monkeypatch):
    psycopg = pytest.importorskip('psycopg')
    for key in ('PGHOSTADDR','PGSERVICE','PGOPTIONS'): monkeypatch.delenv(key, raising=False)
    class Broken:
        closed = False
        def execute(self, *args): raise psycopg.OperationalError('private connection details')
        def close(self): self.closed = True
    connection = Broken()
    monkeypatch.setattr(psycopg, 'connect', lambda *a, **k: connection)
    with pytest.raises(sqlite3.OperationalError, match='unavailable') as error:
        PostgresTarget('host=localhost dbname=test').connect()
    assert connection.closed
    assert 'private' not in str(error.value)
