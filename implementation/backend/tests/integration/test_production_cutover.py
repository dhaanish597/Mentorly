"""Local operator rehearsal; never evidence of a Supabase credential reset."""
import json
import os
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from scripts import production_cutover as operator


def credentials():
    return operator.Credentials(
        'host=127.0.0.1 port=5432 dbname=postgres user=legacy password=new',
        'host=127.0.0.1 port=6543 dbname=postgres user=legacy password=new',
        'host=127.0.0.1 port=5432 dbname=postgres user=legacy password=old',
        'host=127.0.0.1 port=6543 dbname=postgres user=legacy password=old')


def test_protected_credentials_file(tmp_path):
    path = tmp_path / 'operator.json'
    path.write_text(json.dumps(vars(credentials())))
    path.chmod(0o600)
    assert operator.load_credentials(path) == credentials()
    assert 'password=' not in repr(operator.load_credentials(path))
    path.chmod(0o640)
    with pytest.raises(operator.CutoverError, match='owner-only'):
        operator.load_credentials(path)
    path.chmod(0o600)
    link = tmp_path / 'link'
    link.symlink_to(path)
    with pytest.raises(OSError):
        operator.load_credentials(link)


def test_credential_endpoint_and_rotation_checks(monkeypatch):
    value = credentials()
    operator.validate_credentials(value)
    for changed in (
        operator.Credentials(value.old_direct, value.admin_pool, value.old_direct, value.old_pool),
        operator.Credentials(value.admin_direct, value.admin_direct, value.old_direct, value.old_direct),
        operator.Credentials(value.admin_direct, value.admin_pool, value.old_direct.replace('5432', '5433'), value.old_pool),
    ):
        with pytest.raises(operator.CutoverError):
            operator.validate_credentials(changed)
    monkeypatch.setenv('PGHOSTADDR', '1.2.3.4')
    with pytest.raises(operator.CutoverError, match='single-host'):
        operator.validate_credentials(value)


def test_no_network_failure_can_substitute_for_old_auth_rejection(monkeypatch):
    monkeypatch.setattr(operator.psycopg, 'connect', Mock(side_effect=psycopg.OperationalError('private details')))
    with pytest.raises(operator.CutoverError, match='unproven') as exc:
        operator._old_rejected('secret')
    assert 'private details' not in str(exc.value)
    monkeypatch.setattr(operator.psycopg, 'connect', Mock(side_effect=psycopg.errors.InvalidPassword('private details')))
    operator._old_rejected('secret')


def test_successful_old_login_always_aborts(monkeypatch):
    conn = Mock()
    monkeypatch.setattr(operator.psycopg, 'connect', Mock(return_value=conn))
    with pytest.raises(operator.CutoverError, match='still connect'):
        operator._old_rejected('secret')
    conn.close.assert_called_once()


def test_libpq_authentication_fallback_requires_verified_endpoint_and_exact_user(monkeypatch):
    observed = 'connection failed: connection to server at "127.0.0.1", port 55469 failed: FATAL:  password authentication failed for user "legacy"'
    connect = Mock(side_effect=psycopg.OperationalError(observed))
    monkeypatch.setattr(operator.psycopg, 'connect', connect)
    with pytest.raises(operator.CutoverError, match='unproven'):
        operator._old_rejected(credentials().old_direct)
    operator._old_rejected(credentials().old_direct, verified_endpoint=True)
    for message in (observed.replace('"legacy"', '"other"'), observed + ' additional context',
                    'connection timeout', 'SSL certificate verify failed',
                    'FATAL: Tenant or user not found', 'password authentication failed for user "legacy"'):
        connect.side_effect = psycopg.OperationalError(message)
        with pytest.raises(operator.CutoverError, match='unproven'):
            operator._old_rejected(credentials().old_direct, verified_endpoint=True)


def test_supabase_session_and_transaction_pool_identity_and_auth_message(monkeypatch):
    base = 'host=aws-0-ap-northeast-2.pooler.supabase.com dbname=postgres user=postgres.tryalzyijwegfaowftbq sslmode=verify-full'
    config = operator.Credentials(base+' port=5432 password=new', base+' port=6543 password=new',
                                  base+' port=5432 password=old', base+' port=6543 password=old')
    operator.validate_credentials(config)
    message = 'connection failed: connection to server failed: FATAL: password authentication failed for user "postgres"'
    monkeypatch.setattr(operator.psycopg, 'connect', Mock(side_effect=psycopg.OperationalError(message)))
    operator._old_rejected(config.old_pool, verified_endpoint=True)
    mismatched = operator.Credentials(config.admin_direct, config.admin_pool.replace('tryalzyijwegfaowftbq', 'anotherproject'),
                                     config.old_direct, config.old_pool.replace('tryalzyijwegfaowftbq', 'anotherproject'))
    with pytest.raises(operator.CutoverError, match='different projects'):
        operator.validate_credentials(mismatched)
    with pytest.raises(operator.CutoverError, match='verified TLS'):
        operator._params(config.old_pool.replace('verify-full', 'require'))


def test_maintenance_and_recovery_are_required_before_termination(monkeypatch):
    connect = Mock()
    monkeypatch.setattr(operator, '_connect', connect)
    with pytest.raises(operator.CutoverError, match='maintenance'):
        operator.fence_sessions(credentials(), admission_stopped=True, workers_drained=False)
    connect.assert_not_called()
    monkeypatch.setattr(operator, 'preflight', Mock(side_effect=operator.CutoverError('recovery failed')))
    with pytest.raises(operator.CutoverError, match='recovery failed'):
        operator.fence_sessions(credentials(), admission_stopped=True, workers_drained=True)
    connect.assert_not_called()


def test_exact_history_uses_six_versioned_artifacts():
    history = operator.expected_history()
    assert len(history) == 6
    assert [row[0] for row in history] == [f'{version:04d}' for version in range(1, 7)]
    conn = Mock()
    conn.execute.return_value.fetchall.return_value = history[:-1]
    with pytest.raises(operator.CutoverError, match='checksums'):
        operator.verify_history(conn)


@pytest.fixture
def dedicated_database(monkeypatch):
    dsn = os.environ.get('VIVA_POSTGRES_TEST_DSN')
    if not dsn:
        pytest.skip('Dedicated disposable local PostgreSQL DSN required')
    params = psycopg.conninfo.conninfo_to_dict(dsn)
    if not (params.get('host', '').startswith('/') or params.get('host') in ('127.0.0.1', '::1')):
        pytest.fail('Operator tests require an explicit local disposable PostgreSQL host')
    name = 'operator_test_' + uuid4().hex
    role = name + '_runtime'
    with psycopg.connect(dsn, autocommit=True) as root:
        root.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        params['dbname'] = name
        isolated_dsn = psycopg.conninfo.make_conninfo(**params)
        with psycopg.connect(isolated_dsn, autocommit=True) as conn:
            conn.execute('CREATE SCHEMA viva_app')
            conn.execute('SET search_path TO viva_app')
            conn.execute('CREATE TABLE schema_migrations(version TEXT PRIMARY KEY,name TEXT NOT NULL,checksum TEXT NOT NULL,applied_at TEXT NOT NULL)')
            fixture_path = Path(__file__).parents[1] / 'fixtures/legacy_postgres_runtime'
            for record, path in zip(operator.expected_history(), sorted(fixture_path.glob('000*.sql'))):
                conn.execute(path.read_text())
                conn.execute('INSERT INTO schema_migrations VALUES(%s,%s,%s,%s)', (*record, '2026-01-01'))
            conn.execute("INSERT INTO studio_workspaces(id,token_hash,created_at,expires_at) VALUES('retained','hash','2026','2099')")
            conn.execute("INSERT INTO cloud_audio VALUES('scope','session','key',%s,1)", (b'preserved',))
        # Local trust authentication cannot exercise a real password reset.
        # Test the copy/role path only; independent unit tests cover fail-closed
        # credential checking, and real platform validation remains mandatory.
        monkeypatch.setattr(operator, 'preflight', Mock(return_value=('operator', 'operator', name)))
        monkeypatch.setattr(operator, '_old_rejected', Mock())
        yield isolated_dsn, name, role
        root.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
        root.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(role)))
        root.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(name + '_operator')))


def test_copy_restricted_runtime_and_source_preservation(dedicated_database):
    dsn, schema, role = dedicated_database
    params = psycopg.conninfo.conninfo_to_dict(dsn)
    params.setdefault('user', os.environ.get('USER', 'postgres'))
    params['password'] = 'local-test-only'
    admin = psycopg.conninfo.make_conninfo(**params)
    config = operator.Credentials(admin, admin, admin, admin)
    result = operator.provision_target(config, fence_verified=True, account_key='synthetic', schema=schema, role=role)
    assert result['copy']['retained_audio'] == 1
    with psycopg.connect(dsn, autocommit=True) as conn:
        assert conn.execute('SELECT count(*) FROM viva_app.studio_workspaces').fetchone()[0] == 1
    with psycopg.connect(result['runtime_dsn'], autocommit=True) as runtime:
        assert runtime.execute(sql.SQL('SELECT count(*) FROM {}.studio_workspaces').format(sql.Identifier(schema))).fetchone()[0] == 1
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            runtime.execute('SELECT * FROM viva_app.studio_workspaces')
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            runtime.execute("UPDATE viva_provider_coordination.accounts SET capacity=99")
    with pytest.raises(operator.CutoverError, match='fresh'):
        operator.provision_target(config, fence_verified=True, account_key='synthetic', schema=schema, role=role)


def test_failed_history_creates_no_target(dedicated_database):
    dsn, schema, role = dedicated_database
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("UPDATE viva_app.schema_migrations SET checksum='changed' WHERE version='0001'")
    config = operator.Credentials(dsn, dsn, dsn, dsn)
    with pytest.raises(operator.CutoverError, match='checksums'):
        operator.provision_target(config, fence_verified=True, account_key='synthetic', schema=schema, role=role)
    with psycopg.connect(dsn, autocommit=True) as conn:
        assert conn.execute('SELECT to_regnamespace(%s)', (schema,)).fetchone()[0] is None
        assert not conn.execute('SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=%s)', (role,)).fetchone()[0]


def test_concurrent_coordination_creator_is_never_given_rls(dedicated_database):
    dsn, _, _ = dedicated_database
    with psycopg.connect(dsn, autocommit=True) as conn, psycopg.connect(dsn, autocommit=True) as competitor:
        class ConcurrentCreator:
            def execute(self, query, params=()):
                if query == 'CREATE SCHEMA viva_provider_coordination':
                    competitor.execute(operator.ACCOUNT_DDL)
                return conn.execute(query, params)

        with pytest.raises(psycopg.errors.DuplicateSchema), conn.transaction():
            operator._prepare_coordination(ConcurrentCreator())
        rows = competitor.execute("SELECT c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='viva_provider_coordination' AND c.relname IN ('accounts','leases')").fetchall()
        assert rows == [(False,), (False,)]


def test_existing_coordination_without_rls_aborts_before_role_creation(dedicated_database):
    dsn, schema, role = dedicated_database
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(operator.ACCOUNT_DDL)
    config = operator.Credentials(dsn, dsn, dsn, dsn)
    with pytest.raises(operator.CutoverError, match='continuity'):
        operator.provision_target(config, fence_verified=True, account_key='synthetic', schema=schema, role=role)
    with psycopg.connect(dsn, autocommit=True) as conn:
        assert conn.execute('SELECT to_regnamespace(%s)', (schema,)).fetchone()[0] is None
        assert not conn.execute('SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=%s)', (role,)).fetchone()[0]


def test_nonsuperuser_operator_with_create_role_and_db_create(dedicated_database, tmp_path):
    """Match production's privilege boundary, including PostgreSQL16 memberships."""
    from backend.app.core.config import Settings
    from backend.app.main import create_app
    from fastapi.testclient import TestClient
    from pydantic import SecretStr

    dsn, schema, role = dedicated_database
    admin_role = schema + '_operator'
    with psycopg.connect(dsn, autocommit=True) as root:
        root.execute(sql.SQL('CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB CREATEROLE NOREPLICATION BYPASSRLS').format(sql.Identifier(admin_role)))
        root.execute(sql.SQL('GRANT CREATE ON DATABASE {} TO {}').format(sql.Identifier(schema), sql.Identifier(admin_role)))
        root.execute(sql.SQL('ALTER SCHEMA viva_app OWNER TO {}').format(sql.Identifier(admin_role)))
        for name, kind in root.execute("SELECT c.relname,c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='viva_app' AND c.relkind IN ('r','p','S','v','m') ORDER BY c.relkind='S'").fetchall():
            noun = {'S':'SEQUENCE', 'v':'VIEW', 'm':'MATERIALIZED VIEW'}.get(kind, 'TABLE')
            root.execute(sql.SQL('ALTER '+noun+' viva_app.{} OWNER TO {}').format(sql.Identifier(name), sql.Identifier(admin_role)))
    params = psycopg.conninfo.conninfo_to_dict(dsn)
    params.update(user=admin_role, password='local-only')
    admin_dsn = psycopg.conninfo.make_conninfo(**params)
    config = operator.Credentials(admin_dsn, admin_dsn, admin_dsn, admin_dsn)
    result = operator.provision_target(config, fence_verified=True, account_key='synthetic', schema=schema, role=role)
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        assert admin.execute('SELECT rolsuper,rolcreaterole,rolcreatedb,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone() == (False, True, False, True)
        assert admin.execute('SELECT admin_option,inherit_option,set_option FROM pg_auth_members WHERE roleid=(SELECT oid FROM pg_roles WHERE rolname=%s) AND member=(SELECT oid FROM pg_roles WHERE rolname=current_user)', (role,)).fetchone() == (True, False, False)
        assert admin.execute('SELECT has_schema_privilege(%s,%s,\'CREATE\'),has_database_privilege(%s,current_database(),\'CREATE\')', (role, schema, role)).fetchone() == (False, False)
        assert admin.execute('SELECT nspowner=(SELECT oid FROM pg_roles WHERE rolname=current_user) FROM pg_namespace WHERE nspname=%s', (schema,)).fetchone()[0]
    settings = Settings(database_url=SecretStr(result['runtime_dsn']), database_schema=schema,
                        database_path=tmp_path/'unused.sqlite3', tts_cache_dir=tmp_path/'cache',
                        groq_api_key=None, gnani_api_key=SecretStr('synthetic'), env='test')
    with TestClient(create_app(settings)) as client:
        assert client.get('/api/v1/meta/health').status_code == 200
        assert client.get('/api/v1/studio/scenarios').status_code == 200
        response = client.post('/api/v1/studio/workspaces', json={'workspace_id':str(uuid4()), 'workspace_token':'w'*48}, headers={'X-Idempotency-Key':str(uuid4())})
        assert response.status_code == 200, response.text
