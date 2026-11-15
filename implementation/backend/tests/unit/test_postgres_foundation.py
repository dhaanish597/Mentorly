"""Contract tests using a transactional double, not a PostgreSQL server."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from backend.app.db.postgres import Migration, MigrationError, apply_migrations


class Cursor:
    def __init__(self, rows=()):
        self.rows = rows

    def fetchone(self):
        return self.rows[0]

    def fetchall(self):
        return list(self.rows)


class Connection:
    def __init__(self):
        self.info = SimpleNamespace(transaction_status=0)
        self.history = []
        self.executed = []

    @contextmanager
    def transaction(self):
        before = list(self.history)
        try:
            yield
        except BaseException:
            self.history = before
            raise

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        if sql == "SHOW server_encoding":
            return Cursor([("UTF8",)])
        if sql.startswith("SELECT version"):
            return Cursor(self.history)
        if sql.startswith("INSERT INTO viva_schema_migrations"):
            self.history.append(params)
        if sql == "FAIL":
            raise RuntimeError("database error")
        return Cursor()


def test_apply_is_ordered_serialized_and_idempotent():
    conn = Connection()
    manifest = [Migration(1, "initial", "CREATE TABLE example (id bigint)"),
                Migration(2, "index", "CREATE INDEX ON example (id)")]
    assert apply_migrations(conn, manifest) == [1, 2]
    assert conn.executed[0][0] == "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"
    assert conn.executed[2][0] == "SELECT pg_advisory_xact_lock(%s)"
    assert apply_migrations(conn, manifest) == []
    assert len(conn.history) == 2


def test_rejects_drift_missing_and_reordered_history_before_new_sql():
    conn = Connection()
    first = Migration(1, "initial", "SELECT 1")
    apply_migrations(conn, [first])
    for manifest in ([], [Migration(1, "initial", "SELECT 2")],
                     [Migration(1, "renamed", "SELECT 1")],
                     [Migration(2, "other", "SELECT 2")]):
        with pytest.raises(MigrationError, match="history"):
            apply_migrations(conn, manifest)
    assert conn.history == [(first.version, first.name, first.checksum)]


def test_failed_batch_rolls_back_metadata():
    conn = Connection()
    with pytest.raises(RuntimeError, match="database error"):
        apply_migrations(conn, [Migration(1, "one", "SELECT 1"), Migration(2, "two", "FAIL")])
    assert conn.history == []


def test_requires_clean_connection_and_valid_manifest():
    conn = Connection()
    conn.info.transaction_status = 2
    with pytest.raises(MigrationError, match="idle"):
        apply_migrations(conn, [])
    conn.info.transaction_status = 0
    for manifest in ([Migration(0, "bad", "SELECT 1")],
                     [Migration(1, "bad-name", "SELECT 1")],
                     [Migration(1, "empty", " ")],
                     [Migration(1, "one", "SELECT 1"), Migration(1, "two", "SELECT 2")]):
        with pytest.raises(MigrationError):
            apply_migrations(conn, manifest)
    assert conn.executed == []


def test_rejects_non_tuple_rows():
    class DictRows(Connection):
        def execute(self, sql, params=()):
            if sql == "SHOW server_encoding":
                return Cursor([{"server_encoding": "UTF8"}])
            return super().execute(sql, params)

    with pytest.raises(MigrationError, match="tuple rows"):
        apply_migrations(DictRows(), [])
