"""Opt-in authenticated read and lock ordering tests."""
import hashlib
import os
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.db.postgres import apply_migrations
from backend.app.db.postgres.coaching import AuthorizationError
from backend.app.db.postgres.core import CORE_MIGRATION
from backend.app.db.postgres.repository import PostgresRepository

DSN = os.environ.get('VIVA_POSTGRES_TEST_DSN')
pytestmark = pytest.mark.skipif(not DSN, reason='set VIVA_POSTGRES_TEST_DSN to a dedicated test database')


def test_authorized_reads_and_deletion_expiry_races():
    psycopg = pytest.importorskip('psycopg')
    from psycopg import sql
    schema = 'viva_repo_reads_' + uuid.uuid4().hex
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            def connect():
                return psycopg.connect(DSN, options=f'-c search_path={schema}')
            expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            digest = hashlib.sha256(b'token').hexdigest()
            with connect() as conn:
                apply_migrations(conn, [CORE_MIGRATION])
                conn.execute('''INSERT INTO sessions (id,token_hash,exercise_id,spec_version,language_mode,
                    interaction_mode,created_at,updated_at,expires_at) VALUES
                    ('one',%s,'e','v','en','text','a','a',%s),
                    ('two',%s,'e','v','en','text','a','a',%s)''',
                    (digest,expiry,hashlib.sha256(b'other').hexdigest(),expiry))
                conn.execute('''INSERT INTO code_versions (id,session_id,code_version_id,source_code,code_hash,created_at)
                    VALUES ('c1','one',1,'secret1','h1','a'),('c2','two',1,'secret2','h2','a')''')
            repo = PostgresRepository(connect)
            view = repo.get_session('one', token='token')
            assert view.id == 'one' and 'token_hash' not in asdict(view)
            assert repo.get_code_version('one', 1, token='token').source_code == 'secret1'
            assert repo.get_code_version('one', 2, token='token') is None
            for sid, token in [('one','wrong'), ('two','token'), ('missing','token'), ("one' OR TRUE --",'token')]:
                with pytest.raises(AuthorizationError):
                    repo.get_session(sid, token=token)
                with pytest.raises(AuthorizationError):
                    repo.get_code_version(sid, 1, token=token)
            # Hold the lock, start the private read, then commit deletion/expiry.
            # The blocked reader must recheck after acquiring the lock.
            for update in ("deleted_at='now'", "expires_at='2000-01-01T00:00:00+00:00'"):
                with connect() as conn:
                    conn.execute("UPDATE sessions SET deleted_at=NULL,expires_at=%s WHERE id='one'", (expiry,))
                started = threading.Event()
                outcomes = []
                reader_pid = []
                def reader_connect():
                    conn = connect()
                    reader_pid.append(conn.info.backend_pid)
                    started.set()
                    return conn
                reader = PostgresRepository(reader_connect)
                with connect() as locker:
                    locker.execute("SELECT id FROM sessions WHERE id='one' FOR UPDATE")
                    def read():
                        try:
                            reader.get_code_version('one', 1, token='token')
                            outcomes.append('returned')
                        except AuthorizationError:
                            outcomes.append('denied')
                    thread = threading.Thread(target=read)
                    thread.start()
                    assert started.wait(2)
                    deadline = time.monotonic() + 5
                    blocked = 0
                    while time.monotonic() < deadline:
                        blocked = admin.execute('SELECT cardinality(pg_blocking_pids(%s))', (reader_pid[0],)).fetchone()[0]
                        if blocked:
                            break
                        time.sleep(0.01)
                    assert blocked, 'reader never blocked on the session row'
                    locker.execute('UPDATE sessions SET ' + update + " WHERE id='one'")
                    locker.commit()
                    thread.join(5)
                    assert not thread.is_alive() and outcomes == ['denied']
        finally:
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
