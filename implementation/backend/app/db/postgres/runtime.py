"""PostgreSQL runtime preserving the application's SQLite storage contracts.

Only trusted application SQL passes through this adapter. Transactions take one
schema-specific advisory lock, preserving SQLite's serialized writer semantics
across processes. Configuration is transaction-local for transaction poolers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterator, Sequence

_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{0,62}\Z")
_SQL_PARTS = re.compile(r"('(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|--[^\n]*(?:\n|$)|/\*.*?\*/)", re.S)
_MIGRATIONS = Path(__file__).with_name("runtime_migrations")


@dataclass(frozen=True, repr=False)
class PostgresTarget:
    """Explicit target; string representations never contain credentials."""

    dsn: str = field(repr=False)
    schema: str = "viva_app"
    allow_local: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.dsn, str) or not self.dsn.strip():
            raise ValueError("PostgreSQL connection configuration is required")
        if not _IDENTIFIER.fullmatch(self.schema):
            raise ValueError("Invalid PostgreSQL application schema")
        if type(self.allow_local) is not bool:
            raise ValueError("Invalid PostgreSQL local connection policy")
        _connection_options(self)

    def __repr__(self) -> str:
        return f"PostgresTarget(schema={self.schema!r}, credentials=<redacted>)"

    __str__ = __repr__

    @property
    def identity(self) -> str:
        """Stable database/schema identity without hashing credentials."""
        options = _connection_options(self)
        identity = {key: options.get(key, "") for key in ("host", "hostaddr", "port", "dbname", "user")}
        identity["schema"] = self.schema
        return "postgres:" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def _driver():
    try:
        import psycopg
    except ImportError:
        raise sqlite3.OperationalError("PostgreSQL runtime driver is unavailable") from None
    return psycopg


def _connection_options(target: PostgresTarget) -> dict[str, str]:
    try:
        options = _driver().conninfo.conninfo_to_dict(target.dsn)
    except Exception:
        raise ValueError("Invalid PostgreSQL connection configuration") from None
    host = options.get("host", "")
    local = bool(host) and (host.startswith("/") or host in {"localhost", "127.0.0.1", "::1"})
    if not host or "," in host or options.get("service"):
        raise ValueError("PostgreSQL requires one explicit host")
    if local:
        if not target.allow_local:
            raise ValueError("Local PostgreSQL requires explicit test permission")
    elif options.get("sslmode") != "verify-full":
        raise ValueError("Remote PostgreSQL requires verified TLS (sslmode=verify-full)")
    if options.get("options"):
        raise ValueError("PostgreSQL startup options are managed by the runtime")
    return options


def _raw_connection(target: PostgresTarget):
    options = _connection_options(target)
    options["connect_timeout"] = "10"
    if options.get("sslmode") == "verify-full" and not options.get("sslrootcert"):
        import certifi
        options["sslrootcert"] = certifi.where()
    try:
        return _driver().connect(**options, autocommit=True, prepare_threshold=None)
    except Exception:
        raise sqlite3.OperationalError("PostgreSQL connection failed") from None


def _lock_key(schema: str) -> int:
    return int.from_bytes(hashlib.sha256(f"viva-runtime:{schema}".encode()).digest()[:8], "big", signed=True)


def _configure_transaction(raw, schema: str, *, lock: bool) -> None:
    raw.execute(f'SET LOCAL search_path TO "{schema}", pg_catalog')
    raw.execute("SET LOCAL timezone TO 'UTC'")
    raw.execute("SET LOCAL statement_timeout TO '15s'")
    raw.execute("SET LOCAL lock_timeout TO '5s'")
    raw.execute("SET LOCAL idle_in_transaction_session_timeout TO '30s'")
    if lock:
        raw.execute("SELECT pg_advisory_xact_lock(%s)", (_lock_key(schema),))


class Row:
    """Tuple iteration with sqlite3.Row-compatible named access and keys()."""

    def __init__(self, names: Sequence[str], values: Sequence[Any]) -> None:
        self._names = tuple(names)
        self._values = tuple(values)
        self._lookup = {name.casefold(): i for i, name in reversed(list(enumerate(names)))}

    def __getitem__(self, key: int | slice | str) -> Any:
        if isinstance(key, str):
            try:
                key = self._lookup[key.casefold()]
            except KeyError:
                raise IndexError("No item with that key") from None
        return self._values[key]

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def keys(self) -> list[str]:
        return list(self._names)


class Cursor:
    """Materialized cursor, consumable after a pooler transaction commits."""

    def __init__(self, rows: list[Row] | None = None, rowcount: int = -1, description=None) -> None:
        self._rows = rows or []
        self._position = 0
        self.rowcount = rowcount
        self.description = description
        self.lastrowid = None

    def fetchone(self) -> Row | None:
        if self._position >= len(self._rows):
            return None
        row = self._rows[self._position]
        self._position += 1
        return row

    def fetchall(self) -> list[Row]:
        result = self._rows[self._position:]
        self._position = len(self._rows)
        return result

    def fetchmany(self, size: int = 1) -> list[Row]:
        result = self._rows[self._position:self._position + size]
        self._position += len(result)
        return result

    def __iter__(self) -> Iterator[Row]:
        while (row := self.fetchone()) is not None:
            yield row

    def close(self) -> None:
        self._rows.clear()


def _translate(sql: str, *, bind: bool) -> str:
    if not isinstance(sql, str) or not sql.strip():
        raise sqlite3.ProgrammingError("Database statement is required")
    parts = _SQL_PARTS.split(sql)
    for index in range(0, len(parts), 2):
        part = parts[index]
        for name in ("json_valid", "json_extract", "json_each", "date", "datetime", "julianday"):
            part = re.sub(r"\b" + name + r"\s*\(", "viva_" + name + "(", part, flags=re.I)
        if re.search(r"\b(PRAGMA|AUTOINCREMENT|GLOB|REPLACE|sqlite_sequence)\b", part, re.I):
            raise sqlite3.OperationalError("Unsupported database dialect")
        part = re.sub(r"\bINTEGER\b", "BIGINT", part, flags=re.I)
        part = re.sub(r"\bREAL\b", "DOUBLE PRECISION", part, flags=re.I)
        part = re.sub(r"length\(CAST\(([a-z_][a-z0-9_.]*|\?)\s+AS\s+BLOB\)\)", r"octet_length(convert_to(\1,'UTF8'))", part, flags=re.I)
        part = re.sub(r"\?\s+IS\s+NULL", "CAST(? AS TEXT) IS NULL", part, flags=re.I)
        if bind:
            part = part.replace("?", "\x00")
        parts[index] = part
    translated = "".join(parts)
    translated = re.sub(r"viva_json_extract(\(payload_json,\s*'\$\.assistance'\))\s*=\s*1\b", r"viva_json_number\1=1", translated, flags=re.I)
    target = re.match(r"\s*INSERT\s+INTO\s+([a-z_]+)", translated, re.I)
    if target and re.search(r"\bON\s+CONFLICT\b", translated, re.I):
        translated = re.sub(r"\b(\w+)\s*=\s*\1\s*\+\s*excluded\.(\w+)", lambda m: f"{m[1]}={target[1]}.{m[1]}+excluded.{m[2]}", translated, flags=re.I)
    if bind:
        translated = translated.replace("%", "%%").replace("\x00", "%s")
    return translated


class PostgresConnection:
    """Synchronous DBAPI boundary used by existing repository and service code."""

    def __init__(self, target: PostgresTarget) -> None:
        self.target = target
        self._raw = _raw_connection(target)
        self.row_factory = sqlite3.Row

    @property
    def in_transaction(self) -> bool:
        return self._raw.info.transaction_status != 0

    def _query(self, sql: str, parameters: tuple[Any, ...]) -> Cursor:
        cursor = self._raw.execute(sql, parameters if parameters else None)
        description = cursor.description
        names = [column.name for column in description] if description else []
        rows = [Row(names, values) for values in cursor.fetchall()] if description else []
        return Cursor(rows, cursor.rowcount, description)

    def execute(self, sql: str, parameters: Sequence[Any] = ()) -> Cursor:
        psycopg = _driver()
        params = tuple(int(p) if isinstance(p, bool) else p for p in parameters)
        command = sql.strip().rstrip(";").strip()
        try:
            if command.upper() in {"BEGIN", "BEGIN IMMEDIATE", "BEGIN DEFERRED", "BEGIN TRANSACTION"}:
                if self.in_transaction:
                    raise sqlite3.OperationalError("Cannot start a transaction within a transaction")
                self._raw.execute("BEGIN ISOLATION LEVEL READ COMMITTED")
                try:
                    _configure_transaction(self._raw, self.target.schema, lock=True)
                except Exception:
                    self._raw.rollback()
                    raise
                return Cursor()
            if command.upper() in {"COMMIT", "END", "END TRANSACTION"}:
                self.commit()
                return Cursor()
            if command.upper() == "ROLLBACK":
                self.rollback()
                return Cursor()
            table_info = re.fullmatch(r"PRAGMA\s+table_info\(\s*([a-z_]+)\s*\)", command, re.I)
            if table_info:
                command = """SELECT ordinal_position-1 AS cid,column_name AS name,data_type AS type,
                CASE WHEN is_nullable='NO' THEN 1 ELSE 0 END AS notnull,column_default AS dflt_value,
                CASE WHEN EXISTS(SELECT 1 FROM information_schema.key_column_usage k
                 JOIN information_schema.table_constraints t USING(constraint_catalog,constraint_schema,constraint_name)
                 WHERE k.table_schema=c.table_schema AND k.table_name=c.table_name
                 AND k.column_name=c.column_name AND t.constraint_type='PRIMARY KEY') THEN 1 ELSE 0 END AS pk
                FROM information_schema.columns c WHERE table_schema=current_schema() AND table_name=? ORDER BY ordinal_position"""
                params = (table_info[1],)
            elif re.fullmatch(r"PRAGMA\s+(journal_mode\s*=\s*WAL|foreign_keys\s*=\s*ON|synchronous\s*=\s*NORMAL|busy_timeout\s*=\s*5000)", command, re.I):
                return Cursor()
            replace = re.match(r"\s*INSERT\s+OR\s+REPLACE\s+INTO\s+(evidence_artifacts|traces|coaching_messages)\s*\((.*?)\)\s*VALUES", command, re.I | re.S)
            ignore = re.match(r"\s*INSERT\s+OR\s+IGNORE\s+INTO\s+", command, re.I)
            if replace:
                columns = [c.strip() for c in replace[2].split(",")]
                if not self.in_transaction or columns[0] != "id" or not params:
                    raise sqlite3.OperationalError("Replacement requires an explicit owned transaction")
                self._raw.execute(f"DELETE FROM {replace[1]} WHERE id=%s", (params[0],))
                command = re.sub(r"INSERT\s+OR\s+REPLACE", "INSERT", command, count=1, flags=re.I)
            elif ignore:
                command = re.sub(r"INSERT\s+OR\s+IGNORE", "INSERT", command, count=1, flags=re.I) + " ON CONFLICT DO NOTHING"
            if "repo_chunks_fts MATCH" in command:
                expected = "SELECT c.path,c.symbol,c.start_line,c.end_line,c.chunk_hash,c.text FROM repo_chunks_fts f JOIN repo_chunks c ON c.id=f.chunk_id WHERE repo_chunks_fts MATCH ? AND f.snapshot_id=? AND c.snapshot_id=? ORDER BY bm25(repo_chunks_fts) LIMIT 20"
                if " ".join(command.split()) != expected or len(params) != 3:
                    raise sqlite3.OperationalError("Unsupported full-text search query")
                command = "SELECT c.path,c.symbol,c.start_line,c.end_line,c.chunk_hash,c.text FROM repo_chunks_fts f JOIN repo_chunks c ON c.id=f.chunk_id WHERE f.search_vector @@ websearch_to_tsquery('simple',?) AND f.snapshot_id=? AND c.snapshot_id=? ORDER BY ts_rank_cd(f.search_vector,websearch_to_tsquery('simple',?)) DESC,c.id LIMIT 20"
                params = (*params, params[0])
            query = _translate(command, bind=bool(params))
            if self.in_transaction:
                return self._query(query, params)
            with self._raw.transaction():
                _configure_transaction(self._raw, self.target.schema, lock=not command.lstrip().upper().startswith(("SELECT", "EXPLAIN")))
                return self._query(query, params)
        except psycopg.IntegrityError:
            raise sqlite3.IntegrityError("PostgreSQL integrity constraint rejected the operation") from None
        except psycopg.ProgrammingError:
            raise sqlite3.ProgrammingError("PostgreSQL rejected the database statement") from None
        except psycopg.Error:
            raise sqlite3.OperationalError("PostgreSQL operation failed") from None

    def commit(self) -> None:
        try:
            self._raw.commit()
        except _driver().Error:
            raise sqlite3.OperationalError("PostgreSQL commit failed") from None

    def rollback(self) -> None:
        try:
            self._raw.rollback()
        except _driver().Error:
            raise sqlite3.OperationalError("PostgreSQL rollback failed") from None

    def close(self) -> None:
        self._raw.close()

    def __enter__(self) -> PostgresConnection:
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if self.in_transaction:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        return False


def open_connection(target: PostgresTarget) -> PostgresConnection:
    return PostgresConnection(target)


def probe_runtime(target: PostgresTarget) -> bool:
    """Read-only health probe verifies connection, schema, and migration checksums."""
    raw = None
    try:
        raw = _raw_connection(target)
        with raw.transaction():
            raw.execute("SET TRANSACTION READ ONLY")
            _configure_transaction(raw, target.schema, lock=False)
            if raw.execute("SELECT current_schema()").fetchone() != (target.schema,):
                return False
            history = raw.execute("SELECT version,name,checksum FROM schema_migrations ORDER BY version").fetchall()
            files = sorted(_MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql"))
            expected = [(p.stem.split("_", 1)[0], p.stem.split("_", 1)[1], hashlib.sha256(p.read_bytes()).hexdigest()) for p in files]
            if not expected or history != expected:
                return False
            definitions = "\n".join(p.read_text() for p in files)
            tables = set(re.findall(r"CREATE TABLE\s+([a-z_]+)", definitions)) | {"schema_migrations"}
            functions = set(re.findall(r"CREATE FUNCTION\s+([a-z_]+)", definitions))
            triggers = set(re.findall(r"CREATE TRIGGER\s+([a-z_]+)", definitions))
            present_tables = {row[0] for row in raw.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema() AND table_type='BASE TABLE'")}
            present_functions = {row[0] for row in raw.execute("SELECT proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=current_schema()")}
            present_triggers = {row[0] for row in raw.execute("SELECT tgname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema() AND NOT t.tgisinternal")}
            return tables <= present_tables and functions <= present_functions and triggers <= present_triggers
    except Exception:
        return False
    finally:
        if raw is not None:
            raw.close()


def apply_runtime_migrations(target: PostgresTarget, migrations_dir: str | Path | None = None) -> list[str]:
    """Apply the authored runtime manifest atomically under the writer lock."""
    from ..migrations import MigrationError, utc_now_iso

    directory = Path(migrations_dir) if migrations_dir is not None else _MIGRATIONS
    files = sorted(directory.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    if not files:
        raise MigrationError("PostgreSQL migration manifest is missing")
    if migrations_dir is None:
        recorded_source = json.loads((directory / "sqlite_source_manifest.json").read_text())
        current_source = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.parent.joinpath("migrations").glob("*.sql"))}
        if current_source != recorded_source:
            raise MigrationError("SQLite schema changed; PostgreSQL runtime manifest must be reviewed")
    manifest = [(p.stem.split("_", 1)[0], p.stem.split("_", 1)[1], hashlib.sha256(p.read_bytes()).hexdigest(), p.read_text()) for p in files]
    if len({m[0] for m in manifest}) != len(manifest):
        raise MigrationError("PostgreSQL migration versions are duplicated")
    raw = _raw_connection(target)
    try:
        with raw.transaction():
            _configure_transaction(raw, target.schema, lock=True)
            raw.execute(f'CREATE SCHEMA IF NOT EXISTS "{target.schema}"')
            raw.execute(f'REVOKE ALL ON SCHEMA "{target.schema}" FROM PUBLIC')
            for role in ("anon", "authenticated"):
                if raw.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                    raw.execute(f'REVOKE ALL ON SCHEMA "{target.schema}" FROM "{role}"')
            raw.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY,name TEXT NOT NULL,checksum TEXT NOT NULL,applied_at TEXT NOT NULL)")
            history = raw.execute("SELECT version,name,checksum FROM schema_migrations ORDER BY version").fetchall()
            expected = [m[:3] for m in manifest]
            if history != expected[:len(history)] or len(history) > len(expected):
                raise MigrationError("PostgreSQL migration history does not match the runtime manifest")
            applied = []
            for version, name, checksum, sql in manifest[len(history):]:
                raw.execute(sql)
                raw.execute("INSERT INTO schema_migrations VALUES(%s,%s,%s,%s)", (version, name, checksum, utc_now_iso()))
                applied.append(version)
            return applied
    except MigrationError:
        raise
    except Exception:
        raise MigrationError("PostgreSQL migration failed; all changes were rolled back") from None
    finally:
        raw.close()
