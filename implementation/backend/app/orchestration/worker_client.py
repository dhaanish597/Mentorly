"""Coordinator-side HTTP client (`WorkerClient`) for the isolated execution broker."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import os
from typing import Any, Callable
from uuid import UUID

import httpx
from pydantic import ValidationError

HTTP_RESPONSE_GRACE_MS = 2000
CANCELLATION_TIMEOUT_SECONDS = 5.0

try:
    from backend.app.db.repository import (
        SessionDeletedError,
        SessionNotFoundError,
        SessionRepository,
    )
    from backend.app.models.domain import (
        ExecutionObservation,
        ExecutionRequest,
        JobHandle,
        RevisionRef,
        TraceExecutionReport,
        TraceRequest,
        VerificationReport,
        VerifyJobRequest,
    )
    from backend.app.models.enums import (
        ExecutionObservationKind,
        JobStatus,
        SessionState,
        TraceExecutionStatus,
        VerificationStatus,
    )
except ImportError:  # pragma: no cover
    from app.db.repository import (  # type: ignore[no-redef]
        SessionDeletedError,
        SessionNotFoundError,
        SessionRepository,
    )
    from app.models.domain import (  # type: ignore[no-redef]
        ExecutionObservation,
        ExecutionRequest,
        JobHandle,
        RevisionRef,
        TraceExecutionReport,
        TraceRequest,
        VerificationReport,
        VerifyJobRequest,
    )
    from app.models.enums import (  # type: ignore[no-redef]
        ExecutionObservationKind,
        JobStatus,
        SessionState,
        TraceExecutionStatus,
        VerificationStatus,
    )


class PublicCustomCodeDisabledError(PermissionError):
    """Raised when public custom-code execution is attempted while `VCC_ALLOW_PUBLIC_CUSTOM_CODE=false`."""


class StaleRevisionError(RuntimeError):
    """Raised when a job's `RevisionRef` no longer matches the session's active revision."""


class TombstonedSessionError(RuntimeError):
    """Raised when a job targets a tombstoned (`DELETED`) or missing session."""


class BrokerAuthenticationError(PermissionError):
    """Raised when the execution broker rejects `X-Internal-Worker-Secret`."""


class BrokerCommunicationError(RuntimeError):
    """Raised when the execution broker is unreachable or returns an unexpected status."""


class RevisionStateStatus(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    TOMBSTONED = "TOMBSTONED"


@dataclass(frozen=True)
class RevisionCheckResult:
    status: RevisionStateStatus
    reason: str = ""

    @property
    def is_fresh(self) -> bool:
        return self.status == RevisionStateStatus.FRESH


RevisionGuardFn = Callable[[RevisionRef], RevisionCheckResult | bool]


def _parse_bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


class WorkerClient:
    """Trusted coordinator client for submitting jobs to the isolated execution broker."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        internal_worker_secret: str | None = None,
        allow_public_custom_code: bool | None = None,
        session_repository: SessionRepository | None = None,
        revision_guard: RevisionGuardFn | None = None,
        http_client: httpx.Client | None = None,
        timeout_seconds: float = 30.0,
        raise_on_stale_or_tombstoned: bool = False,
    ) -> None:
        self._base_url = (
            base_url
            or os.environ.get("VCC_EXEC_WORKER_URL", "").strip()
            or "http://exec-worker:8001"
        ).rstrip("/")
        self._secret = (
            internal_worker_secret
            if internal_worker_secret is not None
            else os.environ.get("VCC_INTERNAL_WORKER_SECRET", "").strip()
        )
        self._allow_public_custom_code = (
            allow_public_custom_code
            if allow_public_custom_code is not None
            else _parse_bool_env("VCC_ALLOW_PUBLIC_CUSTOM_CODE", default=False)
        )
        self._session_repository = session_repository
        self._revision_guard = revision_guard
        self._http_client = http_client
        self._timeout_seconds = timeout_seconds
        self._raise_on_stale_or_tombstoned = raise_on_stale_or_tombstoned

    @property
    def allow_public_custom_code(self) -> bool:
        return self._allow_public_custom_code

    def _headers(self) -> dict[str, str]:
        if not self._secret:
            raise BrokerAuthenticationError(
                "VCC_INTERNAL_WORKER_SECRET is required for WorkerClient requests"
            )
        return {
            "X-Internal-Worker-Secret": self._secret,
            "Content-Type": "application/json",
        }

    def _enforce_public_gate(self, *, is_public_custom_code: bool) -> None:
        if is_public_custom_code and not self._allow_public_custom_code:
            raise PublicCustomCodeDisabledError(
                "Public custom-code execution is disabled (VCC_ALLOW_PUBLIC_CUSTOM_CODE=false)"
            )

    def check_revision_state(self, revision: RevisionRef) -> RevisionCheckResult:
        if self._revision_guard is not None:
            try:
                guard_res = self._revision_guard(revision)
            except SessionDeletedError as exc:
                return RevisionCheckResult(
                    status=RevisionStateStatus.TOMBSTONED, reason=str(exc)
                )
            except SessionNotFoundError as exc:
                return RevisionCheckResult(
                    status=RevisionStateStatus.TOMBSTONED, reason=str(exc)
                )
            if isinstance(guard_res, RevisionCheckResult):
                if not guard_res.is_fresh:
                    return guard_res
            elif not bool(guard_res):
                return RevisionCheckResult(
                    status=RevisionStateStatus.STALE,
                    reason="Custom revision_guard rejected revision",
                )

        if self._session_repository is None:
            return RevisionCheckResult(status=RevisionStateStatus.FRESH)

        session_id_str = str(revision.session_id)
        try:
            session = self._session_repository.get_session(
                session_id_str, include_deleted=True
            )
        except TypeError:
            session = self._session_repository.get_session(session_id_str)
        except (SessionDeletedError, SessionNotFoundError) as exc:
            return RevisionCheckResult(
                status=RevisionStateStatus.TOMBSTONED,
                reason=str(exc),
            )

        if session is None:
            return RevisionCheckResult(
                status=RevisionStateStatus.TOMBSTONED,
                reason=f"Session {session_id_str} not found",
            )

        if (
            getattr(session, "deleted_at", None) is not None
            or str(getattr(session, "state", "")) == str(SessionState.DELETED)
        ):
            return RevisionCheckResult(
                status=RevisionStateStatus.TOMBSTONED,
                reason=f"Session {session_id_str} is tombstoned",
            )

        if (
            str(session.exercise_id) != str(revision.exercise_id)
            or str(session.spec_version) != str(revision.spec_version)
        ):
            return RevisionCheckResult(
                status=RevisionStateStatus.STALE,
                reason="Session exercise_id or spec_version has changed",
            )

        if int(session.active_code_version_id) != int(revision.code_version_id):
            return RevisionCheckResult(
                status=RevisionStateStatus.STALE,
                reason=(
                    f"Stale code_version_id: revision has {revision.code_version_id}, "
                    f"active is {session.active_code_version_id}"
                ),
            )

        if int(session.active_turn_generation) != int(revision.turn_generation):
            return RevisionCheckResult(
                status=RevisionStateStatus.STALE,
                reason=(
                    f"Stale turn_generation: revision has {revision.turn_generation}, "
                    f"active is {session.active_turn_generation}"
                ),
            )

        get_cv = getattr(self._session_repository, "get_code_version", None)
        if callable(get_cv):
            cv_record = get_cv(session_id_str, int(revision.code_version_id))
            if cv_record is not None and str(cv_record.code_hash) != str(
                revision.code_hash
            ):
                return RevisionCheckResult(
                    status=RevisionStateStatus.STALE,
                    reason="Persisted code_hash does not match revision.code_hash",
                )

        return RevisionCheckResult(status=RevisionStateStatus.FRESH)

    def _rejected_handle(
        self,
        job_id: UUID,
        revision: RevisionRef,
        check: RevisionCheckResult,
    ) -> JobHandle:
        if self._raise_on_stale_or_tombstoned:
            if check.status == RevisionStateStatus.TOMBSTONED:
                raise TombstonedSessionError(check.reason or "Session is tombstoned")
            raise StaleRevisionError(check.reason or "Revision is stale")

        status_val = (
            JobStatus.CANCELLED
            if check.status == RevisionStateStatus.TOMBSTONED
            else JobStatus.SUPERSEDED
        )
        return JobHandle(
            job_id=job_id,
            revision=revision,
            status=status_val,
            observation=None,
            verification_report=None,
            trace_report=None,
        )

    def _post_json(self, path: str, payload: dict[str, Any] | None = None, *,
                   timeout_seconds: float | None = None, cancel_job_id: UUID | None = None) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        headers = self._headers()
        timeout = self._timeout_seconds if timeout_seconds is None else timeout_seconds
        try:
            if self._http_client is not None:
                resp = self._http_client.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                )
            else:
                with httpx.Client(timeout=timeout) as client:
                    resp = client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            cancelled = False
            if cancel_job_id is not None:
                try:
                    cancelled = self.cancel(cancel_job_id)
                except (BrokerCommunicationError,BrokerAuthenticationError):
                    cancelled = False
            raise BrokerCommunicationError(f'Broker job timed out; cancellation {"confirmed" if cancelled else "unconfirmed"}.') from exc
        except httpx.HTTPError as exc:
            raise BrokerCommunicationError(
                f"Broker request to {path} failed: {type(exc).__name__}"
            ) from exc

        if resp.status_code in (401, 403):
            raise BrokerAuthenticationError(
                f"Broker rejected authentication on {path} (HTTP {resp.status_code})"
            )
        if resp.status_code >= 400:
            raise BrokerCommunicationError(
                f"Broker returned HTTP {resp.status_code} on {path}"
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise BrokerCommunicationError('Broker returned malformed JSON') from exc
        if not isinstance(data, dict):
            raise BrokerCommunicationError(f"Broker response on {path} was not a JSON object")
        return data

    def submit_execution(
        self,
        req: ExecutionRequest,
        *,
        is_public_custom_code: bool = False,
    ) -> JobHandle:
        self._enforce_public_gate(is_public_custom_code=is_public_custom_code)

        pre_check = self.check_revision_state(req.revision)
        if not pre_check.is_fresh:
            return self._rejected_handle(req.job_id, req.revision, pre_check)

        raw = self._post_json('/internal/execute', req.model_dump(mode='json'),
            timeout_seconds=(req.budget.startup_deadline_ms + req.budget.invocation_wall_ms + HTTP_RESPONSE_GRACE_MS) / 1000,
            cancel_job_id=req.job_id)
        try:
            obs = ExecutionObservation.model_validate(raw)
        except ValidationError:
            raise BrokerCommunicationError('Worker returned an invalid execution observation') from None

        post_check = self.check_revision_state(req.revision)
        if not post_check.is_fresh:
            try:
                self.cancel(req.job_id)
            except Exception:
                pass
            return self._rejected_handle(req.job_id, req.revision, post_check)

        if obs.error_type == "JobSupersededOrCancelled":
            return JobHandle(
                job_id=req.job_id,
                revision=req.revision,
                status=JobStatus.SUPERSEDED,
                observation=None,
                verification_report=None,
                trace_report=None,
            )

        job_status = (
            JobStatus.FAILED
            if obs.kind == ExecutionObservationKind.UNAVAILABLE
            else JobStatus.COMPLETE
        )
        return JobHandle(
            job_id=req.job_id,
            revision=req.revision,
            status=job_status,
            observation=obs,
            verification_report=None,
            trace_report=None,
        )

    def submit_verify(
        self,
        req: VerifyJobRequest,
        *,
        is_public_custom_code: bool = False,
    ) -> JobHandle:
        self._enforce_public_gate(is_public_custom_code=is_public_custom_code)

        pre_check = self.check_revision_state(req.revision)
        if not pre_check.is_fresh:
            return self._rejected_handle(req.job_id, req.revision, pre_check)

        raw = self._post_json('/internal/verify', req.model_dump(mode='json'),
            timeout_seconds=(req.budget.job_wall_ms + req.budget.startup_deadline_ms) / 1000,
            cancel_job_id=req.job_id)
        try:
            report = VerificationReport.model_validate(raw)
        except ValidationError:
            raise BrokerCommunicationError('Worker returned an invalid verification report') from None

        post_check = self.check_revision_state(req.revision)
        if not post_check.is_fresh:
            try:
                self.cancel(req.job_id)
            except Exception:
                pass
            return self._rejected_handle(req.job_id, req.revision, post_check)

        if report.status == VerificationStatus.SUPERSEDED:
            return JobHandle(
                job_id=req.job_id,
                revision=req.revision,
                status=JobStatus.SUPERSEDED,
                observation=None,
                verification_report=report,
                trace_report=None,
            )

        job_status = (
            JobStatus.FAILED
            if report.status == VerificationStatus.EXECUTION_UNAVAILABLE
            else JobStatus.COMPLETE
        )
        return JobHandle(
            job_id=req.job_id,
            revision=req.revision,
            status=job_status,
            observation=report.student_observation,
            verification_report=report,
            trace_report=None,
        )

    def submit_trace(
        self,
        req: TraceRequest,
        *,
        is_public_custom_code: bool = False,
    ) -> JobHandle:
        self._enforce_public_gate(is_public_custom_code=is_public_custom_code)

        pre_check = self.check_revision_state(req.revision)
        if not pre_check.is_fresh:
            return self._rejected_handle(req.job_id, req.revision, pre_check)

        raw = self._post_json('/internal/trace', req.model_dump(mode='json'),
            timeout_seconds=(req.budget.startup_deadline_ms + req.budget.invocation_wall_ms + HTTP_RESPONSE_GRACE_MS) / 1000,
            cancel_job_id=req.job_id)
        try:
            report = TraceExecutionReport.model_validate(raw)
        except ValidationError:
            raise BrokerCommunicationError('Worker returned an invalid trace report') from None

        post_check = self.check_revision_state(req.revision)
        if not post_check.is_fresh:
            try:
                self.cancel(req.job_id)
            except Exception:
                pass
            return self._rejected_handle(req.job_id, req.revision, post_check)

        job_status = (
            JobStatus.FAILED
            if report.status == TraceExecutionStatus.TRACE_UNAVAILABLE
            else JobStatus.COMPLETE
        )
        return JobHandle(
            job_id=req.job_id,
            revision=req.revision,
            status=job_status,
            observation=report.observation,
            verification_report=None,
            trace_report=report,
        )

    def cancel(self, job_id: UUID) -> bool:
        data = self._post_json(f'/internal/cancel/{job_id}', payload=None, timeout_seconds=min(self._timeout_seconds,CANCELLATION_TIMEOUT_SECONDS))
        return data.get("cancelled") is True
