"""Fixed acceptance controls share real local admission; no VMs are created."""
from contextlib import closing
import sys
import threading
from uuid import uuid4

import pytest

from backend.app.db.migrations import open_connection
from exec_worker.vercel_sandbox import live_acceptance as cli
from exec_worker.vercel_sandbox.adapter import TransportFailure
from exec_worker.vercel_sandbox.cleanup_store import PostgresSandboxCleanupStore
from exec_worker.tests.test_postgres_sandbox_cleanup import target, DSN, name

pytestmark = pytest.mark.skipif(not DSN,reason='disposable local PostgreSQL required')


class InertTransport:
    def __init__(self,target,*,ambiguous=False):
        self.cleanup_store = PostgresSandboxCleanupStore(lambda:target,enforce_execution_limits=True,require_repository_job=True)
        self.cleanup_obligations = set()
        self.lock = threading.Lock()
        self.ready_jobs = set()
        self.calls = []
        self.ambiguous = ambiguous
    def run(self,*,job_id,payload,budget,dispatch_deadline):
        self.calls.append(job_id)
        sandbox_name = name()
        self.cleanup_store.register(sandbox_name,job_id)
        if self.ambiguous:
            self.cleanup_store.require_cleanup(sandbox_name)
            self.cleanup_obligations.add(sandbox_name)
            raise TransportFailure('Controlled ambiguous creation')
        self.cleanup_store.acknowledge(sandbox_name)
        self.cleanup_store.complete(sandbox_name)
        return {'runtime':{'test':'inert'},'reason':'exited','duration_ms':1,'events':{},'limits':{},'cleanup_verified':True}


def control_payload():
    import hashlib
    budget = cli._control_budget('return')
    source = 'def f():\n'+'\n'.join(' '+line for line in cli.CONTROLS['return'].splitlines())
    return {'mode':'execute','function_name':'f','source_code':source,'source_hash':hashlib.sha256(source.encode()).hexdigest(),
        'input_args':{},'budget':budget.model_dump(mode='json'),'apply_rlimits':False},budget


def test_cli_controls_have_repository_binding_global_quota_and_exact_32_ceiling(target):
    raw = InertTransport(target)
    guarded = cli.GuardedAcceptanceTransport(raw)
    payload,budget = control_payload()
    for _ in range(32):
        guarded.run(job_id=uuid4(),payload=payload,budget=budget)
    with pytest.raises(TransportFailure,match='ceiling'):
        guarded.run(job_id=uuid4(),payload=payload,budget=budget)
    assert len(raw.calls)==32 and raw.cleanup_store.unresolved()==[]
    with closing(open_connection(target)) as connection:
        assert {row[0]:row[1] for row in connection.execute('SELECT period_kind,invocations FROM cloud_execution_budget')}=={'DAY':32,'MONTH':32}
        assert connection.execute('SELECT count(*) FROM cloud_execution_jobs WHERE active').fetchone()[0]==0
        # Disposable repository data is deleted; the independent ledger survives.
        assert connection.execute("SELECT count(*) FROM jobs WHERE job_type='ACCEPTANCE'").fetchone()[0]==0
        assert connection.execute('SELECT count(*) FROM cloud_execution_jobs').fetchone()[0]==32


def test_arbitrary_source_fails_before_any_admission_or_provider_boundary(target):
    raw = InertTransport(target)
    guarded = cli.GuardedAcceptanceTransport(raw)
    payload,budget = control_payload()
    with pytest.raises(TransportFailure,match='authored finite'):
        guarded.run(job_id=uuid4(),payload={**payload,'source_code':'print("arbitrary")'},budget=budget)
    assert raw.calls==[] and raw.cleanup_store.unresolved()==[]
    with closing(open_connection(target)) as connection:
        assert connection.execute('SELECT count(*) FROM cloud_execution_jobs').fetchone()[0]==0


def test_unknown_creation_blocks_next_control_and_keeps_charge(target):
    raw = InertTransport(target,ambiguous=True)
    guarded = cli.GuardedAcceptanceTransport(raw)
    payload,budget = control_payload()
    with pytest.raises(TransportFailure,match='cleanup remains unconfirmed'):
        guarded.run(job_id=uuid4(),payload=payload,budget=budget)
    with pytest.raises(TransportFailure,match='capacity'):
        guarded.run(job_id=uuid4(),payload=payload,budget=budget)
    assert len(raw.calls)==1 and len(raw.cleanup_store.unresolved())==1
    with closing(open_connection(target)) as connection:
        assert {row[0]:row[1] for row in connection.execute('SELECT period_kind,invocations FROM cloud_execution_budget')}=={'DAY':1,'MONTH':1}


def test_suite_stops_after_first_failed_native_control(target,monkeypatch,tmp_path):
    raw = InertTransport(target)
    monkeypatch.setattr(cli,'runner_digest',lambda:'a'*64)
    monkeypatch.setattr(cli,'_passed',lambda *args:False)
    evidence = cli.run_acceptance(raw,tmp_path/'failed.json')
    assert len(raw.calls)==1 and len(evidence['controls'])==1
    assert evidence['accepted'] is False and evidence['blockers'][0]['phase']=='control'


def test_cli_local_database_requires_explicit_policy_and_exact_runtime(target,monkeypatch,tmp_path):
    monkeypatch.delenv('VERCEL',raising=False)
    monkeypatch.setenv('VCC_DATABASE_URL',DSN)
    captured = []
    monkeypatch.setattr(cli,'run_acceptance',lambda transport,path:captured.append(transport) or {'accepted':False})
    base = ['live_acceptance','--output',str(tmp_path/'evidence.json'),'--confirmed-free-hobby','--postgres-schema',target.schema]
    monkeypatch.setattr(sys,'argv',base)
    with pytest.raises(ValueError,match='test permission'):
        cli.main()
    assert captured==[]
    monkeypatch.setattr(sys,'argv',base+['--allow-local-postgres-for-acceptance'])
    with pytest.raises(SystemExit) as exit:
        cli.main()
    assert exit.value.code==1
    assert captured[0].cleanup_store.enforces_execution_limits and captured[0].cleanup_store.requires_repository_job
