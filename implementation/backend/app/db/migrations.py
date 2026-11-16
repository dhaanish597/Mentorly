"""SQLite WAL connection helper and versioned SQL migration runner."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import sqlite3
import os
import uuid

_MIGRATION_FILENAME_RE = re.compile(r"^(\d+)_([a-zA-Z0-9_]+)\.sql$")


class MigrationError(RuntimeError):
    """Raised when a migration is malformed, fails, or drifts from recorded checksums."""


@dataclass(frozen=True)
class AppliedMigration:
    version: str
    name: str
    checksum: str
    applied_at: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def database_target(settings):
    """Resolve app-selected storage; older test/worker settings remain compatible."""
    return settings.database_target if hasattr(settings, 'database_target') else settings.database_path


def open_connection(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection configured with WAL mode and foreign key enforcement."""
    from backend.app.db.postgres.runtime import PostgresTarget, Connection
    if isinstance(db_path, PostgresTarget):
        return Connection(db_path)
    target = str(db_path)
    if target != ":memory:" and not target.startswith("file:"):
        Path(target).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn


def _split_sql_statements(sql: str) -> list[str]:
    """Split SQL text into individual complete statements without using executescript."""
    statements: list[str] = []
    buffer: list[str] = []
    for line in sql.splitlines(keepends=True):
        stripped = line.strip()
        if not buffer and (not stripped or stripped.startswith("--")):
            continue
        buffer.append(line)
        candidate = "".join(buffer)
        if sqlite3.complete_statement(candidate):
            cleaned = candidate.strip()
            if cleaned:
                statements.append(cleaned)
            buffer.clear()
    remainder = "".join(buffer).strip()
    if remainder:
        statements.append(remainder)
    return statements


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at TEXT NOT NULL
        );
        """
    )


def _discover_migrations(migrations_dir: Path) -> list[tuple[str, str, Path]]:
    if not migrations_dir.is_dir():
        raise MigrationError(f"Migrations directory does not exist: {migrations_dir}")
    discovered: list[tuple[int, str, str, Path]] = []
    seen_versions: set[str] = set()
    for path in sorted(migrations_dir.iterdir()):
        if not path.is_file() or path.suffix != ".sql":
            continue
        match = _MIGRATION_FILENAME_RE.match(path.name)
        if not match:
            raise MigrationError(f"Invalid migration filename: {path.name}")
        version, name = match.group(1), match.group(2)
        if version in seen_versions:
            raise MigrationError(f"Duplicate migration version: {version}")
        seen_versions.add(version)
        discovered.append((int(version), version, name, path))
    discovered.sort(key=lambda item: (item[0], item[1]))
    return [(version, name, path) for _, version, name, path in discovered]


def apply_migrations(
    db_path: str | Path,
    migrations_dir: str | Path | None = None,
) -> list[str]:
    """Apply all pending SQL migrations atomically and return newly applied versions."""
    from backend.app.db.postgres.runtime import PostgresTarget, initialize
    if isinstance(db_path, PostgresTarget):
        if migrations_dir is not None:
            raise MigrationError('SQLite migration files cannot run on PostgreSQL.')
        return initialize(db_path)
    resolved_dir = (
        Path(migrations_dir)
        if migrations_dir is not None
        else Path(__file__).with_name("migrations")
    )
    migrations = _discover_migrations(resolved_dir)
    applied_now: list[str] = []

    conn = open_connection(db_path)
    try:
        _ensure_migrations_table(conn)
        rows = conn.execute(
            "SELECT version, name, checksum, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()
        recorded = {row["version"]: row["checksum"] for row in rows}

        pending = [(v, n, p) for v, n, p in migrations if v not in recorded]
        # Preserve an existing installation before the first engineering-studio
        # upgrade. Fresh/test memory databases have no historical state to copy.
        studio_upgrade = next((v for v, _, _ in pending if int(v) >= 7), None)
        target = str(db_path)
        if recorded and studio_upgrade and target != ":memory:" and not target.startswith("file:"):
            directory = Path(target).resolve().parent / "backups"
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup_path = directory / f"{Path(target).stem}.before-{studio_upgrade}.{stamp}.{uuid.uuid4().hex[:8]}.sqlite3"
            # Exclusive creation prevents truncating a pre-existing backup.
            descriptor = os.open(backup_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            backup = sqlite3.connect(backup_path)
            try:
                conn.backup(backup)
            except BaseException:
                backup.close()
                backup_path.unlink(missing_ok=True)
                raise
            finally:
                backup.close()

        for version, name, path in migrations:
            sql_bytes = path.read_bytes()
            checksum = hashlib.sha256(sql_bytes).hexdigest()
            if version in recorded:
                if recorded[version] != checksum:
                    raise MigrationError(
                        f"Checksum mismatch for already-applied migration {version} ({name})"
                    )
                continue

            sql_text = sql_bytes.decode("utf-8")
            statements = _split_sql_statements(sql_text)
            if not statements:
                raise MigrationError(f"Migration {path.name} contains no SQL statements")

            conn.execute("BEGIN IMMEDIATE;")
            try:
                for stmt in statements:
                    conn.execute(stmt)
                conn.execute(
                    """
                    INSERT INTO schema_migrations (version, name, checksum, applied_at)
                    VALUES (?, ?, ?, ?);
                    """,
                    (version, name, checksum, utc_now_iso()),
                )
                conn.execute("COMMIT;")
            except sqlite3.Error as exc:
                conn.execute("ROLLBACK;")
                raise MigrationError(
                    f"Migration {path.name} failed and was rolled back: {exc}"
                ) from exc

            applied_now.append(version)
    finally:
        conn.close()

    return applied_now


def get_applied_migrations(db_path: str | Path) -> list[AppliedMigration]:
    """Return all recorded migrations ordered by version."""
    conn = open_connection(db_path)
    try:
        _ensure_migrations_table(conn)
        rows = conn.execute(
            "SELECT version, name, checksum, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()
        return [
            AppliedMigration(
                version=row["version"],
                name=row["name"],
                checksum=row["checksum"],
                applied_at=row["applied_at"],
            )
            for row in rows
        ]
    finally:
        conn.close()
