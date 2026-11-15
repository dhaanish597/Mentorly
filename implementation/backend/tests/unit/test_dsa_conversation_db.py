"""DSA durable reply and deletion-budget invariants on migrated SQLite."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import sqlite3
from pathlib import Path
import shutil
import uuid

import pytest

from backend.app.db.migrations import apply_migrations, open_connection
from backend.app.db.repository import SQLiteRepository


def create_dsa_state(target):
    repo = SQLiteRepository(target)
    repo.initialize()
    sid, tid = str(uuid.uuid4()), str(uuid.uuid4())
    text = "def answer(): return 1"
    repo.create_session(session_id=sid, token_hash=sid, exercise_id="ex1_shortest_subarray", spec_version="v1_positive_only", language_mode="en-IN", interaction_mode="TEXT", starter_code=text, starter_code_hash=hashlib.sha256(text.encode()).hexdigest(), expires_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
    with closing(open_connection(target)) as conn:
        conn.execute("INSERT INTO turns(id,session_id,turn_generation,code_version_id,transport_mode,language_mode,state,created_at,updated_at) VALUES(?,?,1,1,'TEXT','en-IN','CREATED','2026-11-15','2026-11-15')", (tid, sid))
    return repo, sid, tid


def assert_dsa_storage_contract(target):
    _, sid, tid = create_dsa_state(target)
    with closing(open_connection(target)) as conn:
        for index, status in enumerate(("RESERVED", "COMMITTED", "UNCERTAIN"), 1):
            conn.execute("INSERT INTO dsa_model_usage VALUES(?,?,?,?,?,?,?)", (str(uuid.uuid4()), sid, tid, index, str(index), status, "2026-11-15T01:00:00+05:30"))
        reply = (sid, tid, 1, "hash", "Original learner words", "Adaptive reply", "AUTHORED", "2026-11-15")
        conn.execute("INSERT INTO dsa_conversation_replies VALUES(?,?,?,?,?,?,?,?)", reply)
        conn.execute("UPDATE turns SET normalized_transcript='New recording' WHERE id=?", (tid,))
        assert conn.execute("SELECT learner_transcript FROM dsa_conversation_replies WHERE turn_id=?", (tid,)).fetchone()[0] == "Original learner words"
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO dsa_conversation_replies VALUES(?,?,?,?,?,?,?,?)", reply)
        conn.execute("DELETE FROM turns WHERE id=?", (tid,))
        assert conn.execute("SELECT count(*) FROM dsa_conversation_replies").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM dsa_model_usage").fetchone()[0] == 3
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO dsa_model_usage VALUES(?,?,?,?,?,?,?)", (str(uuid.uuid4()), sid, tid, 4, "4", "RELEASED", "2026-11-15"))
        conn.execute("DELETE FROM sessions WHERE id=?", (sid,))
        assert conn.execute("SELECT count(*) FROM dsa_model_usage").fetchone()[0] == 0
        assert conn.execute("SELECT request_count FROM dsa_model_deleted_daily WHERE day='2026-11-14'").fetchone()[0] == 3


def test_dsa_reply_idempotency_and_deleted_turn_session_accounting(tmp_path):
    assert_dsa_storage_contract(tmp_path / "dsa.sqlite3")


def assert_dsa_tombstone_contract(target):
    repo, sid, tid = create_dsa_state(target)
    reserved, uncertain = str(uuid.uuid4()), str(uuid.uuid4())
    with closing(open_connection(target)) as conn:
        for index, status in enumerate(("RESERVED", "COMMITTED", "UNCERTAIN"), 1):
            conn.execute("INSERT INTO dsa_model_usage VALUES(?,?,?,?,?,?,?)", (str(uuid.uuid4()), sid, tid, index, str(index), status, "2026-11-15T01:00:00+05:30"))
        conn.execute("INSERT INTO dsa_conversation_replies VALUES(?,?,?,?,?,?,?,?)", (sid, tid, 1, "hash", "Private learner words", "Private reply", "AUTHORED", "2026-11-15"))
        conn.execute("INSERT INTO model_dispatch_leases VALUES(?,'RESERVED','2026-11-15')", (reserved,))
        conn.execute("INSERT INTO model_dispatch_leases VALUES(?,'UNCERTAIN','2026-11-15')", (uncertain,))
        assert [r[1] for r in conn.execute("PRAGMA table_info(model_dispatch_leases)")] == ["id", "status", "created_at"]
        # Trigger privacy independently of the repository's child-table cleanup.
        conn.execute("UPDATE sessions SET deleted_at='2026-11-15' WHERE id=?", (sid,))
        assert conn.execute("SELECT count(*) FROM turns WHERE session_id=?", (sid,)).fetchone()[0] == 1
        for table in ("dsa_model_usage", "dsa_conversation_replies"):
            assert conn.execute(f"SELECT count(*) FROM {table} WHERE session_id=?", (sid,)).fetchone()[0] == 0
        assert conn.execute("SELECT request_count FROM dsa_model_deleted_daily WHERE day='2026-11-14'").fetchone()[0] == 3
        assert conn.execute("SELECT count(*) FROM model_dispatch_leases").fetchone()[0] == 2
        conn.execute("UPDATE sessions SET deleted_at='2026-11-16' WHERE id=?", (sid,))
    repo.tombstone_session(sid)
    with closing(open_connection(target)) as conn:
        conn.execute("DELETE FROM sessions WHERE id=?", (sid,))
        assert conn.execute("SELECT request_count FROM dsa_model_deleted_daily WHERE day='2026-11-14'").fetchone()[0] == 3
        assert conn.execute("SELECT count(*) FROM model_dispatch_leases").fetchone()[0] == 2
        conn.execute("DELETE FROM model_dispatch_leases WHERE id=?", (reserved,))
        assert conn.execute("SELECT id,status FROM model_dispatch_leases").fetchone()[:] == (uncertain, "UNCERTAIN")
        conn.execute("DELETE FROM model_dispatch_leases WHERE id=?", (uncertain,))
        assert conn.execute("SELECT count(*) FROM model_dispatch_leases").fetchone()[0] == 0
        assert conn.execute("SELECT request_count FROM dsa_model_deleted_daily WHERE day='2026-11-14'").fetchone()[0] == 3


def test_dsa_tombstone_removes_private_linkage_without_freeing_dispatch_leases(tmp_path):
    assert_dsa_tombstone_contract(tmp_path / "tombstone.sqlite3")


def populate_prior_studio_reservations(target):
    wid, sid = str(uuid.uuid4()), str(uuid.uuid4())
    with closing(open_connection(target)) as conn:
        conn.execute("INSERT INTO studio_workspaces VALUES(?,?,'2026-11-15','2099-01-01',NULL)", (wid, "hash"))
        conn.execute("INSERT INTO studio_sessions(id,workspace_id,token_hash,mode,posture,scenario_id,scenario_version,created_at,expires_at) VALUES(?,?,'hash','design','practice','scenario','v1','2026-11-15','2099-01-01')", (sid, wid))
        for index, status in enumerate(("RESERVED", "COMMITTED", "UNCERTAIN")):
            conn.execute("INSERT INTO studio_model_usage VALUES(?,?,1,?,?,'2026-11-15')", (f"prior-private-model-{index}", sid, f"key-{index}", status))


def assert_dispatch_backfill(target):
    with closing(open_connection(target)) as conn:
        rows = conn.execute("SELECT id,status,created_at FROM model_dispatch_leases").fetchall()
        assert len(rows) == 2 and len({r[0] for r in rows}) == 2
        assert all(r[1:] == ("UNCERTAIN", "2026-11-15") for r in rows)
        assert all(not r[0].startswith("prior-private-model-") for r in rows)
        assert conn.execute("SELECT count(*) FROM studio_model_usage").fetchone()[0] == 3


def test_upgrade_backfills_only_actual_pending_model_reservations(tmp_path):
    target = tmp_path / "upgrade.sqlite3"
    directory = tmp_path / "migrations"
    directory.mkdir()
    source = Path(__file__).resolve().parents[2] / "app" / "db" / "migrations"
    for path in source.glob("*.sql"):
        if path.name != "0025_dsa_conversation.sql":
            shutil.copy2(path, directory / path.name)
    apply_migrations(target, directory)
    populate_prior_studio_reservations(target)
    shutil.copy2(source / "0025_dsa_conversation.sql", directory / "0025_dsa_conversation.sql")
    assert apply_migrations(target, directory) == ["0025"]
    assert_dispatch_backfill(target)
    assert apply_migrations(target, directory) == []
    assert_dispatch_backfill(target)
