"""Durable cleanup acceptance in isolated schemas on a local PostgreSQL cluster.

No cloud credentials or Sandbox requests are used. Provider recovery uses a
controlled 404 double; the remaining operations cross the real database boundary.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from backend.app.db.migrations import apply_migrations, get_applied_migrations, open_connection
from backend.app.db.postgres import runtime
from backend.app.db.postgres.runtime import PostgresTarget, _raw_connection, probe_runtime
from exec_worker.vercel_sandbox.adapter import TransportFailure, VercelSandboxTransport
from exec_worker.vercel_sandbox.cleanup_store import PostgresSandboxCleanupStore

DSN = os.environ.get("VIVA_POSTGRES_RUNTIME_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="set VIVA_POSTGRES_RUNTIME_TEST_DSN to a disposable local cluster")
MIGRATIONS = Path(runtime.__file__).with_name("runtime_migrations")


@pytest.fixture
def target():
    psycopg = pytest.importorskip("psycopg")
    host = psycopg.conninfo.conninfo_to_dict(DSN).get("host", "")
    assert host.startswith("/") or host in {"localhost", "127.0.0.1", "::1"}
    value = PostgresTarget(DSN, schema="viva_cleanup_test_" + uuid4().hex, allow_local=True)
    try:
        apply_migrations(value)
        yield value
    finally:
        with _raw_connection(value) as connection:
            connection.execute(psycopg.sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(psycopg.sql.Identifier(value.schema)))


def store(target):
    return PostgresSandboxCleanupStore(lambda: target)


def name():
    return "viva-inv-" + uuid4().hex[:24]


def expire(target):
    with closing(open_connection(target)) as connection:
        connection.execute("UPDATE viva_sandbox_cleanup SET recovery_not_before = CURRENT_TIMESTAMP - INTERVAL '1 second'")


def row(target, sandbox_name):
    with closing(open_connection(target)) as connection:
        return connection.execute("SELECT job_id,owner_id,creation_acknowledged,cleanup_required FROM viva_sandbox_cleanup WHERE sandbox_name=?", (sandbox_name,)).fetchone()


def test_registration_is_durable_private_and_independent_of_deleted_jobs(target):
    first, restarted = store(target), store(target)
    sandbox_name, job_id = name(), uuid4()
    first.register(sandbox_name, job_id)
    assert restarted.unresolved() == [sandbox_name]
    assert restarted.blocking() == []
    assert tuple(row(target, sandbox_name)) == (job_id, UUID(first.owner_id), False, False)
    with closing(open_connection(target)) as connection:
        assert connection.execute("SELECT count(*) FROM jobs WHERE id=?", (str(job_id),)).fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM information_schema.table_constraints WHERE table_schema=current_schema() AND table_name='viva_sandbox_cleanup' AND constraint_type='FOREIGN KEY'").fetchone()[0] == 0
        metadata = connection.execute("SELECT n.nspname,c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relname='viva_sandbox_cleanup' AND n.nspname=current_schema()").fetchone()
        assert tuple(metadata) == (target.schema, True)
        assert connection.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace,aclexplode(c.relacl) a WHERE c.relname='viva_sandbox_cleanup' AND n.nspname=current_schema() AND a.grantee=0").fetchone()[0] == 0
        for role in ("anon", "authenticated"):
            if connection.execute("SELECT 1 FROM pg_roles WHERE rolname=?", (role,)).fetchone():
                assert not connection.execute("SELECT has_schema_privilege(?,current_schema(),'USAGE')", (role,)).fetchone()[0]
                assert not connection.execute("SELECT has_table_privilege(?, 'viva_sandbox_cleanup', 'SELECT,INSERT,UPDATE,DELETE')", (role,)).fetchone()[0]


def test_duplicate_name_registration_never_overwrites_an_existing_obligation(target):
    first, second = store(target), store(target)
    sandbox_name, job_id = name(), uuid4()
    first.register(sandbox_name, job_id)
    for candidate, candidate_job in ((second, uuid4()), (second, job_id), (first, job_id)):
        with pytest.raises(RuntimeError, match="already registered"):
            candidate.register(sandbox_name, candidate_job)
    assert tuple(row(target, sandbox_name)) == (job_id, UUID(first.owner_id), False, False)


@pytest.mark.parametrize("invalid", ["foreign-vm", "viva-inv-" + "a" * 23, "viva-inv-" + "A" * 24, "viva-inv-" + "a" * 24 + "\n", None])
def test_invalid_names_cannot_reach_the_database(target, invalid):
    cleanup = store(target)
    for operation in (lambda: cleanup.register(invalid, uuid4()), lambda: cleanup.acknowledge(invalid), lambda: cleanup.require_cleanup(invalid), lambda: cleanup.complete(invalid)):
        with pytest.raises(ValueError, match="owned Sandbox name"):
            operation()
    assert cleanup.unresolved() == []


def test_invalid_job_identifier_cannot_create_obligation(target):
    cleanup = store(target)
    with pytest.raises(ValueError):
        cleanup.register(name(), "invalid")
    assert cleanup.unresolved() == []


def test_active_owner_is_required_for_every_cleanup_mutation(target):
    first, other = store(target), store(target)
    sandbox_name = name()
    first.register(sandbox_name, uuid4())
    for operation in (other.acknowledge, other.require_cleanup, other.complete):
        with pytest.raises(RuntimeError, match="ownership"):
            operation(sandbox_name)
    first.acknowledge(sandbox_name)
    first.require_cleanup(sandbox_name)
    assert first.blocking() == [sandbox_name]
    first.complete(sandbox_name)
    assert other.unresolved() == []


@pytest.mark.parametrize("expire_lease", [False, True])
def test_expired_or_cleanup_required_creation_cannot_be_acknowledged(target, expire_lease):
    cleanup = store(target)
    sandbox_name = name()
    cleanup.register(sandbox_name, uuid4())
    if expire_lease:
        expire(target)
    else:
        cleanup.require_cleanup(sandbox_name)
    with pytest.raises(RuntimeError, match="before learner launch"):
        cleanup.acknowledge(sandbox_name)
    assert row(target, sandbox_name)[2] is False


def test_restart_does_not_steal_live_owner_but_expired_lease_fences_stale_owner(target):
    first, restarted = store(target), store(target)
    sandbox_name = name()
    first.register(sandbox_name, uuid4())
    first.acknowledge(sandbox_name)
    assert restarted.claim_expired() == []
    expire(target)
    assert restarted.claim_expired() == [(sandbox_name, True)]
    assert row(target, sandbox_name)[1] == UUID(restarted.owner_id)
    assert restarted.claim_expired() == []
    for operation in (first.acknowledge, first.require_cleanup, first.complete):
        with pytest.raises(RuntimeError, match="ownership"):
            operation(sandbox_name)
    restarted.complete(sandbox_name)
    assert restarted.unresolved() == []


def test_competing_restart_instances_claim_each_name_once_in_bounded_batches(target):
    first = store(target)
    expected = {name() for _ in range(23)}
    for sandbox_name in expected:
        first.register(sandbox_name, uuid4())
    expire(target)
    owners = [store(target) for _ in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        batches = list(pool.map(lambda owner: owner.claim_expired(), owners))
    assert all(len(batch) <= 10 for batch in batches)
    claimed = [sandbox_name for batch in batches for sandbox_name, acknowledged in batch if acknowledged is False]
    assert len(claimed) == len(expected) and set(claimed) == expected
    for owner, batch in zip(owners, batches):
        for sandbox_name, _ in batch:
            assert row(target, sandbox_name)[1] == UUID(owner.owner_id)
    assert set(first.blocking()) == expected


@pytest.mark.parametrize("acknowledged", [False, True])
def test_provider_absence_clears_only_acknowledged_creation_during_recovery(target, acknowledged):
    first, restarted = store(target), store(target)
    sandbox_name = name()
    first.register(sandbox_name, uuid4())
    if acknowledged:
        first.acknowledge(sandbox_name)
    expire(target)

    class AbsentSandbox(Exception):
        status_code = 404

    def absent(**options):
        assert options == {"name": sandbox_name}
        raise AbsentSandbox()

    closed = []
    client = SimpleNamespace(get_sandbox=absent, close=lambda: closed.append(True))
    transport = VercelSandboxTransport(lambda: client, cleanup_store=restarted)
    if acknowledged:
        transport.recover_cleanup()
        assert restarted.unresolved() == []
    else:
        with pytest.raises(TransportFailure, match="inventory confirmation"):
            transport.recover_cleanup()
        assert restarted.unresolved() == restarted.blocking() == [sandbox_name]
        assert row(target, sandbox_name)[2:] == (False, True)
    assert closed == [True]


def test_cleanup_target_uses_pooler_safe_runtime_and_closes_each_connection(target, monkeypatch):
    psycopg = pytest.importorskip("psycopg")
    original = psycopg.connect
    connections, options = [], []

    def connect(**kwargs):
        options.append(kwargs)
        connection = original(**kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(psycopg, "connect", connect)
    cleanup = store(target)
    sandbox_name = name()
    cleanup.register(sandbox_name, uuid4())
    assert cleanup.unresolved() == [sandbox_name]
    assert len(connections) == 2 and all(connection.closed for connection in connections)
    assert all(option["autocommit"] is True and option["prepare_threshold"] is None and "options" not in option for option in options)
    # Explicit test/local permission is retained in the target, never inferred.
    with pytest.raises(ValueError, match="test permission"):
        PostgresSandboxCleanupStore(lambda: DSN).unresolved()


def test_cleanup_raises_when_backlog_exceeds_recovery_ceiling(target):
    cleanup = store(target)
    with closing(open_connection(target)) as connection:
        connection.execute("INSERT INTO viva_sandbox_cleanup(sandbox_name,job_id,owner_id) SELECT 'viva-inv-'||lpad(to_hex(i),24,'0'),CAST(? AS UUID),CAST(? AS UUID) FROM generate_series(1,1001) AS i", (str(uuid4()), cleanup.owner_id))
        connection.execute("UPDATE viva_sandbox_cleanup SET cleanup_required=TRUE")
    for read in (cleanup.unresolved, cleanup.blocking):
        with pytest.raises(RuntimeError, match="backlog"):
            read()


def test_cleanup_migration_upgrades_0006_without_rewriting_its_history(target, tmp_path):
    prior = replace(target, schema="viva_cleanup_upgrade_" + uuid4().hex)
    directory = tmp_path / "prior-runtime"
    directory.mkdir()
    try:
        for path in MIGRATIONS.glob("*.sql"):
            if path.name.split("_", 1)[0] < "0007":
                shutil.copy2(path, directory / path.name)
        assert apply_migrations(prior, directory) == ["0001", "0002", "0003", "0004", "0005", "0006"]
        before = [(migration.version, migration.checksum) for migration in get_applied_migrations(prior)]
        with closing(open_connection(prior)) as connection:
            connection.execute("INSERT INTO cloud_leases VALUES('retained','request','owner','HELD',100,90)")
        shutil.copy2(MIGRATIONS / "0007_sandbox_cleanup.sql", directory / "0007_sandbox_cleanup.sql")
        assert apply_migrations(prior, directory) == ["0007"]
        assert [(migration.version, migration.checksum) for migration in get_applied_migrations(prior)][:6] == before
        with closing(open_connection(prior)) as connection:
            assert connection.execute("SELECT owner FROM cloud_leases WHERE id='retained'").fetchone()[0] == "owner"
        cleanup = store(prior)
        sandbox_name = name()
        cleanup.register(sandbox_name, uuid4())
        assert cleanup.unresolved() == [sandbox_name]
        assert not probe_runtime(prior)
        shutil.copy2(MIGRATIONS / "0008_execution_limits.sql", directory / "0008_execution_limits.sql")
        assert apply_migrations(prior, directory) == ["0008"]
        assert probe_runtime(prior)
    finally:
        psycopg = pytest.importorskip("psycopg")
        with _raw_connection(prior) as connection:
            connection.execute(psycopg.sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(psycopg.sql.Identifier(prior.schema)))


def test_documented_cleanup_schema_matches_applied_migration():
    from exec_worker.vercel_sandbox import cleanup_store
    assert Path(cleanup_store.__file__).with_suffix(".sql").read_bytes() == (MIGRATIONS / "0007_sandbox_cleanup.sql").read_bytes()
