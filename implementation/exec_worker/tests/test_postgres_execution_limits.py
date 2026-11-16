"""Real local database races and limits; every VM name remains inert data."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from uuid import uuid4

import pytest

from backend.app.db.migrations import open_connection
from exec_worker.vercel_sandbox.cleanup_store import PostgresSandboxCleanupStore
from exec_worker.tests.test_postgres_sandbox_cleanup import target, name, DSN

pytestmark = pytest.mark.skipif(not DSN, reason='disposable local PostgreSQL required')


def store(target):
    return PostgresSandboxCleanupStore(lambda: target, enforce_execution_limits=True)


def counts(target):
    with closing(open_connection(target)) as connection:
        return {row[0]: row[1] for row in connection.execute('SELECT period_kind,invocations FROM cloud_execution_budget')}


def test_distinct_process_owners_share_one_job_slot_and_owner_fence(target):
    stores = [store(target) for _ in range(8)]
    ids = [uuid4() for _ in stores]
    with ThreadPoolExecutor(max_workers=8) as pool:
        acquired = list(pool.map(lambda item: item[0].acquire_job(item[1]), zip(stores, ids)))
    assert acquired.count(True) == 1
    winner = acquired.index(True)
    assert not stores[(winner + 1) % 8].finish_job(ids[winner])
    assert stores[winner].finish_job(ids[winner])
    assert stores[0].acquire_job(uuid4())


def test_registration_requires_owned_live_job_and_burns_no_quota_when_rejected(target):
    first, other = store(target), store(target)
    jid = uuid4()
    with pytest.raises(RuntimeError, match='unavailable'):
        first.register(name(), jid)
    assert first.acquire_job(jid)
    with pytest.raises(RuntimeError, match='unavailable'):
        other.register(name(), jid)
    assert counts(target) == {}
    with closing(open_connection(target)) as connection:
        connection.execute("UPDATE cloud_execution_jobs SET expires_at=clock_timestamp()-INTERVAL '1 second'")
    with pytest.raises(RuntimeError, match='unavailable'):
        first.register(name(), jid)
    assert counts(target) == {}


def test_one_invocation_across_parallel_creations_and_no_quota_refund(target):
    cleanup, jid = store(target), uuid4()
    assert cleanup.acquire_job(jid)
    names = [name() for _ in range(8)]

    def register(sandbox_name):
        try:
            cleanup.register(sandbox_name, jid)
        except RuntimeError as exc:
            assert 'capacity' in str(exc)
            return False
        return True

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(register, names))
    assert outcomes.count(True) == 1
    assert counts(target) == {'DAY': 1, 'MONTH': 1}
    assert not cleanup.finish_job(jid)
    cleanup.complete(names[outcomes.index(True)])
    assert cleanup.finish_job(jid)
    assert counts(target) == {'DAY': 1, 'MONTH': 1}


@pytest.mark.parametrize('kind,ceiling', [('DAY', 100), ('MONTH', 500)])
def test_quota_exact_ceiling_refuses_next_create_without_counter_drift(target, kind, ceiling):
    cleanup, jid = store(target), uuid4()
    assert cleanup.acquire_job(jid)
    initial = name()
    cleanup.register(initial, jid)
    cleanup.complete(initial)
    with closing(open_connection(target)) as connection:
        connection.execute('UPDATE cloud_execution_budget SET invocations=? WHERE period_kind=?', (ceiling - 1, kind))
    last = name()
    cleanup.register(last, jid)
    cleanup.complete(last)
    before = counts(target)
    assert before[kind] == ceiling and not cleanup.quota_available()
    with pytest.raises(RuntimeError, match='quota exhausted'):
        cleanup.register(name(), jid)
    assert counts(target) == before and cleanup.unresolved() == []


def test_ambiguous_creation_never_expires_into_free_capacity(target):
    first, restarted, jid = store(target), store(target), uuid4()
    assert first.acquire_job(jid)
    sandbox_name = name()
    first.register(sandbox_name, jid)
    first.require_cleanup(sandbox_name)
    with closing(open_connection(target)) as connection:
        connection.execute("UPDATE cloud_execution_jobs SET expires_at=clock_timestamp()-INTERVAL '1 day'")
        connection.execute("UPDATE viva_sandbox_cleanup SET recovery_not_before=clock_timestamp()-INTERVAL '1 day'")
    assert not restarted.acquire_job(uuid4())
    assert not restarted.cancellation_confirmed(jid)
    assert restarted.claim_expired() == [(sandbox_name, False)]
    assert not restarted.acquire_job(uuid4())
    assert counts(target) == {'DAY': 1, 'MONTH': 1}


def test_durable_cancel_before_and_during_dispatch_survives_restart(target):
    first, restarted = store(target), store(target)
    before = uuid4()
    restarted.request_cancel(before)
    assert first.job_cancelled(before) and not first.acquire_job(before)
    jid = uuid4()
    assert first.acquire_job(jid)
    restarted.request_cancel(jid)
    assert first.job_cancelled(jid) and not restarted.cancellation_confirmed(jid)
    with pytest.raises(RuntimeError, match='cancelled'):
        first.register(name(), jid)
    assert first.finish_job(jid) and restarted.cancellation_confirmed(jid)
    assert counts(target) == {}


def test_confirmed_vm_deletion_and_expired_job_allow_safe_restart_recovery(target):
    first, restarted, jid = store(target), store(target), uuid4()
    assert first.acquire_job(jid)
    sandbox_name = name()
    first.register(sandbox_name, jid)
    first.acknowledge(sandbox_name)
    restarted.request_cancel(jid)
    assert not restarted.cancellation_confirmed(jid)
    with closing(open_connection(target)) as connection:
        connection.execute("UPDATE cloud_execution_jobs SET expires_at=clock_timestamp()-INTERVAL '1 second'")
        connection.execute("UPDATE viva_sandbox_cleanup SET recovery_not_before=clock_timestamp()-INTERVAL '1 second'")
    assert restarted.claim_expired() == [(sandbox_name, True)]
    restarted.complete(sandbox_name)
    assert restarted.cancellation_confirmed(jid)
    assert restarted.acquire_job(uuid4())
    with pytest.raises(RuntimeError, match='unavailable'):
        first.register(name(), jid)
