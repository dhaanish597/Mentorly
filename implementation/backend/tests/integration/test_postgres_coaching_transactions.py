"""Opt-in experimental coaching transaction tests against a dedicated database."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import os
from datetime import datetime, timedelta, timezone
import time
import threading
import uuid

import pytest

from backend.app.db.postgres import apply_migrations
from backend.app.db.postgres.core import CORE_MIGRATION
from backend.app.db.postgres.coaching import AuthorizationError, Revision, RevisionConflictError, save_code_version

DSN = os.environ.get("VIVA_POSTGRES_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="set VIVA_POSTGRES_TEST_DSN to a dedicated test database")


def test_code_save_authorization_compare_and_swap_and_delete_race():
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql
    schema = "viva_tx_test_" + uuid.uuid4().hex
    token = "a" * 64
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            def connect():
                conn = psycopg.connect(DSN)
                conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
                conn.commit()
                return conn
            def save(conn, expected, **kwargs):
                return save_code_version(conn, session_id="s", token_hash=kwargs.pop("token_hash", token),
                                         expected=expected, source_code=kwargs.pop("source_code", "new"),
                                         code_hash=kwargs.pop("code_hash", "newhash"), **kwargs)
            revision = Revision("s", "e", "v", 1, "oldhash", 0)
            with connect() as conn:
                apply_migrations(conn, [CORE_MIGRATION])
                conn.execute("INSERT INTO sessions (id,token_hash,exercise_id,spec_version,language_mode,interaction_mode,created_at,updated_at,expires_at) VALUES ('s',%s,'e','v','en','text','t','t','2099-01-01T00:00:00+00:00')", (token,))
                conn.execute("INSERT INTO code_versions (id,session_id,code_version_id,source_code,code_hash,created_at) VALUES ('cv','s',1,'old','oldhash','t')")
                conn.execute("INSERT INTO turns (id,session_id,turn_generation,code_version_id,transport_mode,language_mode,state,created_at,updated_at) VALUES ('turn','s',0,1,'text','en','CREATED','t','t')")
                conn.execute("INSERT INTO jobs (id,session_id,job_type,status,turn_generation,code_version_id,created_at,updated_at) VALUES ('job','s','run','RUNNING',0,1,'t','t')")
                conn.commit()
                with pytest.raises(AuthorizationError):
                    save(conn, revision, token_hash="b" * 64)
                conn.execute("UPDATE sessions SET expires_at='2000-01-01T00:00:00+00:00' WHERE id='s'")
                conn.commit()
                with pytest.raises(AuthorizationError):
                    save(conn, revision)
                conn.execute("UPDATE sessions SET expires_at='not-a-time' WHERE id='s'")
                conn.commit()
                with pytest.raises(AuthorizationError):
                    save(conn, revision)
                conn.execute("UPDATE sessions SET expires_at='2099-01-01T00:00:00+00:00' WHERE id='s'")
                conn.commit()
                no_op = save(conn, revision, source_code="old", code_hash="oldhash", client_edit_sequence=1)
                assert not no_op.changed and no_op.latest_client_edit_sequence == 1
                with pytest.raises(RevisionConflictError):
                    save(conn, revision, client_edit_sequence=1)
            barrier = threading.Barrier(2)
            def competing_save():
                with connect() as conn:
                    barrier.wait(timeout=10)
                    try:
                        return save(conn, revision, client_edit_sequence=2)
                    except RevisionConflictError:
                        return None
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = [f.result(timeout=20) for f in [pool.submit(competing_save) for _ in range(2)]]
            assert sum(item is not None for item in results) == 1
            with connect() as conn:
                assert conn.execute("SELECT active_code_version_id,active_turn_generation,latest_client_edit_sequence FROM sessions WHERE id='s'").fetchone() == (2, 1, 2)
                assert conn.execute("SELECT state FROM turns WHERE id='turn'").fetchone() == ("SUPERSEDED",)
                assert conn.execute("SELECT status FROM jobs WHERE id='job'").fetchone() == ("SUPERSEDED",)
                conn.rollback()
                with pytest.raises(RevisionConflictError):
                    save(conn, revision, client_edit_sequence=3)
                assert conn.execute("SELECT latest_client_edit_sequence FROM sessions WHERE id='s'").fetchone() == (2,)
                conn.rollback()
            # The credential expires while a concurrent transaction holds the row lock.
            begun_expiry = threading.Event()
            current = Revision("s", "e", "v", 2, "newhash", 1)
            with connect() as locker, ThreadPoolExecutor(max_workers=1) as pool:
                expiry = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
                locker.execute("UPDATE sessions SET expires_at=%s WHERE id='s'", (expiry,))
                def expiring_save():
                    with connect() as conn:
                        begun_expiry.set()
                        with pytest.raises(AuthorizationError):
                            save(conn, current, client_edit_sequence=3)
                future = pool.submit(expiring_save)
                assert begun_expiry.wait(10)
                with pytest.raises(TimeoutError):
                    future.result(timeout=0.2)
                time.sleep(1.1)
                locker.commit()
                future.result(timeout=20)
            with connect() as conn:
                assert conn.execute("SELECT latest_client_edit_sequence FROM sessions WHERE id='s'").fetchone() == (2,)
                conn.execute("UPDATE sessions SET expires_at='2099-01-01T00:00:00+00:00' WHERE id='s'")
                conn.commit()
            # A deletion transaction holds the same row lock. A waiting save
            # must observe the committed tombstone before it can write.
            begun = threading.Event()
            current = Revision("s", "e", "v", 2, "newhash", 1)
            with connect() as deleter, ThreadPoolExecutor(max_workers=1) as pool:
                deleter.execute("UPDATE sessions SET deleted_at='t',state='DELETED' WHERE id='s'")
                def waiting_save():
                    with connect() as conn:
                        begun.set()
                        with pytest.raises(AuthorizationError):
                            save(conn, current, client_edit_sequence=3)
                future = pool.submit(waiting_save)
                assert begun.wait(10)
                with pytest.raises(TimeoutError):
                    future.result(timeout=0.2)
                deleter.commit()
                future.result(timeout=20)
            with connect() as conn:
                assert conn.execute("SELECT count(*) FROM code_versions WHERE session_id='s'").fetchone() == (2,)
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
