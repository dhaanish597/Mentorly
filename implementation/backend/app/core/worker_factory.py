"""One trusted worker registry per application configuration.

Cloud execution has no HTTP broker. Its private PostgreSQL ledger serializes
jobs and VM creation across instances; credentials never enter learner assets.
"""
from __future__ import annotations

import threading
import hashlib

from backend.app.db.postgres.runtime import PostgresTarget
from backend.app.db.repository import SQLiteRepository
from backend.app.orchestration.worker_client import WorkerClient

_FACTORY_LOCK = threading.RLock()
OPERATOR_CANARY_SOURCE = "def first_at_least(nums, target):\n    return 0\n"
OPERATOR_CANARY_INPUT = {"nums": [0], "target": 0}


def get_worker_client(settings):
    """Build once, including cancellation while public execution is disabled."""
    target = settings.database_target
    target_configuration = (target.identity, hashlib.sha256(target.dsn.encode()).hexdigest()) if isinstance(target, PostgresTarget) else str(target)
    configuration = (settings.execution_runtime, target_configuration,
        str(settings.vercel_sandbox_acceptance_path), settings.vercel_sandbox_acceptance_sha256,
        settings.allow_public_custom_code, settings.public_execution_enabled,
        settings.exec_worker_url, settings.internal_worker_secret)
    with _FACTORY_LOCK:
        if settings._trusted_worker_configuration is not None:
            if settings._trusted_worker_configuration != configuration:
                raise RuntimeError('Execution configuration changed; restart the application')
            return settings._trusted_worker
        repository = SQLiteRepository(target)
        if settings.execution_runtime == 'vercel_sandbox':
            if not isinstance(target, PostgresTarget):
                raise RuntimeError('Cloud execution requires verified shared PostgreSQL')
            from exec_worker.vercel_sandbox.cleanup_store import PostgresSandboxCleanupStore
            from exec_worker.vercel_sandbox.adapter import VercelSandboxRunner, VercelSandboxTransport
            from exec_worker.vercel_sandbox.integration import InProcessWorkerClient
            cleanup = PostgresSandboxCleanupStore(lambda: target, enforce_execution_limits=True, require_repository_job=True)
            transport = VercelSandboxTransport(cleanup_store=cleanup)
            runner = VercelSandboxRunner(transport=transport,
                acceptance_path=settings.vercel_sandbox_acceptance_path or '',
                acceptance_sha256=settings.vercel_sandbox_acceptance_sha256,
                public_execution_enabled=lambda: settings.allow_public_custom_code and settings.public_execution_enabled)
            worker = InProcessWorkerClient(runner=runner, session_repository=repository,
                allow_public_custom_code=settings.allow_public_custom_code,
                external_cancel_check=cleanup.job_cancelled, execution_store=cleanup,
                cloud_runtime=True)
        elif settings.internal_worker_secret:
            worker = WorkerClient(base_url=settings.exec_worker_url,
                internal_worker_secret=settings.internal_worker_secret.get_secret_value(),
                allow_public_custom_code=settings.allow_public_custom_code,
                session_repository=repository)
        else:
            worker = None
        settings._trusted_worker = worker
        settings._trusted_worker_configuration = configuration
        return worker
