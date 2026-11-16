"""Operator-only diagnostics and a fixed, genuinely isolated execution canary."""
from __future__ import annotations
from backend.app.db.migrations import database_target

import asyncio
from contextlib import closing
from datetime import datetime, timezone
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

router = APIRouter(prefix="/ops", tags=["operations"])
_CANARY_SOURCE = "def first_at_least(nums, target):\n    return 0\n"
_CANARY_INPUT = {"nums": [0], "target": 0}
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
    from backend.app.db.postgres.runtime import PostgresTarget
    if isinstance(path, PostgresTarget):
        try:
            with path.connect() as conn:
                conn.execute("SET statement_timeout TO '500ms'")
                return conn.execute("SELECT to_regclass('sessions') IS NOT NULL").fetchone()==(True,)
        except (ValueError,sqlite3.Error):
            return False
    deadline = time.monotonic() + DATABASE_CHECK_SECONDS
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.5)) as conn:
            conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            return conn.execute("PRAGMA quick_check").fetchall() == [("ok",)]
    except (OSError, sqlite3.Error):
        return False


async def _run_canary(settings) -> tuple[bool, str, int | None]:
    worker = WorkerClient(base_url=settings.exec_worker_url,
        internal_worker_secret=settings.internal_worker_secret.get_secret_value(),
        allow_public_custom_code=True)
    revision = RevisionRef(session_id=uuid4(), exercise_id="ex2_binary_search",
        spec_version="v1_sorted_with_duplicates", code_version_id=1,
        code_hash=hashlib.sha256(_CANARY_SOURCE.encode()).hexdigest(), turn_generation=1)
    request = ExecutionRequest(job_id=uuid4(), revision=revision, source_code=_CANARY_SOURCE,
        input_args=_CANARY_INPUT, case_hash=registry.case_key("ex2_binary_search", "v1_sorted_with_duplicates", _CANARY_INPUT),
        budget=ExecutionBudgetConfig(startup_deadline_ms=1000, invocation_wall_ms=1000,
            job_wall_ms=5000, replay_reserve_ms=1000, shrink_wall_ms=0))
    try:
        handle = await asyncio.wait_for(asyncio.to_thread(worker.submit_execution, request), CANARY_TIMEOUT_SECONDS)
        observation = handle.observation
        passed = observation is not None and observation.kind == ExecutionObservationKind.RETURN and observation.return_value == 0
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


@router.get("/readiness", response_model=OperationsReadinessResponse)
async def operations_readiness(request: Request, authorization: str | None = Header(default=None),
                               run_canary: bool = True) -> OperationsReadinessResponse:
    _require_operator(request, authorization)
    settings = request.app.state.settings
    database = await asyncio.to_thread(_database_ready, database_target(settings))
    accepted = await probe_execution_readiness(settings)
    execution, canary, duration = False, "NOT_RUN", None
    if database and accepted == "READY" and run_canary:
        execution, canary, duration = await _run_canary(settings)
    return OperationsReadinessResponse(status="READY" if database and execution else "BLOCKED_EXTERNAL",
        checked_at=datetime.now(timezone.utc), database_ready=database, execution_ready=execution,
        canary_status=canary, canary_duration_ms=duration,
        speech_status="CONFIGURED_UNVERIFIED" if settings.gnani_api_key else "UNAVAILABLE")
