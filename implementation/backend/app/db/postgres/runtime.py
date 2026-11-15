"""Secret-safe PostgreSQL target and explicit transaction dialect for the coordinator.

The application UOW uses integer booleans, text JSON and ISO timestamps on both
backends. This adapter implements the *finite* SQLite idioms used by the audited
services. It does not accept arbitrary SQL or translate migrations at runtime.
BEGIN IMMEDIATE uses a database/schema-scoped advisory transaction lock: initial
PostgreSQL writes retain SQLite's serialization, with shared durable state.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit


class DatabaseConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class PostgresTarget:
    dsn: str = field(repr=False)
    schema: str = "viva_app"

    def __post_init__(self):
        if not isinstance(self.dsn, str) or not self.dsn or "\x00" in self.dsn:
            raise DatabaseConfigurationError(
                "A PostgreSQL connection string is required."
            )
        if (
            not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", self.schema)
            or self.schema in {"public", "information_schema"}
            or self.schema.startswith("pg_")
        ):
            raise DatabaseConfigurationError("Use a dedicated application schema.")
        # Explicit local test DSNs use keyword format; remote URLs must be postgres.
        if "://" in self.dsn:
            parsed = urlsplit(self.dsn)
            if (
                parsed.scheme not in {"postgres", "postgresql"}
                or not parsed.hostname
                or not parsed.path.strip("/")
            ):
                raise DatabaseConfigurationError("Invalid PostgreSQL URL.")
        elif not re.search(r"(^|\s)(host|dbname)=", self.dsn):
            raise DatabaseConfigurationError("Invalid PostgreSQL connection string.")

    def __str__(self):
        identity = hashlib.sha256(self.dsn.encode()).hexdigest()[:16]
        return f"postgresql:{self.schema}:{identity}"

    def connect(self):
        try:
            import psycopg
            from psycopg import sql
        except ImportError:
            raise DatabaseConfigurationError(
                "Install the coordinator PostgreSQL extra (psycopg)."
            ) from None
        try:
            conn = psycopg.connect(self.dsn, autocommit=True, connect_timeout=5)
            # Identifiers are quoted, never concatenated with credentials.
            conn.execute(
                sql.SQL("SET search_path TO {}, pg_catalog").format(
                    sql.Identifier(self.schema)
                )
            )
            conn.execute("SET timezone TO 'UTC'")
            conn.execute("SET statement_timeout TO '15000ms'")
            conn.execute("SET lock_timeout TO '5000ms'")
            return conn
        except psycopg.Error:
            raise sqlite3.OperationalError(
                "PostgreSQL connection is unavailable."
            ) from None


class Record(Mapping):
    """sqlite3.Row-compatible named/integer access without driver-dependent casts."""

    def __init__(self, columns, values):
        def compatible(value):
            # SUM(bigint) is numeric on PostgreSQL; existing count/duration APIs
            # are numbers, never driver-specific Decimal strings.
            if isinstance(value, Decimal):
                if not value.is_finite():
                    raise sqlite3.DataError("Non-finite database number.")
                return (
                    int(value) if value == value.to_integral_value() else float(value)
                )
            return value

        visible = [
            (c, compatible(v)) for c, v in zip(columns, values) if c != "_vcc_order"
        ]
        self._names = tuple(c for c, _ in visible)
        self._values = tuple(v for _, v in visible)

    def __getitem__(self, key):
        return (
            self._values[key]
            if isinstance(key, (int, slice))
            else self._values[self._names.index(key)]
        )

    def __iter__(self):
        # sqlite3.Row iterates values. dict(row) uses keys() instead.
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def keys(self):
        return list(self._names)


class Cursor:
    def __init__(self, cursor=None, rows=None, columns=None):
        self._cursor = cursor
        self._rows = iter(rows) if rows is not None else None
        self._columns = columns

    @property
    def rowcount(self):
        return self._cursor.rowcount if self._cursor is not None else 0

    def fetchone(self):
        values = (
            next(self._rows, None)
            if self._rows is not None
            else self._cursor.fetchone()
        )
        if values is None:
            return None
        cols = self._columns or [d.name for d in self._cursor.description]
        return Record(cols, values)

    def fetchall(self):
        values = list(self._rows) if self._rows is not None else self._cursor.fetchall()
        cols = self._columns or [d.name for d in self._cursor.description]
        return [Record(cols, row) for row in values]

    def __iter__(self):
        while (row := self.fetchone()) is not None:
            yield row


def _tokens(query: str) -> list[tuple[str, str]]:
    """Tokenize SQL strings/comments/identifiers before replacing bound parameters."""
    pattern = re.compile(
        r"('(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|--[^\n]*|/\*[\s\S]*?\*/|\?|[a-zA-Z_][a-zA-Z_0-9]*|.)",
        re.DOTALL,
    )
    tokens = []
    for m in pattern.finditer(query):
        value = m[0]
        kind = (
            "string"
            if value.startswith("'")
            else "quoted"
            if value.startswith('"')
            else "comment"
            if value.startswith(("--", "/*"))
            else "bind"
            if value == "?"
            else "word"
            if re.fullmatch("[a-zA-Z_][a-zA-Z_0-9]*", value)
            else "punct"
        )
        tokens.append((kind, value))
    return tokens


def _qualify_upsert(query):
    """PG requires target qualification where EXCLUDED and target share a name."""
    match = re.search(r"\bINSERT\s+INTO\s+([a-z_][a-z0-9_]*)", query, re.IGNORECASE)
    update = re.search(r"\bDO\s+UPDATE\s+SET\s+", query, re.IGNORECASE)
    if not match or not update:
        return query
    table = match[1]
    head, tail = query[: update.end()], query[update.end() :]
    # Existing UPSERT assignments have no nested commas except function arguments;
    # scan parentheses/quotes so only top-level '=' determines assignment lhs.
    tokens = _tokens(tail)
    names = set()
    depth = 0
    lhs = True
    for index, (kind, value) in enumerate(tokens):
        following = next(
            (v for k, v in tokens[index + 1 :] if k != "comment" and v.strip()), ""
        )
        if kind == "word" and lhs and depth == 0 and following == "=":
            names.add(value.lower())
        if kind == "punct":
            if value == "(":
                depth += 1
            elif value == ")":
                depth -= 1
            elif value == "=" and depth == 0:
                lhs = False
            elif value == "," and depth == 0:
                lhs = True
    result = []
    depth = 0
    lhs = True
    previous = ""
    for index, (kind, value) in enumerate(tokens):
        following = next(
            (v for k, v in tokens[index + 1 :] if k != "comment" and v.strip()), ""
        )
        if (
            kind == "word"
            and value.lower() in names
            and not lhs
            and previous != "."
            and following not in {".", "("}
        ):
            result.append(f"{table}.{value}")
        else:
            result.append(value)
        if kind == "punct":
            if value == "(":
                depth += 1
            elif value == ")":
                depth -= 1
            elif value == "=" and depth == 0:
                lhs = False
            elif value == "," and depth == 0:
                lhs = True
        if kind != "comment" and value.strip():
            previous = value
    return head + "".join(result)


_FUNCTIONS = {
    "date": "viva_date",
    "datetime": "viva_datetime",
    "julianday": "viva_julianday",
    "json_extract": "viva_json_extract",
    "json_valid": "viva_json_valid",
    "json_each": "viva_json_each",
}


def dialect_sql(
    query: str, *, primary_keys: dict[str, tuple[str, ...]] | None = None
) -> str:
    tokens = _tokens(query)
    output = []
    for i, (kind, value) in enumerate(tokens):
        following = next(
            (v for k, v in tokens[i + 1 :] if k != "comment" and v.strip()), ""
        )
        if kind == "bind":
            # The audited optional archive exclusion is a TEXT identifier. PG
            # cannot infer the type of a standalone NULL placeholder.
            output.append("%s::text" if following.upper() == "IS" else "%s")
        elif kind == "word" and value.lower() in _FUNCTIONS and following == "(":
            output.append(_FUNCTIONS[value.lower()])
        elif kind == "word" and value.lower() == "rowid":
            output.append("_vcc_order")
        elif kind == "word" and value.lower() == "sqlite_master":
            output.append(
                "(SELECT table_name AS name,'table'::text AS type FROM information_schema.tables WHERE table_schema=current_schema()) AS sqlite_master"
            )
        else:
            output.append(value)
    rendered = "".join(output).rstrip().rstrip(";")
    # SQLite BLOB casts mean UTF-8 byte length, not PostgreSQL bytea escape parsing.
    rendered = re.sub(
        r"CAST\(((?:[a-z_][a-z0-9_]*\.)?[a-z_][a-z0-9_]*) AS BLOB\)",
        r"convert_to(\1,'UTF8')",
        rendered,
        flags=re.IGNORECASE,
    )
    if re.match(r"\s*INSERT\s+OR\s+IGNORE\b", rendered, re.IGNORECASE):
        rendered = (
            re.sub(
                r"\bINSERT\s+OR\s+IGNORE\b",
                "INSERT",
                rendered,
                count=1,
                flags=re.IGNORECASE,
            )
            + " ON CONFLICT DO NOTHING"
        )
    elif re.match(r"\s*INSERT\s+OR\s+REPLACE\b", rendered, re.IGNORECASE):
        m = re.search(
            r"INSERT\s+OR\s+REPLACE\s+INTO\s+([a-z_][a-z0-9_]*)\s*\(([^)]+)\)",
            rendered,
            re.IGNORECASE,
        )
        if not m or not primary_keys or m[1] not in primary_keys:
            raise sqlite3.OperationalError(
                "An explicit PostgreSQL UPSERT key is required."
            )
        columns = [c.strip() for c in m[2].split(",")]
        keys = primary_keys[m[1]]
        if not set(keys) <= set(columns):
            raise sqlite3.OperationalError("UPSERT omits its identity columns.")
        updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in columns if c not in keys)
        rendered = re.sub(
            r"\bINSERT\s+OR\s+REPLACE\b",
            "INSERT",
            rendered,
            count=1,
            flags=re.IGNORECASE,
        )
        rendered += f" ON CONFLICT ({','.join(keys)}) DO UPDATE SET {updates}"
    if "repo_chunks_fts MATCH" in rendered:
        rendered = rendered.replace(
            "repo_chunks_fts MATCH %s",
            "f.search_vector @@ websearch_to_tsquery('simple',%s)",
        )
        rendered = rendered.replace(
            "bm25(repo_chunks_fts)",
            "ts_rank(f.search_vector,websearch_to_tsquery('simple',%s)) DESC",
        )
        # Search rank gets same parameter separately; Connection.execute binds it.
    return _qualify_upsert(rendered)


class Connection:
    def __init__(self, target: PostgresTarget):
        self.target = target
        self._conn = target.connect()
        self._primary_keys = {}
        self._load_keys()

    def _load_keys(self):
        rows = self._conn.execute(
            """SELECT t.relname,a.attname FROM pg_index i
            JOIN pg_class t ON t.oid=i.indrelid JOIN pg_namespace n ON n.oid=t.relnamespace
            CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum,position)
            JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=k.attnum
            WHERE n.nspname=%s AND i.indisprimary ORDER BY t.relname,k.position""",
            (self.target.schema,),
        ).fetchall()
        for table, col in rows:
            self._primary_keys[table] = (*self._primary_keys.get(table, ()), col)

    @property
    def in_transaction(self):
        return self._conn.info.transaction_status != 0

    def execute(self, query: str, params=()):
        import psycopg

        command = query.strip().rstrip(";").upper()
        try:
            if command == "BEGIN IMMEDIATE":
                self._conn.execute("BEGIN")
                self._conn.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                lock = int.from_bytes(
                    hashlib.sha256(
                        ("viva-write:" + self.target.schema).encode()
                    ).digest()[:8],
                    "big",
                    signed=True,
                )
                self._conn.execute("SELECT pg_advisory_xact_lock(%s)", (lock,))
                from .maintenance import maintenance_fence

                fence = maintenance_fence.get()
                if fence is not None and fence.target_id == str(self.target):
                    row = self._conn.execute(
                        "SELECT owner,generation,expires_at>clock_timestamp() FROM runtime_maintenance_owner WHERE id='retention' FOR UPDATE"
                    ).fetchone()
                    if row is None or row != (fence.owner, fence.generation, True):
                        self._conn.rollback()
                        raise sqlite3.OperationalError(
                            "Maintenance lease was superseded or expired."
                        )
                return Cursor(rows=[], columns=[])
            from .maintenance import maintenance_fence

            fence = maintenance_fence.get()
            if (
                fence is not None
                and fence.target_id == str(self.target)
                and not self.in_transaction
                and command.startswith(("INSERT ", "UPDATE ", "DELETE "))
            ):
                self.execute("BEGIN IMMEDIATE")
                try:
                    cursor = self.execute(query, params)
                    self.commit()
                    return cursor
                except BaseException:
                    self.rollback()
                    raise
            if command.startswith("PRAGMA TABLE_INFO("):
                table = re.fullmatch(
                    r"PRAGMA TABLE_INFO\(([a-z_][a-z0-9_]*)\)", command, re.IGNORECASE
                )[1].lower()
                rows = self._conn.execute(
                    "SELECT ordinal_position-1,column_name,data_type,is_nullable,column_default FROM information_schema.columns WHERE table_schema=%s AND table_name=%s AND column_name<>'_vcc_order' ORDER BY ordinal_position",
                    (self.target.schema, table),
                ).fetchall()
                pk = self._primary_keys.get(table, ())
                return Cursor(
                    rows=[
                        (
                            n,
                            name,
                            typ,
                            int(nullable == "NO"),
                            default,
                            pk.index(name) + 1 if name in pk else 0,
                        )
                        for n, name, typ, nullable, default in rows
                    ],
                    columns=["cid", "name", "type", "notnull", "dflt_value", "pk"],
                )
            if command.startswith("PRAGMA"):
                raise sqlite3.OperationalError(
                    "SQLite PRAGMA is unsupported on PostgreSQL."
                )
            if command.startswith("CREATE TRIGGER "):
                from .schema_codegen import _trigger

                self._conn.execute(_trigger(query.strip().rstrip(";")))
                return Cursor(rows=[], columns=[])
            if command.startswith("DROP TRIGGER "):
                from psycopg import sql

                name = re.fullmatch(
                    r"DROP TRIGGER ([a-z_][a-z0-9_]*)", command, re.IGNORECASE
                )[1].lower()
                row = self._conn.execute(
                    "SELECT event_object_table FROM information_schema.triggers WHERE trigger_schema=%s AND trigger_name=%s LIMIT 1",
                    (self.target.schema, name),
                ).fetchone()
                if not row:
                    raise sqlite3.OperationalError("Trigger does not exist.")
                self._conn.execute(
                    sql.SQL("DROP TRIGGER {} ON {}").format(
                        sql.Identifier(name), sql.Identifier(row[0])
                    )
                )
                return Cursor(rows=[], columns=[])
            rendered = dialect_sql(query, primary_keys=self._primary_keys)
            if "repo_chunks_fts MATCH" in query:
                params = (*params, params[0])
            # Escape literal percent for psycopg's parameter protocol, only when binding.
            if params:
                rendered = re.sub(r"%(?!s)", "%%", rendered)
            cursor = self._conn.execute(rendered, params if params else None)
            return Cursor(cursor)
        except (psycopg.IntegrityError, psycopg.errors.RaiseException) as exc:
            raise sqlite3.IntegrityError(
                f"PostgreSQL integrity constraint rejected the operation ({exc.sqlstate})."
            ) from None
        except psycopg.Error as exc:
            raise sqlite3.OperationalError(
                f"PostgreSQL operation failed ({exc.sqlstate})."
            ) from None

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, typ, value, tb):
        try:
            self.rollback() if typ else self.commit()
        finally:
            self.close()


def initialize(target: PostgresTarget) -> list[str]:
    """Apply explicit checked-in PostgreSQL DDL; never infer DDL from a live DB."""
    from psycopg import sql

    from .migrations import Migration, apply_migrations

    source = Path(__file__).with_name("runtime_schema.sql").read_text()
    with target.connect() as conn:
        conn.execute(
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                sql.Identifier(target.schema)
            )
        )
        applied = apply_migrations(
            conn, [Migration(100, "complete_runtime_schema", source)]
        )
    return [str(x) for x in applied]
