"""Unit tests for SQLite WAL migrations, rollback/recovery, and Phase 0 repository."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest

from backend.app.db import (
    IdempotencyConflictError,
    MigrationError,
    RevisionConflictError,
    SQLiteRepository,
    SessionDeletedError,
    apply_migrations,
    get_applied_migrations,
    open_connection,
)

EXPECTED_TABLES = {
    "schema_migrations",
    "sessions",
    "code_versions",
    "turns",
    "capture_attempts",
    "challenges",
    "case_history",
    "jobs",
    "artifacts",
    "traces",
    "coaching_messages",
    "speech_jobs",
    "idempotency_records",
    "usage_reservations",
    "usage_ledger",
    "session_events",
}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _future_iso(hours: int = 24) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _past_iso(hours: int = 1) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


class DatabaseMigrationAndRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = Path(tempfile.mkdtemp(prefix="vcc_db_test_"))
        self.db_path = self._tmpdir / "test.sqlite3"
        self.repo = SQLiteRepository(self.db_path)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_initial_migration_wal_fk_tables_and_idempotency(self) -> None:
        applied_first = self.repo.initialize()
        self.assertEqual(applied_first, ["0001", "0002", "0003", "0004", "0005", "0006", "0007", "0008", "0009", "0010", "0011", "0012", "0013"])

        applied_second = self.repo.initialize()
        self.assertEqual(applied_second, [])

        recorded = get_applied_migrations(self.db_path)
        self.assertEqual(len(recorded), 13)
        self.assertEqual(recorded[0].version, "0001")
        self.assertEqual(recorded[0].name, "initial")

        conn = open_connection(self.db_path)
        try:
            journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            fk_enabled = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
            self.assertEqual(journal_mode.lower(), "wal")
            self.assertEqual(fk_enabled, 1)

            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table';"
                ).fetchall()
            }
            self.assertTrue(EXPECTED_TABLES.issubset(tables))

            indexes = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index';"
                ).fetchall()
            }
            for expected_idx in (
                "idx_sessions_expires_at",
                "idx_code_versions_session_created",
                "idx_turns_session_created",
                "idx_turns_status_created",
                "idx_jobs_session_created",
                "idx_jobs_status_created",
                "idx_challenges_expires_at",
                "idx_speech_jobs_status_created",
                "idx_speech_jobs_expires_at",
                "idx_idempotency_status_created",
                "idx_idempotency_expires_at",
                "idx_usage_reservations_status_created",
                "idx_usage_ledger_status_created",
                "idx_session_events_session_created",
            ):
                self.assertIn(expected_idx, indexes)
        finally:
            conn.close()

    def test_migration_rollback_and_forward_recovery(self) -> None:
        migrations_dir = self._tmpdir / "migrations"
        migrations_dir.mkdir()
        initial_src = (
            Path(__file__).resolve().parents[2]
            / "app"
            / "db"
            / "migrations"
            / "0001_initial.sql"
        )
        shutil.copy2(initial_src, migrations_dir / "0001_initial.sql")

        self.assertEqual(apply_migrations(self.db_path, migrations_dir), ["0001"])

        bad_migration = migrations_dir / "0002_add_notes.sql"
        bad_migration.write_text(
            "CREATE TABLE temp_should_rollback (id TEXT PRIMARY KEY);\n"
            "CREATE TABLE broken_syntax (id TEXT PRIMARY KEY, ;\n",
            encoding="utf-8",
        )
        with self.assertRaises(MigrationError):
            apply_migrations(self.db_path, migrations_dir)

        conn = open_connection(self.db_path)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table';"
                ).fetchall()
            }
            self.assertNotIn("temp_should_rollback", tables)
        finally:
            conn.close()

        self.assertEqual([m.version for m in get_applied_migrations(self.db_path)], ["0001"])

        bad_migration.write_text(
            "CREATE TABLE forward_recovered (id TEXT PRIMARY KEY);\n",
            encoding="utf-8",
        )
        self.assertEqual(apply_migrations(self.db_path, migrations_dir), ["0002"])
        self.assertEqual(
            [m.version for m in get_applied_migrations(self.db_path)],
            ["0001", "0002"],
        )

        bad_migration.write_text(
            "CREATE TABLE forward_recovered (id TEXT PRIMARY KEY, extra TEXT);\n",
            encoding="utf-8",
        )
        with self.assertRaises(MigrationError):
            apply_migrations(self.db_path, migrations_dir)

    def test_session_cas_spec_ack_idempotency_and_tombstone(self) -> None:
        self.repo.initialize()
        starter = "def shortest_subarray_ge_target(nums, target):\n    return 0\n"
        session = self.repo.create_session(
            session_id="sess-1",
            token_hash=_sha256("secret-token-1"),
            exercise_id="ex1_shortest_subarray",
            spec_version="v1_positive_only",
            language_mode="EN",
            interaction_mode="VOICE",
            starter_code=starter,
            starter_code_hash=_sha256(starter),
            expires_at=_future_iso(),
        )
        self.assertEqual(session.active_code_version_id, 1)
        self.assertTrue(session.spec_acknowledged)
        self.assertIsNone(session.deleted_at)

        fetched = self.repo.get_session_by_token_hash(_sha256("secret-token-1"))
        self.assertIsNotNone(fetched)
        assert fetched is not None
        self.assertEqual(fetched.id, "sess-1")

        noop = self.repo.save_code_version(
            "sess-1",
            expected_code_version_id=1,
            source_code=starter,
            code_hash=_sha256(starter),
        )
        self.assertFalse(noop.changed)
        self.assertEqual(noop.session.active_code_version_id, 1)

        updated_code = "def shortest_subarray_ge_target(nums, target):\n    return 1\n"
        saved = self.repo.save_code_version(
            "sess-1",
            expected_code_version_id=1,
            source_code=updated_code,
            code_hash=_sha256(updated_code),
        )
        self.assertTrue(saved.changed)
        self.assertEqual(saved.session.active_code_version_id, 2)
        self.assertEqual(saved.code_version.code_version_id, 2)

        with self.assertRaises(RevisionConflictError) as ctx:
            self.repo.save_code_version(
                "sess-1",
                expected_code_version_id=1,
                source_code="def x(): pass\n",
                code_hash=_sha256("def x(): pass\n"),
            )
        self.assertEqual(ctx.exception.actual, 2)

        switched = self.repo.update_spec(
            "sess-1",
            spec_version="v2_negatives_allowed",
            expected_code_version_id=2,
            spec_acknowledged=False,
        )
        self.assertEqual(switched.spec_version, "v2_negatives_allowed")
        self.assertFalse(switched.spec_acknowledged)

        with self.assertRaises(RevisionConflictError):
            self.repo.acknowledge_spec("sess-1", spec_version="v1_positive_only")

        acked = self.repo.acknowledge_spec("sess-1", spec_version="v2_negatives_allowed")
        self.assertTrue(acked.spec_acknowledged)

        miss = self.repo.check_idempotency(
            "sess-1",
            method="POST",
            route="/api/v1/sessions/sess-1/code",
            idempotency_key="idem-key-1234567890",
            request_digest=_sha256("body-a"),
        )
        self.assertEqual(miss.outcome, "MISS")

        self.repo.save_idempotency(
            "sess-1",
            method="POST",
            route="/api/v1/sessions/sess-1/code",
            idempotency_key="idem-key-1234567890",
            request_digest=_sha256("body-a"),
            status="COMPLETED",
            response_json='{"ok":true}',
            expires_at=_future_iso(),
        )
        hit = self.repo.check_idempotency(
            "sess-1",
            method="POST",
            route="/api/v1/sessions/sess-1/code",
            idempotency_key="idem-key-1234567890",
            request_digest=_sha256("body-a"),
        )
        self.assertEqual(hit.outcome, "HIT")
        assert hit.record is not None
        self.assertEqual(hit.record.response_json, '{"ok":true}')

        with self.assertRaises(IdempotencyConflictError):
            self.repo.check_idempotency(
                "sess-1",
                method="POST",
                route="/api/v1/sessions/sess-1/code",
                idempotency_key="idem-key-1234567890",
                request_digest=_sha256("body-b"),
            )

        self.repo.save_idempotency(
            "sess-1",
            method="POST",
            route="/api/v1/sessions/sess-1/code",
            idempotency_key="idem-expired-123456",
            request_digest=_sha256("body-old"),
            status="COMPLETED",
            response_json='{"old":true}',
            expires_at=_past_iso(),
        )
        expired = self.repo.check_idempotency(
            "sess-1",
            method="POST",
            route="/api/v1/sessions/sess-1/code",
            idempotency_key="idem-expired-123456",
            request_digest=_sha256("body-old"),
        )
        self.assertEqual(expired.outcome, "EXPIRED")

        tombstoned = self.repo.tombstone_session("sess-1")
        self.assertIsNotNone(tombstoned.deleted_at)
        self.assertEqual(tombstoned.state, "DELETED")
        self.assertIsNone(self.repo.get_session("sess-1"))
        self.assertIsNone(self.repo.get_session_by_token_hash(_sha256("secret-token-1")))
        self.assertIsNotNone(self.repo.get_session("sess-1", include_deleted=True))

        with self.assertRaises(SessionDeletedError):
            self.repo.save_code_version(
                "sess-1",
                expected_code_version_id=2,
                source_code="def late(): pass\n",
                code_hash=_sha256("def late(): pass\n"),
            )


if __name__ == "__main__":
    unittest.main()
