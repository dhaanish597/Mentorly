"""Disposable role isolation and real app initialization, without providers."""
import os
from uuid import uuid4
import pytest
import psycopg
from psycopg import sql
from fastapi.testclient import TestClient
from pydantic import SecretStr
from backend.app.core.config import Settings
from backend.app.main import create_app
from scripts.provision_preview_database import provision
DSN=os.environ.get('VIVA_POSTGRES_TEST_DSN')
pytestmark=pytest.mark.skipif(not DSN,reason='Disposable PostgreSQL required')


def test_preview_role_isolation_and_restart(tmp_path):
    suffix=uuid4().hex
    schema,role,prod='stage_'+suffix,'role_'+suffix,'production_'+suffix
    with psycopg.connect(DSN,autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(prod)))
        admin.execute(sql.SQL('CREATE TABLE {}.sessions(id text)').format(sql.Identifier(prod)))
    try:
        runtime_dsn=provision(DSN,schema,role)
        with psycopg.connect(runtime_dsn,autocommit=True) as limited:
            for statement in ('SELECT * FROM {}.sessions',"INSERT INTO {}.sessions VALUES('bad')",'CREATE TABLE {}.bad(id text)','DROP TABLE {}.sessions'):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    limited.execute(sql.SQL(statement).format(sql.Identifier(prod)))
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                limited.execute('SELECT * FROM viva_provider_coordination.leases')
        settings=Settings(_env_file=None,database_url=SecretStr(runtime_dsn),database_schema=schema,
            database_path=tmp_path/'unused',tts_cache_dir=tmp_path/'cache',gnani_api_key=None,groq_api_key=None,env='test')
        for _ in range(2):
            with TestClient(create_app(settings)) as client:
                assert client.get('/api/v1/meta/health').status_code == 200
                result=client.post('/api/v1/sessions',json={'exercise_id':'ex1_shortest_subarray','spec_version':'v1_positive_only'})
                assert result.status_code == 200,result.text
    finally:
        with psycopg.connect(DSN,autocommit=True) as admin:
            for name in (schema,prod):
                admin.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(name)))
            admin.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(role)))


def test_remote_provisioning_rejected_before_connection():
    with pytest.raises(ValueError,match='Remote provisioning is disabled'):
        provision('postgresql://invalid.invalid/test')


def test_existing_public_data_grants_fail_closed():
    suffix=uuid4().hex
    schema,role,prod='stage_'+suffix,'role_'+suffix,'production_'+suffix
    with psycopg.connect(DSN,autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(prod)))
        admin.execute(sql.SQL('CREATE TABLE {}.sessions(id text)').format(sql.Identifier(prod)))
        admin.execute(sql.SQL('GRANT SELECT ON {}.sessions TO PUBLIC').format(sql.Identifier(prod)))
    try:
        with pytest.raises(ValueError,match='isolation failed'):
            provision(DSN,schema,role)
        with psycopg.connect(DSN,autocommit=True) as admin:
            assert not admin.execute('SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=%s)',(role,)).fetchone()[0]
            assert not admin.execute('SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=%s)',(schema,)).fetchone()[0]
    finally:
        with psycopg.connect(DSN,autocommit=True) as admin:
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(prod)))


def test_offline_preparation_protects_secret(tmp_path,monkeypatch,capsys):
    import json
    import stat
    from scripts.provision_preview_database import main
    output=tmp_path/'preview-private.json'
    monkeypatch.setattr('sys.argv',['provision_preview_database','--private-output',str(output)])
    main()
    data=json.loads(output.read_text())
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert data['role'] == 'mentorly_preview_20261115_runtime'
    assert len(data['password']) >= 48
    assert data['password'] not in capsys.readouterr().out
    assert not data['remote_ddl_authorized']


@pytest.mark.parametrize('dsn',[
    'postgresql://localhost/postgres?hostaddr=203.0.113.1',
    'host=127.0.0.1 hostaddr=203.0.113.1 dbname=postgres',
    'host=127.0.0.1 service=remote dbname=postgres',
    'host=127.0.0.1 options=-csearch_path=public dbname=postgres',
    'host=127.0.0.1,203.0.113.1 dbname=postgres',
    'host=localhost dbname=postgres',
])
def test_dsn_redirects_rejected_before_connection(monkeypatch,dsn):
    def forbidden(*args,**kwargs):
        pytest.fail('Guard must reject before connecting')
    monkeypatch.setattr(psycopg,'connect',forbidden)
    with pytest.raises(ValueError,match='Remote provisioning is disabled'):
        provision(dsn)


@pytest.mark.parametrize('name',['PGHOST','PGHOSTADDR','PGSERVICE','PGSERVICEFILE','PGOPTIONS'])
def test_libpq_environment_redirects_rejected_before_connection(monkeypatch,name):
    monkeypatch.setenv(name,'external-override')
    def forbidden(*args,**kwargs):
        pytest.fail('Guard must reject before connecting')
    monkeypatch.setattr(psycopg,'connect',forbidden)
    with pytest.raises(ValueError,match='Remote provisioning is disabled'):
        provision('host=127.0.0.1 dbname=postgres')


@pytest.mark.parametrize('privilege',['SELECT','INSERT','UPDATE','REFERENCES'])
def test_public_column_grants_fail_closed(privilege):
    suffix=uuid4().hex
    schema,role,prod='stage_'+suffix,'role_'+suffix,'production_'+suffix
    with psycopg.connect(DSN,autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(prod)))
        admin.execute(sql.SQL('CREATE TABLE {}.sessions(id text)').format(sql.Identifier(prod)))
        admin.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO PUBLIC').format(sql.Identifier(prod)))
        admin.execute(sql.SQL('GRANT '+privilege+'(id) ON {}.sessions TO PUBLIC').format(sql.Identifier(prod)))
    try:
        with pytest.raises(ValueError,match='isolation failed'):
            provision(DSN,schema,role)
        with psycopg.connect(DSN,autocommit=True) as admin:
            assert not admin.execute('SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=%s)',(role,)).fetchone()[0]
            assert not admin.execute('SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=%s)',(schema,)).fetchone()[0]
    finally:
        with psycopg.connect(DSN,autocommit=True) as admin:
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(prod)))


def test_local_account_scope_and_two_provider_enabled_instances(tmp_path):
    import asyncio
    import base64
    import httpx
    from backend.app.db.postgres.runtime import PostgresTarget
    from scripts.provision_preview_database import account_digest
    suffix = uuid4().hex[:16]
    schema, role = 'stage_' + suffix, 'role_' + suffix
    key, other_key = 'synthetic-account-' + suffix, 'different-account-' + suffix
    digest, other = account_digest(key), account_digest(other_key)
    runtime_dsn = None
    # Explicit disposable test setup, never part of the provisioning helper.
    with psycopg.connect(DSN, autocommit=True) as admin:
        rls_before = dict(admin.execute("SELECT c.relname,c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='viva_provider_coordination' AND c.relname IN ('accounts','leases')").fetchall())
        for table in ('accounts', 'leases'):
            admin.execute(sql.SQL('ALTER TABLE viva_provider_coordination.{} ENABLE ROW LEVEL SECURITY').format(sql.Identifier(table)))
    try:
        runtime_dsn = provision(DSN, schema, role, account_key=key)
        with psycopg.connect(DSN, autocommit=True) as admin:
            admin.execute('INSERT INTO viva_provider_coordination.accounts VALUES(%s,1)', (other,))
            admin.execute("INSERT INTO viva_provider_coordination.leases(id,account_hash,state,expires_at) VALUES(%s,%s,'INFLIGHT',clock_timestamp()+interval '1 minute')", ('other-'+suffix, other))
        with psycopg.connect(runtime_dsn, autocommit=True) as limited:
            assert limited.execute('SELECT account_hash FROM viva_provider_coordination.accounts').fetchall() == [(digest,)]
            assert limited.execute('SELECT * FROM viva_provider_coordination.leases WHERE account_hash=%s', (other,)).fetchall() == []
            assert limited.execute("UPDATE viva_provider_coordination.leases SET state='RELEASED' WHERE account_hash=%s", (other,)).rowcount == 0
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                limited.execute('UPDATE viva_provider_coordination.accounts SET capacity=2')
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                limited.execute("INSERT INTO viva_provider_coordination.leases(id,account_hash,state,expires_at) VALUES('bad',%s,'INFLIGHT',clock_timestamp())", (other,))
        settings=Settings(_env_file=None,database_url=SecretStr(runtime_dsn),database_schema=schema,
            database_path=tmp_path/'unused',tts_cache_dir=tmp_path/'cache',gnani_api_key=SecretStr(key),groq_api_key=None,env='test', max_concurrency=1)
        app1, app2 = create_app(settings), create_app(settings)
        with TestClient(app1) as client1, TestClient(app2) as client2:
            first = app1.state.speech.gatekeeper._account_dispatcher
            second = app2.state.speech.gatekeeper._account_dispatcher
            lease = first.reserve()
            assert lease and second.reserve() is None
            first.start(lease)
            first.finish(lease)
            lease2 = second.reserve()
            assert lease2 is not None
            second.finish(lease2)
            calls = []
            audio = base64.b64encode(b'\0\0' * 1600).decode()
            stream = f'event: chunk\ndata: {{"chunk_index":1,"audio":"{audio}"}}\n\nevent: complete\ndata: {{"chunk_index":2,"audio":"","is_final":true}}\n\n'
            def respond(request):
                calls.append(request.url.host)
                return httpx.Response(200, content=stream)
            provider = httpx.AsyncClient(transport=httpx.MockTransport(respond))
            app1.state.speech.adapter._http_client = provider
            app2.state.speech.adapter._http_client = provider
            try:
                for client in (client1, client2):
                    response = client.post('/api/v1/sessions', json={'exercise_id': 'ex1_shortest_subarray', 'spec_version': 'v1_positive_only'})
                    assert response.status_code == 200, response.text
                    session = response.json()
                    voice = client.post('/api/v1/sessions/'+session['session_id']+'/speech/introduction',
                        headers={'Authorization': 'Bearer '+session['session_token'], 'X-Idempotency-Key': str(uuid4())},
                        json={'revision': session['revision']})
                    assert voice.status_code == 200, voice.text
                assert calls and len(calls) <= 2
                with psycopg.connect(runtime_dsn) as check:
                    assert check.execute('SELECT capacity FROM viva_provider_coordination.accounts').fetchone() == (1,)
                    assert check.execute("SELECT count(*) FROM viva_provider_coordination.leases WHERE state IN ('INFLIGHT','UNDISPATCHED','UNCERTAIN')").fetchone()[0] == 0
            finally:
                asyncio.run(provider.aclose())
    finally:
        with psycopg.connect(DSN, autocommit=True) as admin:
            for table in ('accounts', 'leases'):
                admin.execute(sql.SQL('DROP POLICY IF EXISTS {} ON viva_provider_coordination.{}').format(sql.Identifier('preview_'+role+'_'+table), sql.Identifier(table)))
            admin.execute('DELETE FROM viva_provider_coordination.leases WHERE account_hash IN (%s,%s)', (digest,other))
            admin.execute('DELETE FROM viva_provider_coordination.accounts WHERE account_hash IN (%s,%s)', (digest,other))
            admin.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(schema)))
            admin.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
            admin.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(role)))
            for table, enabled in rls_before.items():
                if not enabled:
                    admin.execute(sql.SQL('ALTER TABLE viva_provider_coordination.{} DISABLE ROW LEVEL SECURITY').format(sql.Identifier(table)))


def test_account_grant_refuses_disabled_rls_without_affecting_existing_role():
    from scripts.provision_preview_database import grant_account
    suffix = uuid4().hex[:16]
    existing, preview = 'existing_'+suffix, 'preview_'+suffix
    account = 'existing-'+suffix
    with psycopg.connect(DSN) as admin:
        try:
            for table in ('accounts', 'leases'):
                admin.execute(sql.SQL('ALTER TABLE viva_provider_coordination.{} DISABLE ROW LEVEL SECURITY').format(sql.Identifier(table)))
            for name in (existing, preview):
                admin.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(sql.Identifier(name)))
            admin.execute(sql.SQL('GRANT USAGE ON SCHEMA viva_provider_coordination TO {}').format(sql.Identifier(existing)))
            admin.execute(sql.SQL('GRANT SELECT ON viva_provider_coordination.accounts TO {}').format(sql.Identifier(existing)))
            admin.execute(sql.SQL('GRANT SELECT, INSERT, UPDATE ON viva_provider_coordination.leases TO {}').format(sql.Identifier(existing)))
            admin.execute(sql.SQL('GRANT USAGE ON SEQUENCE viva_provider_coordination.leases_fence_seq TO {}').format(sql.Identifier(existing)))
            admin.execute('INSERT INTO viva_provider_coordination.accounts VALUES(%s,1)', (account,))
            admin.execute(sql.SQL('SET LOCAL ROLE {}').format(sql.Identifier(existing)))
            assert admin.execute('SELECT capacity FROM viva_provider_coordination.accounts WHERE account_hash=%s', (account,)).fetchone() == (1,)
            admin.execute("INSERT INTO viva_provider_coordination.leases(id,account_hash,state,expires_at) VALUES(%s,%s,'UNDISPATCHED',clock_timestamp()+interval '1 minute')", ('existing-'+suffix, account))
            admin.execute("UPDATE viva_provider_coordination.leases SET state='INFLIGHT' WHERE id=%s", ('existing-'+suffix,))
            admin.execute('RESET ROLE')
            with pytest.raises(ValueError, match='RLS must be preinstalled'):
                grant_account(admin, preview, 'synthetic-'+suffix)
            assert admin.execute("SELECT bool_and(NOT c.relrowsecurity) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='viva_provider_coordination' AND c.relname IN ('accounts','leases')").fetchone()[0]
            admin.execute(sql.SQL('SET LOCAL ROLE {}').format(sql.Identifier(existing)))
            assert admin.execute('SELECT capacity FROM viva_provider_coordination.accounts WHERE account_hash=%s', (account,)).fetchone() == (1,)
            assert admin.execute("UPDATE viva_provider_coordination.leases SET state='RELEASED' WHERE id=%s", ('existing-'+suffix,)).rowcount == 1
            admin.execute('RESET ROLE')
        finally:
            admin.rollback()
