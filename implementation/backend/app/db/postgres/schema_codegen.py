"""Offline PostgreSQL DDL authoring from a pristine, migrated SQLite fixture.

Run only during development. It never reads a learner database and never applies
DDL to PostgreSQL. Generated SQL is checked in, reviewed and versioned separately.
Unsupported SQLite features fail rather than disappearing from the schema.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import tempfile
from pathlib import Path

from backend.app.db.migrations import apply_migrations

from .runtime import dialect_sql

FUNCTIONS = r"""
CREATE FUNCTION viva_datetime(value text, VARIADIC modifiers text[] DEFAULT ARRAY[]::text[])
RETURNS text LANGUAGE plpgsql STABLE AS $$
DECLARE moment timestamptz; modifier text;
BEGIN
 IF value IS NULL THEN RETURN NULL; END IF;
 IF value='now' THEN moment:=CURRENT_TIMESTAMP; ELSE moment:=value::timestamptz; END IF;
 FOREACH modifier IN ARRAY modifiers LOOP
  IF modifier !~ '^[+-][0-9]+ (day|days|minute|minutes|second|seconds)$' THEN RETURN NULL; END IF;
  moment:=moment+modifier::interval;
 END LOOP;
 RETURN to_char(moment AT TIME ZONE 'UTC','YYYY-MM-DD HH24:MI:SS');
EXCEPTION WHEN datetime_field_overflow OR invalid_datetime_format OR invalid_time_zone_displacement_value THEN RETURN NULL;
END $$;
CREATE FUNCTION viva_date(value text, VARIADIC modifiers text[] DEFAULT ARRAY[]::text[])
RETURNS text LANGUAGE SQL STABLE AS $$ SELECT substring(viva_datetime(value,VARIADIC modifiers),1,10) $$;
CREATE FUNCTION viva_julianday(value text) RETURNS double precision LANGUAGE plpgsql STABLE AS $$
BEGIN RETURN extract(epoch FROM value::timestamptz)/86400.0+2440587.5;
EXCEPTION WHEN datetime_field_overflow OR invalid_datetime_format OR invalid_time_zone_displacement_value THEN RETURN NULL;
END $$;
CREATE FUNCTION viva_json_valid(value text) RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN PERFORM value::jsonb; RETURN value IS NOT NULL;
EXCEPTION WHEN invalid_text_representation THEN RETURN false;
END $$;
CREATE FUNCTION viva_json_extract(value text, path text) RETURNS text LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
 IF path !~ '^\$\.[a-zA-Z_][a-zA-Z_0-9]*(\.[a-zA-Z_][a-zA-Z_0-9]*)*$' THEN
  RAISE EXCEPTION 'Unsupported JSON path';
 END IF;
 RETURN value::jsonb #>> string_to_array(substring(path,3),'.');
END $$;
CREATE FUNCTION viva_json_each(value text) RETURNS TABLE(key text,value text) LANGUAGE SQL IMMUTABLE AS $$
 SELECT (ordinality-1)::text,element::text FROM jsonb_array_elements($1::jsonb) WITH ORDINALITY AS e(element,ordinality)
$$;
"""


def _trigger(query):
    match = re.fullmatch(
        r"CREATE TRIGGER\s+(\w+)\s+(BEFORE|AFTER)\s+(INSERT|DELETE|UPDATE(?:\s+OF\s+\w+)?)\s+ON\s+(\w+)\s*(?:WHEN\s+([\s\S]+?))?\s*BEGIN\s*([\s\S]*?)\s*END",
        query,
        re.IGNORECASE,
    )
    if not match:
        raise ValueError("Unsupported trigger definition")
    name, timing, event, table, condition, body = match.groups()
    # SQLite's checked evidence trigger idiom becomes an actual PG exception.
    body = re.sub(
        r"SELECT CASE WHEN ([\s\S]*?) THEN RAISE\(ABORT,('(?:''|[^'])*')\) END;?",
        r"IF \1 THEN RAISE EXCEPTION \2; END IF;",
        body,
        flags=re.IGNORECASE,
    )
    body = re.sub(
        r"SELECT RAISE\(ABORT,('(?:''|[^'])*')\);?",
        r"RAISE EXCEPTION \1;",
        body,
        flags=re.IGNORECASE,
    )
    if "RAISE(ABORT" in body.upper():
        raise ValueError("Unsupported trigger guard")
    # Separate each statement before UPSERT qualification; IF guards contain
    # semicolons but have no UPSERTs, and therefore can use the same safe pass.
    body = ";".join(dialect_sql(part) for part in body.split(";"))
    if condition:
        body = f"IF {dialect_sql(condition)} THEN\n{body}\nEND IF;"
    retval = "OLD" if event.upper() == "DELETE" else "NEW"
    return f"""CREATE FUNCTION trigger_{name}() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
{body}\nRETURN {retval};
END $$;
CREATE TRIGGER {name} {timing} {event} ON {table}
 FOR EACH ROW EXECUTE FUNCTION trigger_{name}();"""


def generate_schema() -> str:
    from .account_dispatch import DDL as account_ddl
    from .maintenance import DDL as maintenance_ddl
    from .transfer import DDL as transfer_ddl

    with tempfile.TemporaryDirectory(prefix="viva-pristine-schema-") as directory:
        source = Path(directory) / "empty.sqlite3"
        apply_migrations(source)
        # The current SQLite speech initializer owns additional legacy ledger
        # columns beyond migration SQL. Include them in the authored PG manifest;
        # the dummy adapter cannot dispatch or resolve any provider credentials.
        from backend.app.speech.gatekeeper import SpeechGatekeeper

        gate = SpeechGatekeeper(object(), db_path=source)
        gate._conn.close()
        with sqlite3.connect(source) as conn:
            objects = conn.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name"
            ).fetchall()
    tables = {
        name: query
        for kind, name, _, query in objects
        if kind == "table" and not name.startswith(("sqlite_", "repo_chunks_fts"))
    }
    pending = dict(tables)
    ordered = []
    while pending:
        available = [
            name
            for name, q in pending.items()
            if not (
                set(re.findall(r"REFERENCES\s+[\"\']?(\w+)", q, re.IGNORECASE)) - {name}
            )
            & pending.keys()
        ]
        if not available:
            raise ValueError("Schema has cyclic or unsupported foreign keys")
        for name in available:
            ordered.append(name)
            del pending[name]
    output = [
        "-- Complete coordinator schema. Generated from pristine authored SQLite migrations.",
        "-- Text JSON/timestamps and integer booleans retain existing service contracts.",
        "-- BEGIN IMMEDIATE is serialized across processes by PostgreSQL advisory lock.",
        FUNCTIONS,
        account_ddl,
        maintenance_ddl,
        transfer_ddl,
    ]
    for name in ordered:
        q = tables[name]
        if re.search(
            r"\b(AUTOINCREMENT|WITHOUT ROWID|COLLATE|BLOB)\b", q, re.IGNORECASE
        ):
            raise ValueError("Unsupported table feature: " + name)
        q = re.sub(r"\bREAL\b", "DOUBLE PRECISION", q, flags=re.IGNORECASE)
        q = re.sub(r"\bINTEGER\b", "BIGINT", q, flags=re.IGNORECASE)
        q = dialect_sql(q)
        q = (
            q[: q.rfind(")")]
            + ", _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY"
            + q[q.rfind(")") :]
        )
        output.append(q + ";")
    output.append("""CREATE TABLE repo_chunks_fts (
 chunk_id TEXT PRIMARY KEY REFERENCES repo_chunks(id) ON DELETE CASCADE,
 snapshot_id TEXT NOT NULL REFERENCES repo_snapshots(id) ON DELETE CASCADE,
 text TEXT NOT NULL,
 search_vector tsvector GENERATED ALWAYS AS (to_tsvector('simple',text)) STORED,
 _vcc_order BIGINT GENERATED ALWAYS AS IDENTITY
);
CREATE INDEX repo_chunks_fts_search ON repo_chunks_fts USING GIN(search_vector);""")
    for kind, name, table, query in objects:
        if kind == "index":
            output.append(dialect_sql(query) + ";")
        elif kind == "trigger":
            output.append(_trigger(query))
    return "\n\n".join(output) + "\n"


if __name__ == "__main__":
    target = Path(__file__).with_name("runtime_schema.sql")
    generated = generate_schema()
    target.write_text(generated)
    print(
        f"Authored {target.name}; SHA256 {hashlib.sha256(generated.encode()).hexdigest()}"
    )
