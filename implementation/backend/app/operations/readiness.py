"""Operator-only diagnostics and a fixed, genuinely isolated execution canary."""
from __future__ import annotations

import asyncio
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import sqlite3
import time
from uuid import uuid4

from fastapi import APIRouter, Header, Request

from backend.app.core.errors import ApiAppException
from backend.app.core.logging import get_logger

_LOGGER = get_logger("vcc.operations")
from backend.app.core.execution_readiness import probe_execution_readiness
from backend.app.exercises import registry
from backend.app.models.api_schemas import OperationsReadinessResponse
from backend.app.models.domain import ExecutionBudgetConfig, ExecutionRequest, RevisionRef
from backend.app.models.enums import ExecutionObservationKind
from backend.app.orchestration.worker_client import WorkerClient
from backend.app.core.worker_factory import get_worker_client, OPERATOR_CANARY_SOURCE, OPERATOR_CANARY_INPUT
from backend.app.db.repository import SQLiteRepository

router = APIRouter(prefix="/ops", tags=["operations"])
_CANARY_SOURCE = OPERATOR_CANARY_SOURCE
_CANARY_INPUT = OPERATOR_CANARY_INPUT
CANARY_TIMEOUT_SECONDS = 8.0
DATABASE_CHECK_SECONDS = 0.5


def _require_operator(request: Request, authorization: str | None) -> None:
    configured = request.app.state.settings.operations_token
    expected = configured.get_secret_value() if configured is not None else ""
    candidate = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
    if not 32 <= len(expected) <= 256 or not candidate or len(candidate) > 256:
        raise ApiAppException(status_code=403, code="OPERATOR_AUTH_REQUIRED", message="Operator access is required.")
    if not hmac.compare_digest(hashlib.sha256(candidate.encode()).digest(), hashlib.sha256(expected.encode()).digest()):
        raise ApiAppException(status_code=403, code="OPERATOR_AUTH_REQUIRED", message="Operator access is required.")


def _database_ready(path) -> bool:
    from backend.app.db.postgres.runtime import PostgresTarget, probe_runtime
    if isinstance(path, PostgresTarget):
        return probe_runtime(path)
    deadline = time.monotonic() + DATABASE_CHECK_SECONDS
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.5)) as conn:
            conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            return conn.execute("PRAGMA quick_check").fetchall() == [("ok",)]
    except (OSError, sqlite3.Error):
        return False


async def _run_canary(settings) -> tuple[bool, str, int | None]:
    worker = get_worker_client(settings)
    repository = SQLiteRepository(settings.database_target)
    source_hash = hashlib.sha256(_CANARY_SOURCE.encode()).hexdigest()
    session_id = uuid4()
    revision = RevisionRef(session_id=session_id, exercise_id="ex2_binary_search",
        spec_version="v1_sorted_with_duplicates", code_version_id=1,
        code_hash=source_hash, turn_generation=0)
    request = ExecutionRequest(job_id=uuid4(), revision=revision, source_code=_CANARY_SOURCE,
        input_args=_CANARY_INPUT, case_hash=registry.case_key("ex2_binary_search", "v1_sorted_with_duplicates", _CANARY_INPUT),
        budget=ExecutionBudgetConfig(startup_deadline_ms=5000 if settings.execution_runtime=='vercel_sandbox' else 1000, invocation_wall_ms=1000,
            job_wall_ms=5000, replay_reserve_ms=1000, shrink_wall_ms=0))
    created = False
    try:
        await asyncio.to_thread(repository.create_session, session_id=str(session_id), token_hash=str(uuid4()),
            exercise_id='ex2_binary_search', spec_version='v1_sorted_with_duplicates',
            language_mode='en-IN', interaction_mode='TEXT', starter_code=_CANARY_SOURCE,
            starter_code_hash=source_hash, expires_at=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat())
        created = True
        await asyncio.to_thread(repository.register_execution_job, str(session_id), str(request.job_id), 'CANARY', revision, '')
        if settings.execution_runtime=='vercel_sandbox':
            from backend.app.models.domain import ExecutionObservation
            raw = await asyncio.wait_for(asyncio.to_thread(worker.submit_operator_canary, request), 20)
            observation = ExecutionObservation.model_validate(raw)
        else:
            handle = await asyncio.wait_for(asyncio.to_thread(worker.submit_execution, request), CANARY_TIMEOUT_SECONDS)
            observation = handle.observation
        passed = observation is not None and observation.kind == ExecutionObservationKind.RETURN and observation.return_value == 0
        await asyncio.to_thread(repository.finish_execution_job, str(session_id), str(request.job_id), 'COMPLETE' if passed else 'FAILED')
        return passed, "PASSED" if passed else "FAILED", observation.duration_ms if observation else None
    except Exception as exc:
        _LOGGER.warning("Readiness canary failed (%s)", type(exc).__name__)
        try:
            cancelled = await asyncio.wait_for(asyncio.to_thread(worker.cancel, request.job_id), 2.0)
            if not cancelled:
                _LOGGER.warning("Readiness canary cancellation remains unconfirmed")
        except Exception:
            _LOGGER.warning("Readiness canary cancellation remains unconfirmed")
        return False, "FAILED", None
    finally:
        if created:
            await asyncio.to_thread(repository.tombstone_session, str(session_id))


@router.get("/readiness", response_model=OperationsReadinessResponse)
async def operations_readiness(request: Request, authorization: str | None = Header(default=None),
                               run_canary: bool = True) -> OperationsReadinessResponse:
    _require_operator(request, authorization)
    settings = request.app.state.settings
    database = await asyncio.to_thread(_database_ready, settings.database_target)
    accepted = await probe_execution_readiness(settings)
    if settings.execution_runtime=='vercel_sandbox' and database and run_canary:
        try:
            preflight = await asyncio.to_thread(get_worker_client(settings).check_canary_preflight)
            accepted = 'READY' if preflight.ready and preflight.acceptance_verified else 'BLOCKED_EXTERNAL'
        except Exception:
            accepted = 'BLOCKED_EXTERNAL'
    execution, canary, duration = False, "NOT_RUN", None
    if database and accepted == "READY" and run_canary:
        execution, canary, duration = await _run_canary(settings)
    return OperationsReadinessResponse(status="READY" if database and execution else "BLOCKED_EXTERNAL",
        checked_at=datetime.now(timezone.utc), database_ready=database, execution_ready=execution,
        canary_status=canary, canary_duration_ms=duration,
        speech_status="CONFIGURED_UNVERIFIED" if settings.gnani_api_key else "UNAVAILABLE")
