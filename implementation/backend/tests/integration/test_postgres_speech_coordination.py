"""Opt-in experimental speech coordination tests using a dedicated PostgreSQL DB."""
from concurrent.futures import ThreadPoolExecutor
import os
import threading
import time
import uuid

import pytest

from backend.app.db.postgres import apply_migrations
from backend.app.db.postgres.core import CORE_MIGRATION
from backend.app.db.postgres.speech_coordination import (
    SPEECH_MIGRATION, CoordinationError, Lease, configure, reserve, start,
    release_unstarted, complete,
)

DSN = os.environ.get("VIVA_POSTGRES_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="set VIVA_POSTGRES_TEST_DSN to a dedicated test database")


def test_global_capacity_budget_fencing_and_conservative_recovery():
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql
    schema = "viva_speech_test_" + uuid.uuid4().hex
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            def connect():
                conn = psycopg.connect(DSN)
                conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
                conn.commit()
                return conn
            with connect() as conn:
                apply_migrations(conn, [CORE_MIGRATION, SPEECH_MIGRATION])
                configure(conn, max_slots=2, max_stt_ms=1000, max_tts_chars=100, max_calls=10)
                with pytest.raises(ValueError):
                    reserve(conn, stt_ms=1, tts_chars=0, calls=2, lease_seconds=5)
                with pytest.raises(CoordinationError):
                    configure(conn, max_slots=3, max_stt_ms=1000, max_tts_chars=100, max_calls=10)
            barrier = threading.Barrier(4)
            def attempt():
                with connect() as conn:
                    barrier.wait(timeout=10)
                    try:
                        return reserve(conn, stt_ms=400, tts_chars=10, calls=1, lease_seconds=2)
                    except CoordinationError:
                        return None
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = [future.result(timeout=15) for future in [pool.submit(attempt) for _ in range(4)]]
            leases = [item for item in results if item is not None]
            assert len(leases) == 2 and leases[0].fence != leases[1].fence
            with connect() as conn:
                with pytest.raises(CoordinationError):
                    start(conn, Lease(leases[0].reservation_id, leases[0].fence + 100))
                start(conn, leases[0])
                start(conn, leases[1])
                complete(conn, leases[0])
                with pytest.raises(CoordinationError):
                    complete(conn, leases[0])
                with pytest.raises(CoordinationError):
                    reserve(conn, stt_ms=201, tts_chars=0, calls=1, lease_seconds=5)
                time.sleep(2.1)
                with pytest.raises(CoordinationError):
                    complete(conn, leases[1])
                assert conn.execute("SELECT state FROM viva_speech_reservations WHERE id=%s", (leases[1].reservation_id,)).fetchone() == ("STARTED",)
                conn.rollback()  # A rejected transaction rolls back lazy expiry marking.
                # Even if the provider is presently idle, a paused worker may
                # dispatch later. Its expired lease remains budgeted and occupied.
                with pytest.raises(CoordinationError):
                    reserve(conn, stt_ms=201, tts_chars=0, calls=1, lease_seconds=5)
                probe = reserve(conn, stt_ms=200, tts_chars=0, calls=1, lease_seconds=5)
                with pytest.raises(CoordinationError):
                    reserve(conn, stt_ms=0, tts_chars=0, calls=1, lease_seconds=5)
                release_unstarted(conn, probe)
                with pytest.raises(CoordinationError):
                    start(conn, leases[1])
                assert conn.execute("SELECT state,count(*) FROM viva_speech_reservations GROUP BY state ORDER BY state").fetchall() == [("COMMITTED",1),("RELEASED",1),("UNCERTAIN",1)]
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
