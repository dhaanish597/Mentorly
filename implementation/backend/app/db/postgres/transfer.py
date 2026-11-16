"""Private, versioned offline SQLite export and empty-target PostgreSQL import.

This is operator tooling, never a public HTTP import endpoint. It preserves all
authoritative app rows, including hashed capabilities, revisions and quota
history. It excludes rebuildable FTS shadow tables and live infrastructure leases.
No cutover is performed: keep source SQLite and its verified backup for rollback.
"""

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from .runtime import PostgresTarget

MAX_SNAPSHOT_BYTES = 256 * 1024 * 1024
NAME = re.compile(r"[a-z_][a-z0-9_]{0,62}\Z")
IGNORED = {
    "viva_schema_migrations",
    "runtime_maintenance_owner",
    "runtime_transfer_history",
    "cloud_audio",
    "legacy_cloud_audio",
}
DDL = """CREATE TABLE runtime_transfer_history (
 content_hash TEXT PRIMARY KEY, imported_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 table_count INTEGER NOT NULL, row_count BIGINT NOT NULL
);"""


class TransferError(ValueError):
    pass


def _canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _rows_hash(rows):
    return hashlib.sha256(_canonical(rows)).hexdigest()


def _sorted(rows):
    return sorted(rows, key=_canonical)


def export_sqlite(source: Path, destination: Path):
    source = Path(source)
    destination = Path(destination)
    if source.is_symlink() or not source.is_file():
        raise TransferError("A regular existing SQLite source is required.")
    if destination.exists() or destination.is_symlink():
        raise TransferError("Export destination already exists.")
    tables = {}
    # SQLite online backup captures a transactionally coherent WAL snapshot.
    with tempfile.TemporaryDirectory(prefix="viva-transfer-") as directory:
        backup = Path(directory) / "snapshot.sqlite3"
        fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        with (
            closing(
                sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
            ) as original,
            closing(sqlite3.connect(backup)) as copy,
        ):
            original.backup(copy)
            if (
                copy.execute("PRAGMA integrity_check").fetchall() != [("ok",)]
                or copy.execute("PRAGMA foreign_key_check").fetchone() is not None
            ):
                raise TransferError("SQLite backup integrity checks failed.")
            names = [
                row[0]
                for row in copy.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
            ]
            for name in names:
                if name.startswith(("sqlite_", "repo_chunks_fts")):
                    continue
                if not NAME.fullmatch(name):
                    raise TransferError("Unsupported table identifier.")
                columns = [
                    row[1] for row in copy.execute(f'PRAGMA table_info("{name}")')
                ]
                rows = _sorted(
                    [list(row) for row in copy.execute(f'SELECT * FROM "{name}"')]
                )
                tables[name] = {
                    "columns": columns,
                    "rows": rows,
                    "count": len(rows),
                    "hash": _rows_hash(rows),
                }
    payload = {"schema_version": "viva-storage-transfer-1", "tables": tables}
    payload["content_hash"] = hashlib.sha256(_canonical(payload)).hexdigest()
    encoded = _canonical(payload) + b"\n"
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        raise TransferError("Export exceeds bounded snapshot size.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".viva-export-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp, destination)  # atomic and cannot overwrite an existing file
    finally:
        Path(temp).unlink(missing_ok=True)
    return {
        "content_hash": payload["content_hash"],
        "tables": len(tables),
        "rows": sum(t["count"] for t in tables.values()),
    }


def load_snapshot(path):
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > MAX_SNAPSHOT_BYTES:
        raise TransferError("Invalid snapshot file.")
    try:
        payload = json.loads(path.read_bytes())
    except (ValueError, RecursionError):
        raise TransferError("Invalid snapshot encoding.") from None
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema_version", "tables", "content_hash"}
        or payload["schema_version"] != "viva-storage-transfer-1"
    ):
        raise TransferError("Unsupported snapshot contract.")
    digest = payload["content_hash"]
    base = {k: v for k, v in payload.items() if k != "content_hash"}
    if (
        type(digest) is not str
        or hashlib.sha256(_canonical(base)).hexdigest() != digest
    ):
        raise TransferError("Snapshot integrity hash mismatch.")
    if not isinstance(payload["tables"], dict) or len(payload["tables"]) > 200:
        raise TransferError("Invalid table manifest.")
    for name, table in payload["tables"].items():
        if (
            not NAME.fullmatch(name)
            or not isinstance(table, dict)
            or set(table) != {"columns", "rows", "count", "hash"}
        ):
            raise TransferError("Invalid table contract.")
        cols, rows = table["columns"], table["rows"]
        if (
            not isinstance(cols, list)
            or len(cols) > 128
            or len(set(cols)) != len(cols)
            or any(not isinstance(c, str) or not NAME.fullmatch(c) for c in cols)
        ):
            raise TransferError("Invalid columns.")
        if (
            not isinstance(rows, list)
            or len(rows) > 1000000
            or type(table["count"]) is not int
            or len(rows) != table["count"]
            or any(not isinstance(row, list) or len(row) != len(cols) for row in rows)
        ):
            raise TransferError("Invalid rows.")
        if _rows_hash(rows) != table["hash"] or _sorted(rows) != rows:
            raise TransferError("Table reconciliation hash mismatch.")
    return payload


def _target_columns(conn, schema):
    rows = conn.execute(
        "SELECT table_name,column_name FROM information_schema.columns WHERE table_schema=%s AND column_name<>'_vcc_order' ORDER BY table_name,ordinal_position",
        (schema,),
    ).fetchall()
    tables = {}
    for table, col in rows:
        if table in IGNORED or table == "repo_chunks_fts":
            continue
        tables.setdefault(table, []).append(col)
    return tables


def _order(conn, schema, tables):
    rows = conn.execute(
        """SELECT c.relname,p.relname FROM pg_constraint k
      JOIN pg_class c ON c.oid=k.conrelid JOIN pg_class p ON p.oid=k.confrelid
      JOIN pg_namespace n ON n.oid=c.relnamespace WHERE k.contype='f' AND n.nspname=%s""",
        (schema,),
    ).fetchall()
    dependencies = {
        t: {
            parent
            for child, parent in rows
            if child == t and parent != t and parent in tables
        }
        for t in tables
    }
    # Evidence triggers enforce additional ownership dependencies beyond FKs.
    dependencies.get("learning_external_events", set()).update(
        {"interview_reports", "interview_events"}
    )
    dependencies.get("learning_evidence_achievements", set()).update(
        {"learning_events", "learning_external_events"}
    )
    pending = set(tables)
    ordered = []
    while pending:
        ready = sorted(t for t in pending if not dependencies[t] & pending)
        if not ready:
            raise TransferError("Unsupported cyclic import dependencies.")
        ordered.extend(ready)
        pending.difference_update(ready)
    return ordered


def reconcile(conn, schema, payload):
    from psycopg import sql

    actual = _target_columns(conn, schema)
    if actual != {name: table["columns"] for name, table in payload["tables"].items()}:
        raise TransferError(
            "Source and target columns differ; migrate source before export."
        )
    for name, table in payload["tables"].items():
        query = sql.SQL("SELECT {} FROM {}").format(
            sql.SQL(",").join(sql.Identifier(c) for c in table["columns"]),
            sql.Identifier(name),
        )
        rows = _sorted([list(r) for r in conn.execute(query)])
        if len(rows) != table["count"] or _rows_hash(rows) != table["hash"]:
            raise TransferError("Target count/hash reconciliation failed.")


def import_postgres(target: PostgresTarget, snapshot_path: Path):
    """Preserve the target on failure without exposing rejected private rows."""
    import psycopg

    try:
        return _import_postgres(target, snapshot_path)
    except psycopg.Error as exc:
        raise TransferError(
            f"PostgreSQL import failed ({exc.sqlstate}); the import transaction was rolled back."
        ) from None


def _import_postgres(target: PostgresTarget, snapshot_path: Path):
    """Import once into an initialized empty app schema; never merge or overwrite."""
    from psycopg import sql

    from .runtime import initialize

    payload = load_snapshot(snapshot_path)
    initialize(target)
    with target.connect() as conn, conn.transaction():
        lock = int.from_bytes(
            hashlib.sha256(("viva-write:" + target.schema).encode()).digest()[:8],
            "big",
            signed=True,
        )
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (lock,))
        existing = conn.execute(
            "SELECT content_hash FROM runtime_transfer_history"
        ).fetchall()
        if existing:
            if existing != [(payload["content_hash"],)]:
                raise TransferError("Target already contains a different import.")
            reconcile(conn, target.schema, payload)
            return {
                "status": "ALREADY_IMPORTED",
                "content_hash": payload["content_hash"],
            }
        tables = _target_columns(conn, target.schema)
        source_tables = {name: t["columns"] for name, t in payload["tables"].items()}
        if tables != source_tables:
            differing = sorted(
                name
                for name in tables.keys() | source_tables.keys()
                if tables.get(name) != source_tables.get(name)
            )
            raise TransferError(
                "Source and target columns differ: " + ",".join(differing)
            )
        for name in tables:
            if conn.execute(
                sql.SQL("SELECT EXISTS(SELECT 1 FROM {})").format(sql.Identifier(name))
            ).fetchone()[0]:
                raise TransferError(
                    "Target must be empty; existing data was preserved."
                )
        for name in _order(conn, target.schema, tables):
            table = payload["tables"][name]
            query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                sql.Identifier(name),
                sql.SQL(",").join(sql.Identifier(c) for c in table["columns"]),
                sql.SQL(",").join(sql.Placeholder() for _ in table["columns"]),
            )
            with conn.cursor() as cursor:
                cursor.executemany(query, table["rows"])
        # Search indexes are disposable; source chunks remain authoritative.
        conn.execute(
            "INSERT INTO repo_chunks_fts(chunk_id,snapshot_id,text) SELECT id,snapshot_id,text FROM repo_chunks"
        )
        reconcile(conn, target.schema, payload)
        conn.execute(
            "INSERT INTO runtime_transfer_history(content_hash,table_count,row_count) VALUES(%s,%s,%s)",
            (
                payload["content_hash"],
                len(tables),
                sum(t["count"] for t in payload["tables"].values()),
            ),
        )
    return {
        "status": "IMPORTED",
        "content_hash": payload["content_hash"],
        "tables": len(tables),
        "rows": sum(t["count"] for t in payload["tables"].values()),
    }
