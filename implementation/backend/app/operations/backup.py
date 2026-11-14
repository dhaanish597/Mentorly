"""Verified SQLite snapshots for local operators; never overwrite a database."""
from __future__ import annotations

import argparse
from contextlib import closing
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import time

BACKUP_TIMEOUT_SECONDS = 30.0
BACKUP_PAGE_BATCH = 128


@dataclass(frozen=True)
class DatabaseVerification:
    integrity_ok: bool
    sha256: str
    size_bytes: int
    migration_versions: tuple[str, ...]


def _digest(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def _readonly_connection(path: Path) -> sqlite3.Connection:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Database must be an existing regular, non-symlink file")
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)


def verify_database(database_path: str | Path) -> DatabaseVerification:
    """Check integrity, foreign keys and exact installed migration identities."""
    path = Path(database_path)
    migrations = Path(__file__).resolve().parents[1] / "db" / "migrations"
    expected = {p.name.split("_", 1)[0]: _digest(p) for p in migrations.glob("*.sql")}
    try:
        with closing(_readonly_connection(path)) as conn:
            conn.execute("PRAGMA query_only=ON")
            if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("Database integrity validation failed")
            if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ValueError("Database foreign-key validation failed")
            recorded = dict(conn.execute("SELECT version, checksum FROM schema_migrations"))
            if recorded != expected:
                raise ValueError("Database migration identities do not match this application")
    except sqlite3.Error as exc:
        raise ValueError("Database could not be validated") from exc
    return DatabaseVerification(True, _digest(path), path.stat().st_size, tuple(sorted(recorded)))


def _check_empty_destination(destination: Path) -> None:
    for suffix in ("", "-journal", "-wal", "-shm"):
        candidate = destination.with_name(destination.name + suffix)
        if candidate.exists() or candidate.is_symlink():
            raise FileExistsError("Destination or SQLite sidecars already exist; nothing is overwritten")


def _private_destination(destination: Path) -> Path:
    owner = os.geteuid()
    if not destination.parent.is_dir():
        raise ValueError("Choose an existing private destination directory")
    original = destination.absolute().parent
    resolved = original.resolve(strict=True)
    ancestry = {original, *original.parents, resolved, *resolved.parents}
    for directory in ancestry:
        info = directory.lstat()
        if info.st_uid not in (0, owner):
            raise ValueError("Backup destination needs trusted private ancestry")
        if not stat.S_ISLNK(info.st_mode) and info.st_mode & 0o022:
            if not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX):
                raise ValueError("Backup destination needs trusted private ancestry")
    parent = resolved
    info = parent.stat()
    if not parent.is_dir() or info.st_uid != owner or info.st_mode & 0o077:
        raise ValueError("Choose an owner-only private destination directory (0700)")
    return parent / destination.name


def _copy_snapshot(source_path: str | Path, destination_path: str | Path) -> DatabaseVerification:
    source, destination = Path(source_path), Path(destination_path)
    _check_empty_destination(destination)
    destination = _private_destination(destination)
    _check_empty_destination(destination)
    verify_database(source)
    fd, temp_name = tempfile.mkstemp(prefix=".vcc-backup-", suffix=".sqlite3", dir=destination.parent)
    temp_path = Path(temp_name)
    os.close(fd)
    started = time.monotonic()

    def check_progress(_status: int, _remaining: int, _total: int) -> None:
        if time.monotonic() - started >= BACKUP_TIMEOUT_SECONDS:
            raise TimeoutError("Database snapshot exceeded its bounded deadline")

    try:
        with closing(_readonly_connection(source)) as src, closing(sqlite3.connect(temp_path)) as dst:
            src.backup(dst, pages=BACKUP_PAGE_BATCH, progress=check_progress, sleep=0.05)
            dst.execute("PRAGMA journal_mode=DELETE")
        verification = verify_database(temp_path)
        with temp_path.open("rb") as file:
            os.fsync(file.fileno())
        _check_empty_destination(destination)
        os.link(temp_path, destination)
        return verification
    finally:
        temp_path.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm", "-journal"):
            temp_path.with_name(temp_path.name + suffix).unlink(missing_ok=True)


def create_verified_backup(database_path: str | Path, destination_path: str | Path) -> DatabaseVerification:
    """Use SQLite's online backup API, including committed WAL data."""
    return _copy_snapshot(database_path, destination_path)


def restore_verified_backup(backup_path: str | Path, destination_path: str | Path) -> DatabaseVerification:
    """Restore only into a new inactive path; operators switch configuration later."""
    return _copy_snapshot(backup_path, destination_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("backup", "restore", "verify"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    if args.operation == "verify":
        result = verify_database(args.source)
    else:
        if args.destination is None:
            parser.error("--destination is required; existing files are never overwritten")
        operation = create_verified_backup if args.operation == "backup" else restore_verified_backup
        result = operation(args.source, args.destination)
    print(json.dumps(asdict(result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
