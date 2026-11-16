"""Rehearse production's six-schema lineage against isolated local PostgreSQL."""
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
from uuid import uuid4

import pytest
from psycopg import sql
from backend.app.db.postgres.legacy_upgrade import UpgradeError, copy_legacy_schema
from backend.app.db.postgres.runtime import PostgresTarget, initialize

DSN = os.environ.get("VIVA_POSTGRES_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="Dedicated disposable PostgreSQL DSN required")


@pytest.fixture
def runtime():
    import psycopg
    target = PostgresTarget(DSN, 'viva_runtime_' + uuid4().hex)
    try:
        initialize(target)
        yield None, target
    finally:
        with psycopg.connect(DSN, autocommit=True) as conn:
            conn.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(target.schema)))

FIXTURES = Path(__file__).parent.parent / 'fixtures' / 'legacy_postgres_runtime'


@pytest.fixture
def legacy(runtime):
    _, target = runtime
    name = 'viva_legacy_' + uuid4().hex
    files = sorted(FIXTURES.glob('000*.sql'))
    expected = [(p.stem.split('_', 1)[0], p.stem.split('_', 1)[1], hashlib.sha256(p.read_bytes()).hexdigest()) for p in files]
    import psycopg
    conn = psycopg.connect(target.dsn, autocommit=True)
    try:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(name)))
        conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(name)))
        conn.execute('CREATE TABLE schema_migrations(version TEXT PRIMARY KEY,name TEXT NOT NULL,checksum TEXT NOT NULL,applied_at TEXT NOT NULL)')
        for p, record in zip(files, expected):
            conn.execute(p.read_text())
            conn.execute('INSERT INTO schema_migrations VALUES(%s,%s,%s,%s)', (*record, datetime.now(timezone.utc).isoformat()))
        conn.execute('INSERT INTO studio_workspaces(id,token_hash,created_at,expires_at) VALUES(%s,%s,%s,%s)', ('workspace', 'hash', '2026-01-01', '2099-01-01'))
        conn.execute('INSERT INTO cloud_audio VALUES(%s,%s,%s,%s,%s)', ('scope', 'session', 'key', b'audio', 1.0))
        yield target, name, expected, conn
    finally:
        conn.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(name)))
        conn.close()


def test_copy_reconciles_data_without_modifying_source(legacy):
    target, name, expected, conn = legacy
    result = copy_legacy_schema(target, name, expected)
    assert result['tables'] > 50
    assert result['retained_audio'] == 1
    assert conn.execute('SELECT count(*) FROM studio_workspaces').fetchone()[0] == 1
    with target.connect() as db:
        assert db.execute('SELECT token_hash FROM studio_workspaces WHERE id=%s', ('workspace',)).fetchone()[0] == 'hash'
        assert bytes(db.execute('SELECT wav FROM legacy_cloud_audio').fetchone()[0]) == b'audio'
    with pytest.raises(UpgradeError, match='not empty'):
        copy_legacy_schema(target, name, expected)


def test_refuses_unreconciled_provider_leases(legacy):
    target, name, expected, conn = legacy
    conn.execute("INSERT INTO cloud_leases VALUES('lease','speech','owner','UNCERTAIN',1,1)")
    with pytest.raises(UpgradeError, match='leases'):
        copy_legacy_schema(target, name, expected)
    with target.connect() as db:
        assert db.execute('SELECT count(*) FROM studio_workspaces').fetchone()[0] == 0


def test_refuses_unrecognized_migration_history(legacy):
    target, name, expected, conn = legacy
    conn.execute("UPDATE schema_migrations SET checksum='changed' WHERE version='0001'")
    with pytest.raises(UpgradeError, match='history'):
        copy_legacy_schema(target, name, expected)
    with target.connect() as db:
        assert db.execute('SELECT count(*) FROM studio_workspaces').fetchone()[0] == 0


def test_freeze_blocks_writers_until_context_exit_and_copy_commits(legacy):
    import psycopg
    from backend.app.db.postgres.legacy_upgrade import frozen_legacy_schema
    target, name, expected, conn = legacy
    with frozen_legacy_schema(target, name) as frozen:
        copy_legacy_schema(target, name, expected, frozen_connection=frozen)
        conn.execute("SET lock_timeout = '100ms'")
        with pytest.raises(psycopg.errors.LockNotAvailable):
            conn.execute("INSERT INTO studio_workspaces(id,token_hash,created_at,expires_at) VALUES('blocked','h','2026','2099')")
        with target.connect() as other:
            assert other.execute('SELECT count(*) FROM studio_workspaces').fetchone()[0] == 0
    conn.execute("INSERT INTO studio_workspaces(id,token_hash,created_at,expires_at) VALUES('after','h','2026','2099')")
    with target.connect() as db:
        assert db.execute('SELECT count(*) FROM studio_workspaces').fetchone()[0] == 1


def test_interrupted_frozen_copy_rolls_back_and_releases_writers(legacy):
    from backend.app.db.postgres.legacy_upgrade import frozen_legacy_schema
    target, name, expected, conn = legacy
    with pytest.raises(RuntimeError, match='interrupted'):
        with frozen_legacy_schema(target, name) as frozen:
            copy_legacy_schema(target, name, expected, frozen_connection=frozen)
            raise RuntimeError('interrupted')
    with target.connect() as db:
        assert db.execute('SELECT count(*) FROM studio_workspaces').fetchone()[0] == 0
        assert db.execute("SELECT to_regclass('legacy_cloud_audio')").fetchone()[0] is None
    conn.execute("INSERT INTO studio_workspaces(id,token_hash,created_at,expires_at) VALUES('after','h','2026','2099')")
    with frozen_legacy_schema(target, name) as frozen:
        assert copy_legacy_schema(target, name, expected, frozen_connection=frozen)['retained_audio'] == 1


def test_durable_fence_blocks_restricted_role_after_commit(legacy):
    import psycopg
    from backend.app.db.postgres.legacy_fence import install_legacy_fence
    target, name, expected, conn = legacy
    role = 'viva_writer_' + uuid4().hex
    ident = sql.Identifier(role)
    try:
        conn.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(ident))
        conn.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(sql.Identifier(name), ident))
        conn.execute(sql.SQL('GRANT INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA {} TO {}').format(sql.Identifier(name), ident))
        install_legacy_fence(target, name, role)
        conn.execute(sql.SQL('SET ROLE {}').format(ident))
        for statement in ["INSERT INTO studio_workspaces(id,token_hash,created_at,expires_at) VALUES('blocked','h','2026','2099')", "UPDATE studio_workspaces SET token_hash='x'", 'DELETE FROM studio_workspaces', 'TRUNCATE cloud_audio']:
            with pytest.raises(psycopg.errors.RaiseException, match='write fence'):
                conn.execute(statement)
        conn.execute('RESET ROLE')
        assert conn.execute('SELECT count(*) FROM studio_workspaces').fetchone()[0] == 1
        assert copy_legacy_schema(target, name, expected)['retained_audio'] == 1
    finally:
        conn.execute('RESET ROLE')
        conn.execute(sql.SQL('DROP OWNED BY {}').format(ident))
        conn.execute(sql.SQL('DROP ROLE {}').format(ident))


def test_fence_rejects_superuser_writer(legacy):
    from backend.app.db.postgres.legacy_fence import install_legacy_fence
    target, name, _, conn = legacy
    role = conn.execute('SELECT current_user').fetchone()[0]
    with pytest.raises(UpgradeError, match='bypass'):
        install_legacy_fence(target, name, role)
    assert conn.execute("SELECT to_regprocedure('viva_reject_legacy_writes()')").fetchone()[0] is None


def test_failed_fence_install_rolls_back_all_ddl_and_can_retry(legacy):
    import psycopg
    from backend.app.db.postgres.legacy_fence import install_legacy_fence
    target, name, _, conn = legacy
    role = 'viva_writer_' + uuid4().hex
    ident = sql.Identifier(role)
    try:
        conn.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(ident))
        conn.execute("CREATE FUNCTION conflicting_fence() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NULL; END $$")
        conn.execute('CREATE TRIGGER viva_legacy_write_fence BEFORE INSERT ON studio_workspaces FOR EACH STATEMENT EXECUTE FUNCTION conflicting_fence()')
        with pytest.raises(psycopg.errors.DuplicateObject):
            install_legacy_fence(target, name, role)
        assert conn.execute("SELECT to_regprocedure('viva_reject_legacy_writes()')").fetchone()[0] is None
        conn.execute('DROP TRIGGER viva_legacy_write_fence ON studio_workspaces')
        install_legacy_fence(target, name, role)
        assert conn.execute("SELECT to_regprocedure('viva_reject_legacy_writes()')").fetchone()[0] is not None
    finally:
        conn.execute(sql.SQL('DROP ROLE {}').format(ident))


def test_same_artifact_restart_preserves_post_cutover_write(legacy):
    target, name, expected, _ = legacy
    copy_legacy_schema(target, name, expected)
    with target.connect() as db:
        db.execute("INSERT INTO studio_workspaces(id,token_hash,created_at,expires_at) VALUES('post-cutover','new','2026','2099')")
    initialize(target)
    with target.connect() as db:
        assert db.execute("SELECT token_hash FROM studio_workspaces WHERE id='post-cutover'").fetchone() == ('new',)
        assert bytes(db.execute('SELECT wav FROM legacy_cloud_audio').fetchone()[0]) == b'audio'


def test_restricted_staging_role_cannot_read_or_write_legacy(legacy):
    import psycopg
    target, source, _, conn = legacy
    role = 'viva_staging_' + uuid4().hex
    ident = sql.Identifier(role)
    try:
        conn.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(ident))
        conn.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(sql.Identifier(target.schema), ident))
        conn.execute(sql.SQL('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {} TO {}').format(sql.Identifier(target.schema), ident))
        conn.execute(sql.SQL('SET ROLE {}').format(ident))
        assert conn.execute(sql.SQL('SELECT count(*) FROM {}.studio_workspaces').format(sql.Identifier(target.schema))).fetchone()[0] == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(sql.SQL('SELECT * FROM {}.studio_workspaces').format(sql.Identifier(source)))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(sql.SQL("INSERT INTO {}.studio_workspaces(id,token_hash,created_at,expires_at) VALUES('bad','h','2026','2099')").format(sql.Identifier(source)))
    finally:
        conn.execute('RESET ROLE')
        conn.execute(sql.SQL('DROP OWNED BY {}').format(ident))
        conn.execute(sql.SQL('DROP ROLE {}').format(ident))


def test_historical_timestamp_ties_have_deterministic_key_order(legacy):
    target, name, expected, conn = legacy
    for identifier in ('z-tied', 'a-tied'):
        conn.execute('INSERT INTO studio_workspaces(id,token_hash,created_at,expires_at) VALUES(%s,%s,%s,%s)',
                     (identifier, identifier+'-hash', '2026-02-01', '2099-01-01'))
    copy_legacy_schema(target, name, expected)
    with target.connect() as db:
        assert [r[0] for r in db.execute("SELECT id FROM studio_workspaces WHERE created_at='2026-02-01' ORDER BY _vcc_order")] == ['a-tied', 'z-tied']
