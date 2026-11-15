"""Opt-in PostgreSQL test. VIVA_POSTGRES_TEST_DSN must name a dedicated test DB.

The database user must be able to create and drop schemas. The test creates a
randomly named schema and removes it afterward. Never point it at production.
"""
from concurrent.futures import ThreadPoolExecutor
import os
import threading
import uuid

import pytest

from backend.app.db.postgres import Migration, MigrationError, apply_migrations


DSN = os.environ.get("VIVA_POSTGRES_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="set VIVA_POSTGRES_TEST_DSN to a dedicated test database")


def test_real_postgres_transaction_concurrency_and_drift():
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql

    schema = "viva_test_" + uuid.uuid4().hex
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {} ").format(sql.Identifier(schema)))
        try:
            def connect():
                conn = psycopg.connect(DSN)
                # Exercise callers configured with a stricter default.
                conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
                conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
                conn.commit()
                return conn

            with connect() as conn:
                with pytest.raises(psycopg.Error):
                    apply_migrations(conn, [Migration(1, "create", "CREATE TABLE probe (id bigint)"),
                                            Migration(2, "fail", "SELECT * FROM missing_table")])
                assert conn.execute("SELECT to_regclass('probe'), to_regclass('viva_schema_migrations')").fetchone() == (None, None)
                conn.rollback()

            with connect() as conn:
                conn.row_factory = psycopg.rows.dict_row
                with pytest.raises(MigrationError, match="tuple rows"):
                    apply_migrations(conn, [])

            barrier = threading.Barrier(2)
            migrations = [Migration(1, "create", "CREATE TABLE probe (id bigint); SELECT pg_sleep(0.5)"),
                          Migration(2, "insert", "INSERT INTO probe VALUES (42)")]

            def run():
                with connect() as conn:
                    barrier.wait(timeout=10)
                    return apply_migrations(conn, migrations)

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(run) for _ in range(2)]
                results = [future.result(timeout=20) for future in futures]
            assert sorted(results, key=len) == [[], [1, 2]]
            with connect() as conn:
                assert conn.execute("SELECT count(*), min(id) FROM probe").fetchone() == (1, 42)
                assert conn.execute("SELECT count(*) FROM viva_schema_migrations").fetchone() == (2,)
                conn.rollback()
                with pytest.raises(MigrationError, match="history"):
                    apply_migrations(conn, [Migration(1, "create", "SELECT 1")])
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
