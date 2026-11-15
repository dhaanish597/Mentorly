"""Trusted synchronous coordinator client; learner execution stays in microVMs.

This removes the extra HTTP broker hop while retaining WorkerClient's public
gate, request/response models and pre/post revision guards. It creates no HTTP
endpoint and never evaluates learner source in the backend interpreter.
"""
from __future__ import annotations

import threading
import math
import time
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from typing import Callable
from uuid import UUID

try:
    from backend.app.models.domain import (
        ExecutionObservation, ExecutionRequest, TraceExecutionReport, TraceRequest,
        VerificationReport, VerifyJobRequest,
    )
    from backend.app.models.enums import ExecutionObservationKind, TraceExecutionStatus, VerificationStatus
    from backend.app.orchestration.worker_client import BrokerCommunicationError, WorkerClient
except ImportError:  # pragma: no cover
    from app.models.domain import (
        ExecutionObservation, ExecutionRequest, TraceExecutionReport, TraceRequest,
        VerificationReport, VerifyJobRequest,
    )
    from app.models.enums import ExecutionObservationKind, TraceExecutionStatus, VerificationStatus
    from app.orchestration.worker_client import BrokerCommunicationError, WorkerClient

from exec_worker.worker_app.main import ActiveJobRegistry
from exec_worker.worker_app.sandbox_runner import SandboxRunnerProtocol
from exec_worker.worker_app.verifier_harness import run_verification_job


class InProcessWorkerClient(WorkerClient):
    """Use from the coordinator's thread pool, with its durable admission guard.

    The semaphore bounds this instance. The caller must continue enforcing its
    database-backed global admission/usage limits and session ownership checks.
    Cancellation checks can also read the caller's durable job state.
    """
    def __init__(self, *, runner: SandboxRunnerProtocol, session_repository,
                 allow_public_custom_code: bool = False, max_concurrency: int = 1,
                 revision_guard=None, external_cancel_check: Callable[[UUID], bool] | None = None,
                 execution_store=None, cloud_runtime: bool = False):
        if session_repository is None:
            raise ValueError("Trusted execution requires the session repository")
        if type(max_concurrency) is not int or not 1 <= max_concurrency <= 4:
            raise ValueError("Execution concurrency must be between one and four")
        super().__init__(session_repository=session_repository,
                         revision_guard=revision_guard,
                         allow_public_custom_code=allow_public_custom_code)
        self.runner = runner
        self.registry = ActiveJobRegistry()
        self._capacity = threading.BoundedSemaphore(max_concurrency)
        self._external_cancel_check = external_cancel_check
        self._cancellation_lock = threading.Lock()
        self._cancellations = {}
        self._execution_store = execution_store
        self._cloud_runtime = cloud_runtime

    def _cancel_runner(self, job_id):
        self.registry.mark_cancelled(job_id)
        persistence_error = None
        if self._execution_store is not None:
            try:
                self._execution_store.request_cancel(job_id)
            except Exception:
                persistence_error = BrokerCommunicationError('Durable cancellation request unavailable')
        with self._cancellation_lock:
            existing = self._cancellations.get(job_id)
            if existing is not None:
                return existing
            future = Future()
            future.set_running_or_notify_cancel()
            self._cancellations[job_id] = future
        def cancel():
            try:
                result = self.runner.cancel_invocation(job_id)
                if self._execution_store is not None and self._execution_store.recovery_due(job_id):
                    self.runner.recover_cleanup(job_id)
            except BaseException as exc:
                future.set_exception(exc)
            else:
                if persistence_error is None:
                    future.set_result(result)
                else:
                    future.set_exception(persistence_error)
            finally:
                with self._cancellation_lock:
                    self._cancellations.pop(job_id, None)
        try:
            threading.Thread(target=cancel, daemon=True).start()
        except BaseException as exc:
            with self._cancellation_lock:
                self._cancellations.pop(job_id, None)
            future.set_exception(exc)
        return future

    def check_preflight(self):
        return self.runner.check_preflight()

    def check_canary_preflight(self):
        return self.runner.check_canary_preflight()

    def submit_operator_canary(self, req):
        return self._post_json('/internal/operator-canary', req.model_dump(mode='json'),
            timeout_seconds=10, cancel_job_id=req.job_id)

    @property
    def runtime_version(self):
        return self.runner.runtime_version

    def _superseded(self, req):
        if self.registry.is_cancelled_or_superseded(req.job_id, req.revision):
            return True
        try:
            if not self.check_revision_state(req.revision).is_fresh:
                return True
            return self._external_cancel_check is not None and self._external_cancel_check(req.job_id)
        except Exception:
            raise BrokerCommunicationError("Execution revision or cancellation state unavailable") from None

    def _discarded(self, req, previous=None):
        if isinstance(req, ExecutionRequest):
            return ExecutionObservation(kind=ExecutionObservationKind.INVALID_RESULT,
                return_value=None, error_type="JobSupersededOrCancelled",
                error_message="Execution was cancelled or superseded", stdout_excerpt="", stderr_excerpt="",
                duration_ms=previous.duration_ms if previous is not None else 0)
        runtime = str(self.runner.runtime_version)[:64]
        if isinstance(req, VerifyJobRequest):
            return VerificationReport(status=VerificationStatus.SUPERSEDED,
                curated_cases_run=previous.curated_cases_run if previous is not None else 0,
                curated_cases_total=previous.curated_cases_total if previous is not None else 0,
                generated_cases_run=previous.generated_cases_run if previous is not None else 0,
                generated_cases_target=req.generated_cases_target,
                completed_stages=previous.completed_stages if previous is not None else [],
                terminal_reason="Verification was cancelled or superseded", seed=req.seed, runtime_version=runtime)
        return TraceExecutionReport(trace_id=req.trace_id, revision=req.revision, case_hash=req.case_hash,
            status=TraceExecutionStatus.TRACE_UNAVAILABLE, steps=[], total_observed=0,
            trace_truncated=False, termination_reason="Trace was cancelled or superseded",
            observation=None, runtime_version=runtime)

    def _post_json(self, path, payload=None, *, timeout_seconds=None, cancel_job_id=None):
        if path.startswith("/internal/cancel/"):
            try:
                job_id = UUID(path[len("/internal/cancel/"):])
            except ValueError:
                raise BrokerCommunicationError("Invalid cancellation job identifier") from None
            timeout = float(self._timeout_seconds if timeout_seconds is None else timeout_seconds)
            if not math.isfinite(timeout):
                raise BrokerCommunicationError("Invalid cancellation response deadline")
            try:
                self._cancel_runner(job_id).result(timeout=max(0, timeout))
            except FutureTimeoutError:
                raise BrokerCommunicationError("Cancellation response deadline exceeded; termination unconfirmed") from None
            confirmed = self._execution_store is None or self._execution_store.cancellation_confirmed(job_id)
            return {"job_id": str(job_id), "cancelled": confirmed, "status": "CANCELLED" if confirmed else 'CANCEL_REQUESTED'}
        models = {"/internal/execute": ExecutionRequest, "/internal/verify": VerifyJobRequest,
                  "/internal/trace": TraceRequest, '/internal/operator-canary': ExecutionRequest}
        model = models.get(path)
        if model is None:
            raise BrokerCommunicationError("Unsupported trusted execution operation")
        req = model.model_validate(payload)
        if cancel_job_id is not None and cancel_job_id != req.job_id:
            raise BrokerCommunicationError("Execution job identifier mismatch")
        response_timeout = float(self._timeout_seconds if timeout_seconds is None else timeout_seconds)
        if not math.isfinite(response_timeout):
            raise BrokerCommunicationError("Invalid execution response deadline")
        if self._cloud_runtime:
            response_timeout = min(240.0, response_timeout + max(0, 5000 - req.budget.startup_deadline_ms) / 1000)
            req = req.model_copy(update={'budget': req.budget.model_copy(update={
                'startup_deadline_ms': 5000, 'job_wall_ms': min(req.budget.job_wall_ms, 235000)})})
        deadline = time.monotonic() + max(0, response_timeout)
        queue_wait = min(5.0, max(0, response_timeout))
        if not self._capacity.acquire(timeout=max(0, queue_wait)):
            raise BrokerCommunicationError("Execution capacity is busy")
        if time.monotonic() >= deadline:
            self._capacity.release()
            raise BrokerCommunicationError("Execution response deadline exceeded before dispatch")
        if self._execution_store is not None:
            try:
                acquired = self._execution_store.acquire_job(req.job_id)
            except Exception:
                self._capacity.release()
                raise BrokerCommunicationError('Shared execution admission unavailable') from None
            if not acquired:
                self._capacity.release()
                raise BrokerCommunicationError('Shared execution capacity is occupied or cancelled')

        future = Future()
        future.set_running_or_notify_cancel()
        monitor_stop = threading.Event()

        def monitor():
            while not monitor_stop.wait(0.1):
                try:
                    cancelled = time.monotonic() >= deadline or self._superseded(req)
                except Exception:
                    cancelled = True
                if cancelled:
                    try:
                        self._cancel_runner(req.job_id)
                    except Exception:
                        # VM lifetime and durable registration retain the slot if
                        # cancellation storage/transport is temporarily unavailable.
                        self.registry.mark_cancelled(req.job_id)
                    return

        def dispatch():
            try:
                if self._cloud_runtime:
                    self.runner.set_dispatch_deadline(deadline)
                already_stale, cancel_ids = self.registry.register_job(req.job_id, req.revision)
                for job_id in cancel_ids:
                    self._cancel_runner(job_id).result(timeout=max(0,min(5,deadline-time.monotonic())))
                if already_stale or self._superseded(req):
                    raw = self._discarded(req).model_dump(mode="json")
                else:
                    if time.monotonic() >= deadline:
                        raise BrokerCommunicationError("Execution response deadline exceeded before dispatch")
                    if path == "/internal/execute":
                        result = self.runner.execute(req)
                    elif path == '/internal/operator-canary':
                        result = self.runner.execute_operator_canary(req)
                    elif path == "/internal/trace":
                        result = self.runner.trace(req)
                    else:
                        result = run_verification_job(req, self.runner,
                            cancel_check_fn=lambda: time.monotonic() >= deadline or self._superseded(req))
                    if time.monotonic() >= deadline:
                        raise BrokerCommunicationError("Execution response deadline exceeded")
                    if self._superseded(req):
                        self.runner.cancel_invocation(req.job_id)
                        result = self._discarded(req, result)
                    raw = result.model_dump(mode="json")
            except BaseException as exc:
                error = exc
            else:
                error = None
            finally:
                # The worker owns this slot until its synchronous transport has
                # finished cleanup, even after the caller's response timeout.
                self.registry.complete_job(req.job_id)
                monitor_stop.set()
                if self._cloud_runtime:
                    self.runner.set_dispatch_deadline(None)
                if self._execution_store is not None:
                    try:
                        settled = self._execution_store.finish_job(req.job_id)
                    except Exception:
                        error = BrokerCommunicationError('Shared execution settlement unavailable')
                    else:
                        if not settled:
                            error = BrokerCommunicationError('Sandbox cleanup remains unconfirmed')
                self._capacity.release()
            if error is None:
                future.set_result(raw)
            else:
                future.set_exception(error)

        thread = threading.Thread(target=dispatch, daemon=True)
        try:
            if self._execution_store is not None:
                threading.Thread(target=monitor, daemon=True).start()
            thread.start()
        except BaseException:
            monitor_stop.set()
            try:
                if self._execution_store is not None:
                    self._execution_store.finish_job(req.job_id)
            finally:
                self._capacity.release()
            raise
        def request_cancellation():
            # Its independent future permits cancellation while the execution
            # slot remains held; transport cleanup remains owned by dispatch.
            self._cancel_runner(req.job_id)
        try:
            raw = future.result(timeout=max(0, deadline - time.monotonic()))
        except FutureTimeoutError:
            request_cancellation()
            raise BrokerCommunicationError("Execution response deadline exceeded; cancellation requested") from None
        if time.monotonic() >= deadline:
            request_cancellation()
            raise BrokerCommunicationError("Execution response deadline exceeded; cancellation requested")
        return raw
