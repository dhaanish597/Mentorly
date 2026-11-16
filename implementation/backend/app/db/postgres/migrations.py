"""Transactional, serialized runner for explicitly authored PostgreSQL migrations.

The caller owns the connection and must provide a clean, idle psycopg 3-style
connection with tuple rows (the psycopg default). Migration SQL is trusted application code and must not contain
transaction control or statements prohibited in a transaction. Do not use this
runner with the SQLite migration files.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Protocol, Sequence


class MigrationError(RuntimeError):
    """Migration history is invalid or inconsistent with the supplied manifest."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


class Connection(Protocol):
    def transaction(self): ...
    def execute(self, query: str, params: tuple = ()): ...


# Stable application-specific signed 64-bit advisory lock. Transaction-scoped:
# PostgreSQL releases it on both commit and rollback, including connection loss.
_MIGRATION_LOCK = 6217580234511616305
_NAME = re.compile(r"[a-z][a-z0-9_]*\Z")


def apply_migrations(conn: Connection, migrations: Sequence[Migration]) -> list[int]:
    """Apply a complete ordered PostgreSQL manifest in one transaction.

    Serialized across cooperating processes in the same database. Existing
    history must be an exact prefix, including names and checksums. A failure
    leaves both DDL and metadata rolled back. The caller must not invoke this
    inside an existing transaction: a nested transaction would defer lock
    release and commit to its outer owner.
    """
    manifest = tuple(migrations)
    if any(type(m.version) is not int or m.version <= 0 or not _NAME.fullmatch(m.name)
           or not m.sql.strip() for m in manifest):
        raise MigrationError("Invalid migration manifest")
    if any(a.version >= b.version for a, b in zip(manifest, manifest[1:])):
        raise MigrationError("Migration versions must be strictly increasing")

    # psycopg's IDLE value is 0. Refuse an unknown connection state as well as
    # an active transaction, rather than silently creating a savepoint.
    info = getattr(conn, "info", None)
    if info is None or getattr(info, "transaction_status", None) != 0:
        raise MigrationError("An idle PostgreSQL connection is required")

    applied: list[int] = []
    with conn.transaction():
        # A waiter must take a fresh snapshot after the advisory lock is held.
        conn.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        encoding_row = conn.execute("SHOW server_encoding").fetchone()
        if not isinstance(encoding_row, tuple) or len(encoding_row) != 1:
            raise MigrationError("PostgreSQL connection must use tuple rows")
        if encoding_row[0] != "UTF8":
            raise MigrationError("PostgreSQL database must use UTF8 encoding")
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (_MIGRATION_LOCK,))
        # PostgreSQL checks schema CREATE even for CREATE TABLE IF NOT EXISTS
        # when the table already exists. A provisioned runtime has only DML
        # grants: inspect under the migration lock and avoid unnecessary DDL.
        if conn.execute("SELECT to_regclass('viva_schema_migrations')").fetchone()[0] is None:
            conn.execute("""CREATE TABLE viva_schema_migrations (
            version BIGINT PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
        rows = conn.execute(
            "SELECT version, name, checksum FROM viva_schema_migrations ORDER BY version"
        ).fetchall()
        if any(not isinstance(row, tuple) or len(row) != 3 for row in rows):
            raise MigrationError("PostgreSQL connection must use tuple rows")
        expected = [(m.version, m.name, m.checksum) for m in manifest]
        if len(rows) > len(expected) or [tuple(row) for row in rows] != expected[:len(rows)]:
            raise MigrationError("PostgreSQL migration history does not match manifest")
        for migration in manifest[len(rows):]:
            # Execute trusted SQL without parameters, allowing PostgreSQL-native
            # syntax such as function bodies; do not split SQL on semicolons.
            conn.execute(migration.sql)
            conn.execute(
                "INSERT INTO viva_schema_migrations (version, name, checksum) VALUES (%s, %s, %s)",
                (migration.version, migration.name, migration.checksum),
            )
            applied.append(migration.version)
    return applied
