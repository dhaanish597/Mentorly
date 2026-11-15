"""Real runtime acceptance using a disposable local PostgreSQL database.

VIVA_POSTGRES_RUNTIME_TEST_DSN must name a local dedicated test cluster. Every
test creates a random private schema and drops only that schema in teardown.
These tests make no speech/model calls and are not cloud deployment acceptance.
"""
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import multiprocessing
import os
import sqlite3
import shutil
from pathlib import Path
import uuid

import pytest

from backend.app.db.migrations import apply_migrations, get_applied_migrations, MigrationError, open_connection
from backend.app.db.postgres.runtime import PostgresTarget, _raw_connection, probe_runtime
from backend.app.db.repository import SQLiteRepository, RevisionConflictError, IdempotencyConflictError

DSN = os.environ.get("VIVA_POSTGRES_RUNTIME_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="set VIVA_POSTGRES_RUNTIME_TEST_DSN to a disposable local cluster")


@pytest.fixture
def target():
    psycopg = pytest.importorskip("psycopg")
    host = psycopg.conninfo.conninfo_to_dict(DSN).get("host", "")
    assert host.startswith("/") or host in {"localhost", "127.0.0.1", "::1"}, "Runtime tests require a local disposable cluster"
    value = PostgresTarget(DSN, schema="viva_runtime_test_" + uuid.uuid4().hex, allow_local=True)
    try:
        apply_migrations(value)
        yield value
    finally:
        with _raw_connection(value) as admin:
            admin.execute(psycopg.sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(psycopg.sql.Identifier(value.schema)))


def workspace(conn, wid=None):
    wid = wid or str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc)
    conn.execute("INSERT INTO studio_workspaces VALUES(?,?,?,?,NULL)", (wid, "capability-digest", timestamp.isoformat(), (timestamp + timedelta(days=1)).isoformat()))
    return wid


def session(target):
    repo = SQLiteRepository(target)
    sid = str(uuid.uuid4())
    source = "def answer():\n    return 1\n"
    repo.create_session(session_id=sid, token_hash=sid, exercise_id="ex1_shortest_subarray", spec_version="v1_positive_only", language_mode="en-IN", interaction_mode="TEXT", starter_code=source, starter_code_hash=hashlib.sha256(source.encode()).hexdigest(), expires_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
    return repo, sid


def test_complete_schema_columns_indexes_constraints_and_history(target, tmp_path):
    local = tmp_path / "source.sqlite3"
    apply_migrations(local)
    from backend.app.speech.gatekeeper import SpeechGatekeeper
    from backend.app.speech.gnani_adapter import GnaniSpeechAdapter
    gate = SpeechGatekeeper(GnaniSpeechAdapter(api_key=''), db_path=local)
    gate._conn.close()
    with closing(open_connection(local)) as source, closing(open_connection(target)) as postgres:
        names = [row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'") if not row[0].startswith("repo_chunks_fts")]
        for name in names:
            assert [r[1] for r in source.execute(f"PRAGMA table_info({name})")] == [r[1] for r in postgres.execute(f"PRAGMA table_info({name})")], name
        source_indexes = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL")}
        pg_indexes = {r[0] for r in postgres.execute("SELECT indexname FROM pg_indexes WHERE schemaname=current_schema()")}
        assert source_indexes <= pg_indexes
        for name in names:
            foreign_keys = list(source.execute(f"PRAGMA foreign_key_list({name})"))
            pg_keys = postgres.execute("SELECT count(*) FROM information_schema.table_constraints WHERE table_schema=current_schema() AND table_name=? AND constraint_type='FOREIGN KEY'", (name,)).fetchone()[0]
            assert len({row[0] for row in foreign_keys}) == pg_keys, name
        assert postgres.execute("SELECT count(*) FROM information_schema.triggers WHERE trigger_schema=current_schema()").fetchone()[0] == 23
        assert postgres.execute("SELECT count(*) FROM user_profiles").fetchone()[0] == 0
    assert apply_migrations(target) == []
    assert [m.version for m in get_applied_migrations(target)] == ["0001", "0002", "0003", "0004", "0005", "0006", "0007", "0008"]
    assert probe_runtime(target)


def test_secret_safe_target_and_remote_tls_policy():
    secret = "password-do-not-disclose"
    remote = PostgresTarget(f"host=db.example.com user=postgres password={secret} dbname=postgres sslmode=verify-full")
    assert secret not in str(remote) and secret not in repr(remote)
    for invalid in (f"host=db.example.com password={secret} sslmode=require", "host=localhost dbname=postgres", "host=one,two sslmode=verify-full", "host=db.example.com sslmode=verify-full options='-c search_path=public'"):
        with pytest.raises(ValueError) as error:
            PostgresTarget(invalid)
        assert secret not in str(error.value)


def test_readonly_probe_detects_missing_runtime_structure(target):
    assert probe_runtime(target)
    with closing(open_connection(target)) as conn:
        assert conn.execute("SELECT count(*) FROM pg_namespace n,aclexplode(n.nspacl) a WHERE n.nspname=current_schema() AND a.grantee=0").fetchone()[0] == 0
        conn.execute("DROP TABLE cloud_audio")
    assert not probe_runtime(target)


def test_atomic_rollback_and_checksum_drift(target, tmp_path):
    other = replace(target, schema="viva_runtime_rollback_" + uuid.uuid4().hex)
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "0001_probe.sql").write_text("CREATE TABLE rollback_probe(id TEXT PRIMARY KEY);")
    (directory / "0002_bad.sql").write_text("INSERT INTO nonexistent VALUES(1);")
    try:
        with pytest.raises(MigrationError, match="rolled back"):
            apply_migrations(other, directory)
        with _raw_connection(other) as admin:
            assert admin.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (other.schema,)).fetchone() is None
        (directory / "0002_bad.sql").write_text("INSERT INTO rollback_probe VALUES('ok');")
        assert apply_migrations(other, directory) == ["0001", "0002"]
        (directory / "0001_probe.sql").write_text("CREATE TABLE rollback_probe(id TEXT);")
        with pytest.raises(MigrationError, match="history"):
            apply_migrations(other, directory)
        with closing(open_connection(other)) as conn:
            assert conn.execute("SELECT id FROM rollback_probe").fetchone()[0] == "ok"
    finally:
        with _raw_connection(other) as admin:
            admin.execute(f'DROP SCHEMA IF EXISTS "{other.schema}" CASCADE')


def test_rows_placeholders_utf8_bytes_json_and_utc_dates(target):
    with closing(open_connection(target)) as conn:
        row = conn.execute("SELECT ? AS name, '?' AS literal, 'date(' AS untouched, 3 AS number", ("100% है \\ text",)).fetchone()
        assert dict(row) == {"name": "100% है \\ text", "literal": "?", "untouched": "date(", "number": 3}
        assert tuple(row) == ("100% है \\ text", "?", "date(", 3)
        assert row["NAME"] == row[0]
        assert conn.execute("SELECT length(CAST(? AS BLOB))", ("है",)).fetchone()[0] == len("है".encode())
        assert conn.execute("SELECT date(?), date(?), date(?,'-2 days')", ("2026-11-15T01:00:00+05:30", "invalid", "2026-11-15")).fetchone()[:] == ("2026-11-14", None, "2026-11-13")
        assert conn.execute("SELECT json_extract(?,'$.text'),json_extract(?,'$.number')", ('{"text":"है"}', '{"number":4}')).fetchone()[:] == ("है", "4")
        assert conn.execute("SELECT 1 FROM json_each(?) WHERE json_extract(value,'$.turn_id')=?", ('[{"turn_id":"a"},{"turn_id":"b"}]', "b")).fetchone()[0] == 1
        for value, expected in ((1, True), (True, True), ("1", False), (False, False)):
            found = conn.execute("SELECT 1 FROM (SELECT ? AS payload_json) AS source WHERE json_extract(payload_json,'$.assistance')=1", (json.dumps({"assistance": value}),)).fetchone()
            assert (found is not None) == expected
        assert conn.execute("SELECT CAST(? AS TEXT) IS NULL", (None,)).fetchone()[0]
        with pytest.raises(sqlite3.OperationalError, match="Unsupported"):
            conn.execute("PRAGMA quick_check")


def test_transaction_context_commits_rolls_back_and_remains_open(target):
    with closing(open_connection(target)) as conn:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            workspace(conn, "committed")
        with pytest.raises(RuntimeError):
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                workspace(conn, "rolled-back")
                raise RuntimeError("abort")
        assert [r[0] for r in conn.execute("SELECT id FROM studio_workspaces")] == ["committed"]
        assert not conn.in_transaction


def _increment(target, repetitions):
    with closing(open_connection(target)) as conn:
        for _ in range(repetitions):
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute("SELECT request_count FROM admission_counters").fetchone()[0]
            conn.execute("UPDATE admission_counters SET request_count=?", (current + 1,))
            conn.commit()
    return repetitions


def test_independent_processes_share_writer_serialization(target):
    with closing(open_connection(target)) as conn:
        conn.execute("INSERT INTO admission_counters VALUES('test','digest',1,0)")
    with ProcessPoolExecutor(max_workers=4, mp_context=multiprocessing.get_context("spawn")) as pool:
        assert sum(pool.map(_increment, [target] * 4, [8] * 4)) == 32
    with closing(open_connection(target)) as conn:
        assert conn.execute("SELECT request_count FROM admission_counters").fetchone()[0] == 32


def test_repository_cas_and_tombstone_cleanup(target):
    repo, sid = session(target)
    def save(number):
        try:
            return repo.save_code_version(sid, expected_code_version_id=1, source_code=f"def answer(): return {number}", code_hash=str(number)).changed
        except RevisionConflictError:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(save, [2, 3]), key=str) == [True, "conflict"]
    assert repo.get_session(sid).active_code_version_id == 2
    assert repo.get_prior_failing_input(sid, None) is None
    assert repo.get_prior_failing_artifact_id(sid, None) is None
    repo.tombstone_session(sid)
    assert repo.get_session(sid) is None
    with closing(open_connection(target)) as conn:
        assert conn.execute("SELECT audio_pending FROM cleanup_obligations WHERE session_id=?", (sid,)).fetchone()[0] == 1


def test_repository_ingestion_native_search_and_delete(target):
    from backend.app.repo_learning import service
    with closing(open_connection(target)) as conn:
        wid = workspace(conn)
    result = service.create(target, wid, "zip", {"main.py": 'def validate_capability():\n    return "है \\ value"\n'}, {"total": 1})
    assert result["status"] == "READY"
    assert len(service.search(target, wid, result["snapshot_id"], "validate_capability missing")["results"]) == 1
    service.delete(target, wid, result["snapshot_id"])
    with closing(open_connection(target)) as conn:
        assert conn.execute("SELECT count(*) FROM repo_chunks_fts").fetchone()[0] == 0


def test_repository_idempotent_import_and_request_conflict(target):
    from backend.app.repo_learning import service, idempotency
    with closing(open_connection(target)) as conn:
        wid = workspace(conn)
    first, dispatch = service.queue_import(target, wid, "zip", None, "digest", "retry-key")
    second, repeated_dispatch = service.queue_import(target, wid, "zip", None, "digest", "retry-key")
    assert first == second and dispatch and not repeated_dispatch
    with pytest.raises(idempotency.IdempotencyConflict):
        service.queue_import(target, wid, "zip", None, "changed", "retry-key")
    with closing(open_connection(target)) as conn:
        assert conn.execute("SELECT count(*) FROM repo_snapshots").fetchone()[0] == 1


def test_session_idempotency_conflicting_requests_are_atomic(target):
    repo, sid = session(target)
    expires = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    def remember(digest):
        try:
            return repo.save_idempotency(session_id=sid, method="POST", route="/test", idempotency_key="key", request_digest=digest, status="COMPLETE", response_json='{"ok":true}', expires_at=expires).request_digest
        except IdempotencyConflictError:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(remember, ["first", "second"]))
    assert result.count("conflict") == 1
    with closing(open_connection(target)) as conn:
        assert conn.execute("SELECT count(*) FROM idempotency_records").fetchone()[0] == 1


def test_trusted_replace_preserves_delete_cascade_and_rollback(target):
    _, sid = session(target)
    with closing(open_connection(target)) as conn:
        params = ("message", sid, 1, "initial", "2026-11-15")
        statement = "INSERT OR REPLACE INTO coaching_messages(id,session_id,hint_level,text,created_at) VALUES(?,?,?,?,?)"
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(statement, params)
        conn.commit()
        conn.execute("INSERT INTO speech_jobs(id,session_id,coaching_message_id,playback_id,code_version_id,turn_generation,normalized_text_hash,mode,status,expires_at,created_at) VALUES(?,?,?,'playback',1,0,'hash','CACHED','READY','2099-01-01','2026-11-15')", ("speech", sid, "message"))
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(statement, ("message", "missing-session", 1, "changed", "2026-11-15"))
        conn.rollback()
        assert conn.execute("SELECT text FROM coaching_messages").fetchone()[0] == "initial"
        assert conn.execute("SELECT count(*) FROM speech_jobs").fetchone()[0] == 1
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(statement, ("message", sid, 1, "changed", "2026-11-15"))
        conn.commit()
        assert conn.execute("SELECT text FROM coaching_messages").fetchone()[0] == "changed"
        assert conn.execute("SELECT count(*) FROM speech_jobs").fetchone()[0] == 0


def test_learning_completion_cannot_use_missing_or_foreign_evidence(target):
    from backend.app.learning import service
    with closing(open_connection(target)) as conn:
        wid, foreign = workspace(conn), workspace(conn)
        state = service.create_session(conn, wid, "dsa-complexity", "en-IN")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE learning_sessions SET state='completed' WHERE id=?", (state["id"],))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO learning_answers VALUES(?,?,?,?,?,?,?,?,?,?)", ("foreign", state["id"], foreign, 1, 1, "question", "A", 1, "{}", "2026-11-15"))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO learning_events VALUES(?,?,?,?,?,?,?,?,?)", ("event", wid, state["id"], 1, "lesson.completed", "learning_engine", None, 0, "2026-11-15"))
        assert conn.execute("SELECT count(*) FROM learning_answers").fetchone()[0] == 0


def test_learning_real_service_evidence_and_soft_delete(target):
    from backend.app.learning import service
    from backend.app.learning.catalog import lesson_by_id
    with closing(open_connection(target)) as conn:
        wid = workspace(conn)
        conn.execute("BEGIN IMMEDIATE")
        state = service.create_session(conn, wid, "dsa-complexity", "en-IN")
        lesson = lesson_by_id("dsa-complexity")
        state = service.answer_session(conn, wid, state["id"], state["epoch"], state["question"]["id"], lesson["question"]["correct_answer"])
        conn.commit()
        assert state["state"] == "completed"
        assert conn.execute("SELECT count(*) FROM learning_achievements").fetchone()[0] == 1
        for table in ("learning_answers", "learning_events", "learning_achievements"):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(f"UPDATE {table} SET workspace_id=workspace_id")
        conn.execute("UPDATE studio_workspaces SET deleted_at=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), wid))
        for table in ("learning_sessions", "learning_answers", "learning_events", "learning_achievements"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_interview_report_bridge_and_soft_delete(target):
    from backend.app.interviews import service
    from backend.app.interviews.schemas import NewSession
    from backend.app.learning.service import record_interview_completion
    with closing(open_connection(target)) as conn:
        wid = workspace(conn)
        conn.execute("BEGIN IMMEDIATE")
        state = service.create(conn, wid, NewSession(type="dsa", difficulty="beginner", topics=[], duration_minutes=15, language_mode="en-IN"))
        row = service.owned(conn, state["id"], wid)
        service.complete(conn, row, "user_ended", record_interview_completion)
        conn.commit()
        assert conn.execute("SELECT count(*) FROM learning_external_events").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE interview_reports SET report_json='{}'")
        conn.execute("UPDATE studio_workspaces SET deleted_at=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), wid))
        for table in ("interview_sessions", "interview_reports", "learning_external_events", "learning_evidence_achievements"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_deleted_speech_credit_and_audio_budget_retained(target):
    with closing(open_connection(target)) as conn:
        wid = workspace(conn)
        for number in range(2):
            conn.execute("INSERT INTO module_speech_usage VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (str(number), wid, "source", "lesson", 1, "STT", 2.5, 20, 2, "UNCERTAIN", "2026-11-15T01:00:00+05:30", "2026-11-15T01:00:00+05:30"))
        conn.execute("UPDATE studio_workspaces SET deleted_at='2026-11-15' WHERE id=?", (wid,))
        assert conn.execute("SELECT request_count FROM studio_speech_deleted_daily WHERE day='2026-11-14'").fetchone()[0] == 4
        assert conn.execute("SELECT stt_seconds,tts_chars FROM module_speech_deleted_totals WHERE day='2026-11-14'").fetchone()[:] == (5.0, 40)
        assert conn.execute("SELECT count(*) FROM module_speech_usage").fetchone()[0] == 0


def test_dsa_reply_and_deleted_turn_session_accounting(target):
    from backend.tests.unit.test_dsa_conversation_db import assert_dsa_storage_contract
    assert_dsa_storage_contract(target)


def test_dsa_tombstone_removes_private_linkage_without_freeing_dispatch_leases(target):
    from backend.tests.unit.test_dsa_conversation_db import assert_dsa_tombstone_contract
    assert_dsa_tombstone_contract(target)


def test_upgrade_backfills_only_actual_pending_model_reservations(target, tmp_path):
    from backend.tests.unit.test_dsa_conversation_db import assert_dispatch_backfill, populate_prior_studio_reservations
    other = replace(target, schema="viva_dispatch_upgrade_" + uuid.uuid4().hex)
    source = Path(__file__).resolve().parents[2] / "app" / "db" / "postgres" / "runtime_migrations"
    directory = tmp_path / "migrations"
    directory.mkdir()
    try:
        for path in source.glob("*.sql"):
            if path.name.split('_', 1)[0] < '0005':
                shutil.copy2(path, directory / path.name)
        apply_migrations(other, directory)
        populate_prior_studio_reservations(other)
        shutil.copy2(source / "0005_dsa_conversation.sql", directory / "0005_dsa_conversation.sql")
        assert apply_migrations(other, directory) == ["0005"]
        assert_dispatch_backfill(other)
        assert apply_migrations(other, directory) == []
        assert_dispatch_backfill(other)
    finally:
        with _raw_connection(other) as admin:
            admin.execute(f'DROP SCHEMA IF EXISTS "{other.schema}" CASCADE')
