"""Trusted cloud factory, dispatch and cancellation against local PostgreSQL.

All runner/provider work is controlled doubles; learner source is never executed.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.core.worker_factory import get_worker_client, OPERATOR_CANARY_SOURCE, OPERATOR_CANARY_INPUT
from backend.app.core.execution_readiness import probe_execution_readiness
from backend.app.db.migrations import open_connection
from backend.app.db.repository import SQLiteRepository
from backend.app.exercises import registry
from backend.app.models.domain import ExecutionRequest, ExecutionObservation, ExecutionBudgetConfig, RevisionRef
from backend.app.orchestration.worker_client import BrokerCommunicationError
from backend.app.operations.readiness import _run_canary
from exec_worker.vercel_sandbox.adapter import TransportFailure
from exec_worker.vercel_sandbox.cleanup_store import PostgresSandboxCleanupStore
from exec_worker.tests.test_postgres_sandbox_cleanup import target, DSN, name

pytestmark = pytest.mark.skipif(not DSN, reason='disposable local PostgreSQL required')


def settings(target, **options):
    class LocalSettings(Settings):
        @property
        def database_target(self):
            return target
    return LocalSettings(env='test', cloud_runtime=True, execution_runtime='vercel_sandbox',
        gnani_api_key=None, groq_api_key=None, **options)


def request(target, *, budget=None):
    repository = SQLiteRepository(target)
    sid, jid = uuid4(), uuid4()
    source_hash = hashlib.sha256(OPERATOR_CANARY_SOURCE.encode()).hexdigest()
    repository.create_session(session_id=str(sid), token_hash=str(uuid4()), exercise_id='ex2_binary_search',
        spec_version='v1_sorted_with_duplicates', language_mode='en-IN', interaction_mode='TEXT',
        starter_code=OPERATOR_CANARY_SOURCE, starter_code_hash=source_hash,
        expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
    revision = RevisionRef(session_id=sid, exercise_id='ex2_binary_search',
        spec_version='v1_sorted_with_duplicates', code_version_id=1, code_hash=source_hash, turn_generation=0)
    repository.register_execution_job(str(sid), str(jid), 'EXECUTE', revision, '')
    req = ExecutionRequest(job_id=jid, revision=revision, source_code=OPERATOR_CANARY_SOURCE,
        input_args=OPERATOR_CANARY_INPUT, case_hash=registry.case_key('ex2_binary_search', 'v1_sorted_with_duplicates', OPERATOR_CANARY_INPUT), budget=budget or ExecutionBudgetConfig())
    return repository, req


def observation():
    return ExecutionObservation(kind='RETURN', return_value=0, stdout_excerpt='', stderr_excerpt='', duration_ms=2)


def accept_double(monkeypatch):
    from exec_worker.vercel_sandbox import adapter, acceptance
    monkeypatch.setattr(adapter, 'version', lambda package: acceptance.SDK_VERSIONS[package])
    monkeypatch.setattr(adapter, 'load_acceptance', lambda *args: {'runtime': {'kernel': 'controlled-test'}})


def run_double(worker, monkeypatch, *, capture=None, entered=None, release=None):
    cleanup = worker._execution_store
    def execute(req):
        sandbox_name = name()
        cleanup.register(sandbox_name, req.job_id)
        cleanup.acknowledge(sandbox_name)
        if capture is not None:
            capture.append((req, worker.runner._dispatch_local.deadline))
        if entered is not None:
            entered.set()
            assert release.wait(3)
        cleanup.complete(sandbox_name)
        return observation()
    monkeypatch.setattr(worker.runner, 'execute', execute)
    if release is not None:
        monkeypatch.setattr(worker.runner, 'cancel_invocation', lambda jid: release.set())


def test_cloud_factory_cached_for_routes_startup_and_retention_without_http(target, monkeypatch):
    value = settings(target)
    from backend.app.core import worker_factory
    monkeypatch.setattr(worker_factory, 'WorkerClient', lambda **kwargs: pytest.fail('cloud must not construct HTTP broker'))
    worker = get_worker_client(value)
    assert worker is get_worker_client(value)
    assert worker.runner.transport.cleanup_store is worker._execution_store
    assert worker._execution_store.enforces_execution_limits and worker._execution_store.requires_repository_job
    from backend.app.main import create_app
    with TestClient(create_app(value)) as client:
        assert client.app.state.worker is worker
        assert client.app.state.retention.worker_client is worker
        assert client.get('/api/v1/meta/health').status_code == 200


def test_validated_settings_gate_overrides_ambient_enable_and_keeps_cancel_available(target, monkeypatch):
    monkeypatch.setenv('VCC_PUBLIC_EXECUTION_ENABLED', 'true')
    accept_double(monkeypatch)
    value = settings(target, allow_public_custom_code=False, public_execution_enabled=False)
    worker = get_worker_client(value)
    assert not worker.check_preflight().ready
    assert asyncio.run(probe_execution_readiness(value)) == 'DISABLED'
    assert worker.cancel(uuid4()) is True
    assert worker.check_canary_preflight().ready
    assert not worker.check_preflight().ready


def test_cloud_readiness_acceptance_and_route_use_same_cached_registry(target, monkeypatch):
    value = settings(target, allow_public_custom_code=True, public_execution_enabled=True)
    assert asyncio.run(probe_execution_readiness(value)) == 'BLOCKED_EXTERNAL'
    accept_double(monkeypatch)
    assert asyncio.run(probe_execution_readiness(value)) == 'READY'
    from backend.app.api import routes_sessions
    monkeypatch.setattr(routes_sessions, 'get_settings', lambda: value)
    _, machine = routes_sessions._get_repo_and_machine()
    assert machine.worker_client is get_worker_client(value)


def test_explicit_empty_acceptance_never_inherits_ambient_path_or_hash(target, monkeypatch):
    monkeypatch.setenv('VCC_VERCEL_SANDBOX_ACCEPTANCE_PATH', '/ambient/acceptance')
    monkeypatch.setenv('VCC_VERCEL_SANDBOX_ACCEPTANCE_SHA256', 'a' * 64)
    value = settings(target, vercel_sandbox_acceptance_path=None, vercel_sandbox_acceptance_sha256='')
    worker = get_worker_client(value)
    assert worker.runner.acceptance_path == '' and worker.runner.acceptance_sha256 == ''


def test_settings_change_requires_restart_instead_of_forking_registry(target):
    value = settings(target)
    worker = get_worker_client(value)
    value.vercel_sandbox_acceptance_sha256 = 'a' * 64
    with pytest.raises(RuntimeError, match='restart'):
        get_worker_client(value)
    assert value._trusted_worker is worker


def test_cloud_startup_and_dispatch_deadline_are_bounded(target, monkeypatch):
    worker = get_worker_client(settings(target))
    captured = []
    run_double(worker, monkeypatch, capture=captured)
    _, req = request(target, budget=ExecutionBudgetConfig(startup_deadline_ms=1000, job_wall_ms=300000))
    started = time.monotonic()
    raw = worker._post_json('/internal/execute', req.model_dump(mode='json'), timeout_seconds=300)
    actual, deadline = captured[0]
    assert raw['kind'] == 'RETURN'
    assert actual.budget.startup_deadline_ms == 5000 and actual.budget.job_wall_ms == 235000
    assert deadline - started <= 240.5
    assert worker.runner._dispatch_local.__dict__ == {}


def test_cross_instance_cancel_is_pending_then_stops_active_dispatch(target, monkeypatch):
    first, other = get_worker_client(settings(target)), get_worker_client(settings(target))
    started, release = threading.Event(), threading.Event()
    run_double(first, monkeypatch, entered=started, release=release)
    _, req = request(target)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(first.submit_execution, req)
        assert started.wait(2)
        assert other.cancel(req.job_id) is False
        handle = result.result(timeout=3)
    assert handle.status == 'SUPERSEDED' and handle.observation is None
    assert release.is_set() and other.cancel(req.job_id) is True
    assert first._execution_store.unresolved() == []


def test_deleted_revision_stops_dispatch_and_never_delivers_result(target, monkeypatch):
    worker = get_worker_client(settings(target))
    started, release = threading.Event(), threading.Event()
    run_double(worker, monkeypatch, entered=started, release=release)
    repository, req = request(target)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(worker.submit_execution, req)
        assert started.wait(2)
        repository.tombstone_session(str(req.revision.session_id))
        handle = result.result(timeout=3)
    assert handle.status == 'CANCELLED' and handle.observation is None
    assert release.is_set() and worker._execution_store.unresolved() == []


@pytest.mark.parametrize('mutation', ['deleted', 'cancelled', 'code', 'spec', 'missing'])
def test_atomic_registration_rechecks_repository_before_provider_boundary(target, mutation):
    repository, req = request(target)
    cleanup = PostgresSandboxCleanupStore(lambda: target, enforce_execution_limits=True, require_repository_job=True)
    assert cleanup.acquire_job(req.job_id)
    with closing(open_connection(target)) as connection:
        if mutation=='deleted':
            connection.execute("UPDATE sessions SET deleted_at='2026-11-15T00:00:00+00:00' WHERE id=?", (str(req.revision.session_id),))
        elif mutation=='cancelled':
            connection.execute("UPDATE jobs SET status='CANCEL_REQUESTED' WHERE id=?", (str(req.job_id),))
        elif mutation=='code':
            connection.execute("UPDATE sessions SET active_code_version_id=2 WHERE id=?", (str(req.revision.session_id),))
        elif mutation=='spec':
            connection.execute("UPDATE sessions SET spec_version='different' WHERE id=?", (str(req.revision.session_id),))
        else:
            connection.execute('DELETE FROM jobs WHERE id=?', (str(req.job_id),))
    with pytest.raises(RuntimeError):
        cleanup.register(name(), req.job_id)
    assert cleanup.unresolved() == []
    with closing(open_connection(target)) as connection:
        assert connection.execute('SELECT count(*) FROM cloud_execution_budget').fetchone()[0] == 0


def test_operator_canary_is_fixed_and_independent_of_public_gate(target, monkeypatch):
    accept_double(monkeypatch)
    value = settings(target)
    worker = get_worker_client(value)
    captured = []
    run_double(worker, monkeypatch, capture=captured)
    result = asyncio.run(_run_canary(value))
    assert result[0] is True and result[1]=='PASSED'
    assert captured[0][0].source_code == OPERATOR_CANARY_SOURCE
    assert captured[0][0].input_args == OPERATOR_CANARY_INPUT
    assert not worker.check_preflight().ready
    _, arbitrary = request(target)
    arbitrary = arbitrary.model_copy(update={'source_code': 'print("arbitrary")'})
    with pytest.raises(PermissionError, match='fixed operator canary'):
        worker.runner.execute_operator_canary(arbitrary)


def test_expired_dispatch_never_reaches_sdk_creation(target, monkeypatch, tmp_path):
    worker = get_worker_client(settings(target))
    _, req = request(target)
    assert worker._execution_store.acquire_job(req.job_id)
    from exec_worker.vercel_sandbox import adapter
    asset = tmp_path / 'inert'
    asset.write_bytes(b'inert-test-only')
    monkeypatch.setattr(adapter, 'guest_files', lambda: {'inert': asset})
    monkeypatch.setattr(worker.runner.transport, '_client', lambda: pytest.fail('expired dispatch must not create provider client'))
    with pytest.raises(TransportFailure, match='cancelled before launch'):
        worker.runner.transport.run(job_id=req.job_id, payload={'mode':'execute'}, budget=req.budget, dispatch_deadline=time.monotonic()-1)
    assert worker._execution_store.unresolved() == []


def test_cancel_after_restart_recovers_only_acknowledged_expired_name(target, monkeypatch):
    first, restarted = get_worker_client(settings(target)), get_worker_client(settings(target))
    _, req = request(target)
    cleanup = first._execution_store
    assert cleanup.acquire_job(req.job_id)
    sandbox_name = name()
    cleanup.register(sandbox_name, req.job_id)
    cleanup.acknowledge(sandbox_name)
    with closing(open_connection(target)) as connection:
        connection.execute("UPDATE cloud_execution_jobs SET expires_at=clock_timestamp()-INTERVAL '1 second'")
        connection.execute("UPDATE viva_sandbox_cleanup SET recovery_not_before=clock_timestamp()-INTERVAL '1 second'")
    looked_up, closed = [], []
    class Absent(Exception):
        status_code = 404
    def absent(**options):
        looked_up.append(options['name'])
        raise Absent()
    monkeypatch.setattr(restarted.runner.transport, '_client', lambda: SimpleNamespace(get_sandbox=absent, close=lambda:closed.append(True)))
    assert restarted.cancel(req.job_id) is True
    assert looked_up==[sandbox_name] and closed==[True]
    assert cleanup.unresolved() == []


def test_asgi_cancel_works_with_public_disabled_after_owner_crash(target,monkeypatch):
    value = settings(target)
    first = get_worker_client(settings(target))
    repository,req = request(target)
    assert first._execution_store.acquire_job(req.job_id)
    sandbox_name = name()
    first._execution_store.register(sandbox_name,req.job_id)
    first._execution_store.acknowledge(sandbox_name)
    token = 'f'*64
    with closing(open_connection(target)) as connection:
        connection.execute('UPDATE sessions SET token_hash=? WHERE id=?',(hashlib.sha256(token.encode()).hexdigest(),str(req.revision.session_id)))
        connection.execute("UPDATE cloud_execution_jobs SET expires_at=clock_timestamp()-INTERVAL '1 second'")
        connection.execute("UPDATE viva_sandbox_cleanup SET recovery_not_before=clock_timestamp()-INTERVAL '1 second'")
    restarted = get_worker_client(value)
    looked_up = []
    class Absent(Exception):
        status_code=404
    def absent(**options):
        looked_up.append(options['name'])
        raise Absent()
    monkeypatch.setattr(restarted.runner.transport,'_client',lambda:SimpleNamespace(get_sandbox=absent,close=lambda:None))
    from backend.app.main import create_app
    with TestClient(create_app(value)) as client:
        response = client.post(f'/api/v1/sessions/{req.revision.session_id}/cancel',headers={'Authorization':'Bearer '+token,'X-Idempotency-Key':str(uuid4())},
            json={'scope':'TURN','job_id':str(req.job_id),'reason':'User cancelled'})
    assert response.status_code==200,response.text
    assert response.json()['cancelled_job_ids']==[str(req.job_id)]
    assert response.json()['unconfirmed_job_ids']==[] and looked_up==[sandbox_name]
    assert restarted._execution_store.unresolved()==[]
