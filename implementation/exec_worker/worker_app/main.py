"""FastAPI execution broker service (`create_broker_app`) for Phase 1 (T-02)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
import secrets
import threading
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

try:
    from backend.app.models.domain import (
        ExecutionObservation,
        ExecutionRequest,
        RevisionRef,
        TraceExecutionReport,
        TraceRequest,
        VerificationReport,
        VerifyJobRequest,
    )
    from backend.app.models.enums import (
        ExecutionObservationKind,
        JobStatus,
        TraceExecutionStatus,
        VerificationStatus,
    )
except ImportError:  # pragma: no cover
    from app.models.domain import (  # type: ignore[no-redef]
        ExecutionObservation,
        ExecutionRequest,
        RevisionRef,
        TraceExecutionReport,
        TraceRequest,
        VerificationReport,
        VerifyJobRequest,
    )
    from app.models.enums import (  # type: ignore[no-redef]
        ExecutionObservationKind,
        JobStatus,
        TraceExecutionStatus,
        VerificationStatus,
    )

from .sandbox_runner import (
    DEFAULT_RUNNER_IMAGE,
    GVisorSandboxRunner,
    SandboxRunnerProtocol,
)
from .verifier_harness import run_verification_job


@dataclass(frozen=True)
class BrokerConfig:
    """Configuration for the internal execution broker service."""

    internal_worker_secret: str
    runner_image: str = DEFAULT_RUNNER_IMAGE
    max_concurrency: int = 4
    service_version: str = "0.2.0-phase1"
    ipc_parent_dir: str | None = None

    @classmethod
    def from_env(cls) -> "BrokerConfig":
        secret = os.environ.get("VCC_INTERNAL_WORKER_SECRET", "").strip()
        runner_image = (
            os.environ.get("VCC_RUNNER_IMAGE", "").strip() or DEFAULT_RUNNER_IMAGE
        )
        raw_conc = os.environ.get("VCC_WORKER_MAX_CONCURRENCY", "4").strip()
        try:
            max_conc = max(1, int(raw_conc))
        except ValueError:
            max_conc = 4
        return cls(
            internal_worker_secret=secret,
            runner_image=runner_image,
            max_concurrency=max_conc,
            ipc_parent_dir=os.environ.get("VCC_IPC_PARENT_DIR", "").strip() or None,
        )


class BrokerHealthResponse(BaseModel):
    """Secret-free health and runtime preflight response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    service: str = "vcc-exec-worker"
    version: str
    sandbox_ready: bool
    runtime_version: str
    runner_image: str
    platform_system: str
    docker_available: bool
    runsc_registered: bool
    runsc_binary_available: bool
    runner_image_present: bool
    acceptance_verified: bool = False
    failure_reasons: list[str] = Field(default_factory=list)
    active_jobs: int = Field(ge=0)
    max_concurrency: int = Field(ge=1)


class BrokerCancelResponse(BaseModel):
    """Response returned by `POST /internal/cancel/{job_id}`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: UUID
    cancelled: bool
    status: JobStatus


@dataclass
class _TrackedJobEntry:
    job_id: UUID
    revision: RevisionRef
    status: JobStatus = JobStatus.RUNNING
    superseded: bool = False
    cancelled: bool = False


class ActiveJobRegistry:
    """Thread-safe registry tracking active jobs, cancellations, and session revisions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[UUID, _TrackedJobEntry] = {}
        self._cancelled_ids: set[UUID] = set()
        self._superseded_ids: set[UUID] = set()
        self._latest_session_rev: dict[UUID, tuple[int, int]] = {}

    def register_job(self, job_id: UUID, revision: RevisionRef) -> tuple[bool, list[UUID]]:
        with self._lock:
            incoming_pair = (revision.code_version_id, revision.turn_generation)
            current_latest = self._latest_session_rev.get(revision.session_id)
            superseded_to_cancel: list[UUID] = []

            if job_id in self._cancelled_ids:
                entry = _TrackedJobEntry(
                    job_id=job_id,
                    revision=revision,
                    status=JobStatus.CANCELLED,
                    cancelled=True,
                )
                self._jobs[job_id] = entry
                return True, []

            if current_latest is not None and incoming_pair < current_latest:
                self._superseded_ids.add(job_id)
                entry = _TrackedJobEntry(
                    job_id=job_id,
                    revision=revision,
                    status=JobStatus.SUPERSEDED,
                    superseded=True,
                )
                self._jobs[job_id] = entry
                return True, []

            if current_latest is None or incoming_pair > current_latest:
                self._latest_session_rev[revision.session_id] = incoming_pair
                for other_id, other_entry in self._jobs.items():
                    if (
                        other_entry.revision.session_id == revision.session_id
                        and (
                            other_entry.revision.code_version_id,
                            other_entry.revision.turn_generation,
                        )
                        < incoming_pair
                        and other_entry.status in (JobStatus.QUEUED, JobStatus.RUNNING)
                    ):
                        other_entry.superseded = True
                        other_entry.status = JobStatus.SUPERSEDED
                        self._superseded_ids.add(other_id)
                        superseded_to_cancel.append(other_id)

            self._jobs[job_id] = _TrackedJobEntry(
                job_id=job_id,
                revision=revision,
                status=JobStatus.RUNNING,
            )
            return False, superseded_to_cancel

    def is_cancelled_or_superseded(self, job_id: UUID, revision: RevisionRef | None = None) -> bool:
        with self._lock:
            if job_id in self._cancelled_ids or job_id in self._superseded_ids:
                return True
            entry = self._jobs.get(job_id)
            if entry is not None and (entry.cancelled or entry.superseded):
                return True
            if revision is not None:
                latest = self._latest_session_rev.get(revision.session_id)
                if latest is not None and (
                    revision.code_version_id,
                    revision.turn_generation,
                ) < latest:
                    return True
            return False

    def mark_cancelled(self, job_id: UUID) -> JobStatus:
        with self._lock:
            self._cancelled_ids.add(job_id)
            entry = self._jobs.get(job_id)
            if entry is not None:
                entry.cancelled = True
                entry.status = JobStatus.CANCELLED
            return JobStatus.CANCELLED

    def complete_job(self, job_id: UUID) -> None:
        with self._lock:
            entry = self._jobs.get(job_id)
            if entry is not None and not (entry.cancelled or entry.superseded):
                entry.status = JobStatus.COMPLETE

    def active_count(self) -> int:
        with self._lock:
            return sum(
                1
                for e in self._jobs.values()
                if e.status in (JobStatus.QUEUED, JobStatus.RUNNING)
            )


def create_broker_app(
    *,
    config: BrokerConfig | None = None,
    runner: SandboxRunnerProtocol | None = None,
    job_registry: ActiveJobRegistry | None = None,
) -> FastAPI:
    """Create the authenticated FastAPI execution broker application."""
    active_config = config or BrokerConfig.from_env()
    active_runner: SandboxRunnerProtocol = runner or GVisorSandboxRunner(
        runner_image=active_config.runner_image,
        ipc_parent_dir=active_config.ipc_parent_dir,
    )
    registry = job_registry or ActiveJobRegistry()
    semaphore = asyncio.Semaphore(max(1, active_config.max_concurrency))

    app = FastAPI(
        title="VCC Isolated Execution Broker",
        version=active_config.service_version,
        docs_url=None,
        redoc_url=None,
    )
    app.state.config = active_config
    app.state.runner = active_runner
    app.state.job_registry = registry
    app.state.semaphore = semaphore

    def verify_internal_secret(
        x_internal_worker_secret: str | None = Header(
            default=None, alias="X-Internal-Worker-Secret"
        ),
    ) -> None:
        expected = active_config.internal_worker_secret
        if not expected or x_internal_worker_secret is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or unconfigured internal worker secret",
            )
        if not secrets.compare_digest(
            x_internal_worker_secret.encode("utf-8"),
            expected.encode("utf-8"),
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid internal worker secret",
            )

    @app.get(
        "/internal/health",
        response_model=BrokerHealthResponse,
        dependencies=[Depends(verify_internal_secret)],
    )
    async def internal_health() -> BrokerHealthResponse:
        preflight = await run_in_threadpool(active_runner.check_preflight)
        return BrokerHealthResponse(
            status="ok" if preflight.ready else "degraded",
            version=active_config.service_version,
            sandbox_ready=preflight.ready,
            runtime_version=preflight.runtime_version,
            runner_image=preflight.runner_image,
            platform_system=preflight.platform_system,
            docker_available=preflight.docker_available,
            runsc_registered=preflight.runsc_registered,
            runsc_binary_available=preflight.runsc_binary_available,
            runner_image_present=preflight.runner_image_present,
            acceptance_verified=preflight.acceptance_verified,
            failure_reasons=list(preflight.failure_reasons),
            active_jobs=registry.active_count(),
            max_concurrency=active_config.max_concurrency,
        )

    @app.post(
        "/internal/execute",
        response_model=ExecutionObservation,
        dependencies=[Depends(verify_internal_secret)],
    )
    async def internal_execute(req: ExecutionRequest) -> ExecutionObservation:
        already_stale, to_cancel = registry.register_job(req.job_id, req.revision)
        for old_id in to_cancel:
            await run_in_threadpool(active_runner.cancel_invocation, old_id)

        if already_stale:
            return ExecutionObservation(
                kind=ExecutionObservationKind.INVALID_RESULT,
                return_value=None,
                error_type="JobSupersededOrCancelled",
                error_message="Job was cancelled or superseded before execution",
                stdout_excerpt="",
                stderr_excerpt="",
                duration_ms=0,
            )

        async with semaphore:
            if registry.is_cancelled_or_superseded(req.job_id, req.revision):
                return ExecutionObservation(
                    kind=ExecutionObservationKind.INVALID_RESULT,
                    return_value=None,
                    error_type="JobSupersededOrCancelled",
                    error_message="Job was cancelled or superseded while queued",
                    stdout_excerpt="",
                    stderr_excerpt="",
                    duration_ms=0,
                )
            try:
                obs = await run_in_threadpool(active_runner.execute, req)
                if registry.is_cancelled_or_superseded(req.job_id, req.revision):
                    return ExecutionObservation(
                        kind=ExecutionObservationKind.INVALID_RESULT,
                        return_value=None,
                        error_type="JobSupersededOrCancelled",
                        error_message="Late execution result discarded for superseded/cancelled job",
                        stdout_excerpt="",
                        stderr_excerpt="",
                        duration_ms=obs.duration_ms,
                    )
                registry.complete_job(req.job_id)
                return obs
            finally:
                if registry.is_cancelled_or_superseded(req.job_id, req.revision):
                    await run_in_threadpool(active_runner.cancel_invocation, req.job_id)

    @app.post(
        "/internal/verify",
        response_model=VerificationReport,
        dependencies=[Depends(verify_internal_secret)],
    )
    async def internal_verify(req: VerifyJobRequest) -> VerificationReport:
        already_stale, to_cancel = registry.register_job(req.job_id, req.revision)
        for old_id in to_cancel:
            await run_in_threadpool(active_runner.cancel_invocation, old_id)

        runtime_ver = getattr(active_runner, "runtime_version", None) or "runsc-phase1"
        if already_stale:
            return VerificationReport(
                status=VerificationStatus.SUPERSEDED,
                curated_cases_run=0,
                curated_cases_total=0,
                generated_cases_run=0,
                generated_cases_target=req.generated_cases_target,
                completed_stages=[],
                terminal_reason="Verification job was cancelled or superseded before execution",
                seed=req.seed,
                runtime_version=runtime_ver[:64],
            )

        async with semaphore:
            if registry.is_cancelled_or_superseded(req.job_id, req.revision):
                return VerificationReport(
                    status=VerificationStatus.SUPERSEDED,
                    curated_cases_run=0,
                    curated_cases_total=0,
                    generated_cases_run=0,
                    generated_cases_target=req.generated_cases_target,
                    completed_stages=[],
                    terminal_reason="Verification job was cancelled or superseded while queued",
                    seed=req.seed,
                    runtime_version=runtime_ver[:64],
                )
            try:
                report = await run_in_threadpool(
                    run_verification_job,
                    req,
                    active_runner,
                    cancel_check_fn=lambda: registry.is_cancelled_or_superseded(
                        req.job_id, req.revision
                    ),
                )
                if registry.is_cancelled_or_superseded(req.job_id, req.revision):
                    return VerificationReport(
                        status=VerificationStatus.SUPERSEDED,
                        curated_cases_run=report.curated_cases_run,
                        curated_cases_total=report.curated_cases_total,
                        generated_cases_run=report.generated_cases_run,
                        generated_cases_target=report.generated_cases_target,
                        completed_stages=list(report.completed_stages),
                        terminal_reason="Late verification result superseded or cancelled",
                        seed=req.seed,
                        runtime_version=report.runtime_version,
                    )
                registry.complete_job(req.job_id)
                return report
            finally:
                if registry.is_cancelled_or_superseded(req.job_id, req.revision):
                    await run_in_threadpool(active_runner.cancel_invocation, req.job_id)

    @app.post(
        "/internal/trace",
        response_model=TraceExecutionReport,
        dependencies=[Depends(verify_internal_secret)],
    )
    async def internal_trace(req: TraceRequest) -> TraceExecutionReport:
        already_stale, to_cancel = registry.register_job(req.job_id, req.revision)
        for old_id in to_cancel:
            await run_in_threadpool(active_runner.cancel_invocation, old_id)

        runtime_ver = getattr(active_runner, "runtime_version", None) or "runsc-phase1"
        if already_stale:
            return TraceExecutionReport(
                trace_id=req.trace_id,
                revision=req.revision,
                case_hash=req.case_hash,
                status=TraceExecutionStatus.TRACE_UNAVAILABLE,
                steps=[],
                total_observed=0,
                trace_truncated=False,
                termination_reason="Trace job was cancelled or superseded before launch",
                observation=None,
                runtime_version=runtime_ver[:64],
            )

        async with semaphore:
            if registry.is_cancelled_or_superseded(req.job_id, req.revision):
                return TraceExecutionReport(
                    trace_id=req.trace_id,
                    revision=req.revision,
                    case_hash=req.case_hash,
                    status=TraceExecutionStatus.TRACE_UNAVAILABLE,
                    steps=[],
                    total_observed=0,
                    trace_truncated=False,
                    termination_reason="Trace job was cancelled or superseded while queued",
                    observation=None,
                    runtime_version=runtime_ver[:64],
                )
            try:
                report = await run_in_threadpool(active_runner.trace, req)
                if registry.is_cancelled_or_superseded(req.job_id, req.revision):
                    return TraceExecutionReport(
                        trace_id=req.trace_id,
                        revision=req.revision,
                        case_hash=req.case_hash,
                        status=TraceExecutionStatus.TRACE_UNAVAILABLE,
                        steps=[],
                        total_observed=0,
                        trace_truncated=False,
                        termination_reason="Late trace result discarded for superseded/cancelled job",
                        observation=None,
                        runtime_version=report.runtime_version,
                    )
                registry.complete_job(req.job_id)
                return report
            finally:
                if registry.is_cancelled_or_superseded(req.job_id, req.revision):
                    await run_in_threadpool(active_runner.cancel_invocation, req.job_id)

    @app.post(
        "/internal/cancel/{job_id}",
        response_model=BrokerCancelResponse,
        dependencies=[Depends(verify_internal_secret)],
    )
    async def internal_cancel(job_id: UUID) -> BrokerCancelResponse:
        job_status = registry.mark_cancelled(job_id)
        killed = await run_in_threadpool(active_runner.cancel_invocation, job_id)
        return BrokerCancelResponse(
            job_id=job_id,
            cancelled=True or killed,
            status=job_status,
        )

    return app


app = create_broker_app()
