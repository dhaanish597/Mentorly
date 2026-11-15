"""Synchronous execution adapter over fresh, disposable deny-all microVMs.

The backend imports this trusted module. Only the guest_files() allowlist is
uploaded. SDK credentials stay in the backend and never reach guest commands.
"""
from __future__ import annotations

import base64
from datetime import timedelta
import hashlib
from importlib.metadata import version
import io
import json
import os
from pathlib import Path
import secrets
import threading
import time
from uuid import UUID

from exec_worker.vercel_sandbox.acceptance import IMAGE, LIMITS, SDK_VERSIONS, guest_files, load_acceptance, verify_sdk_creation_source
from exec_worker.vercel_sandbox.cleanup_store import NAME, SandboxCleanupStore
from exec_worker.vercel_sandbox.supervisor import DIAGNOSTIC_ERROR_TYPES, DIAGNOSTIC_PHASES
from exec_worker.worker_app.sandbox_runner import (
    GVisorSandboxRunner, SandboxRuntimePreflight, _ContainerRunOutcome,
    ExecutionObservation, ExecutionObservationKind, TraceExecutionReport, TraceExecutionStatus,
)
CREATION_IMAGE = "vercel/sandbox/universal"


def single_attempt_creation(client):
    """Pin the reviewed SDK hook per client; never retry an ambiguous create."""
    from vercel.sandbox._internal.api_client import SandboxApiClient
    verify_sdk_creation_source()
    api = client._service.api_client
    original = api._request
    if type(api) is not SandboxApiClient or getattr(original, '__func__', None) is not SandboxApiClient._request:
        raise TransportFailure('Unaccepted Sandbox SDK creation adapter')

    async def request(method, path, **kwargs):
        if method == 'POST' and path == 'v3/sandboxes':
            kwargs['retries'] = 0
        return await original(method, path, **kwargs)

    api._request = request
    return client


class TransportFailure(RuntimeError):
    """Safe error without request metadata or guest data."""
    def __init__(self, message, *, sandbox_name=None, phase=None, error_type=None, status_code=None,
                 supervisor_diagnostic=None, provider_deletion_verified=False):
        super().__init__(message)
        self.sandbox_name = sandbox_name
        self.phase = phase
        self.error_type = error_type
        self.status_code = status_code
        self.supervisor_diagnostic = supervisor_diagnostic
        self.provider_deletion_verified = provider_deletion_verified


class InvalidRunnerOutput(TransportFailure):
    """Malformed guest protocol bytes; distinct from provider unavailability."""


def _supervisor_diagnostic(response: dict):
    """Validate only fixed diagnostic categories; never preserve arbitrary guest text."""
    failure = response.get("failure")
    cleanup = response.get("cleanup_failures", [])
    if not isinstance(cleanup, list) or len(cleanup) > 16:
        raise TransportFailure("invalid supervisor diagnostics")
    if failure is None and not cleanup:
        return None
    def validate(item):
        if (not isinstance(item, dict) or set(item) != {"phase", "error_type", "errno"}
                or type(item["phase"]) is not str or type(item["error_type"]) is not str
                or item["phase"] not in DIAGNOSTIC_PHASES
                or item["error_type"] not in DIAGNOSTIC_ERROR_TYPES
                or (item["errno"] is not None and
                    (type(item["errno"]) is not int or not 0 < item["errno"] < 4096))):
            raise TransportFailure("invalid supervisor diagnostics")
        return dict(item)
    return {"failure": validate(failure) if failure is not None else None,
            "cleanup_failures": [validate(item) for item in cleanup]}


class _BoundedSink(io.RawIOBase):
    def __init__(self, cap: int, on_ready=None):
        self.cap = cap
        self.data = bytearray()
        self.on_ready = on_ready
        self.ready = False
    def writable(self):
        return True
    def write(self, data):
        if len(self.data) + len(data) > self.cap:
            raise TransportFailure("supervisor transport output exceeded limit")
        self.data.extend(data)
        marker = b"VIVA_SUPERVISOR_READY_V1\n"
        if not self.ready and self.data.startswith(marker):
            self.ready = True
            if self.on_ready is not None:
                self.on_ready()
        return len(data)


class VercelSandboxTransport:
    """Transport also used by explicit local acceptance, without a public gate."""
    def __init__(self, client_factory=None, *, cleanup_store: SandboxCleanupStore | None = None):
        self.client_factory = client_factory
        self.cleanup_store = cleanup_store
        self.lock = threading.Lock()
        self.active: dict[UUID, dict[str, object]] = {}
        self.cancelled: set[UUID] = set()
        self.cleanup_obligations: set[str] = set()
        self.ready_jobs: set[UUID] = set()
        self.inflight_names: set[str] = set()

    def _client(self):
        if self.client_factory is not None:
            return self.client_factory()
        from vercel.sandbox.sync import SyncSandboxClient, SandboxServiceOptions
        client = SyncSandboxClient.create(options=SandboxServiceOptions(
            request_timeout=timedelta(seconds=5), file_transfer_timeout=timedelta(seconds=5)))
        try:
            return single_attempt_creation(client)
        except Exception:
            client.close()
            raise TransportFailure('Sandbox SDK creation policy unavailable') from None

    def cancel_invocation(self, job_id: UUID) -> bool:
        with self.lock:
            self.cancelled.add(job_id)
            boxes = list(self.active.get(job_id, {}).values())
        deleted = False
        for box in boxes:
            try:
                box.destroy(delete_orphan_snapshots=True)
                deleted = True
            except Exception:
                # Caller still sees cancellation; run() must verify final cleanup.
                continue
        return deleted

    def is_cancelled(self, job_id: UUID):
        with self.lock:
            cancelled = job_id in self.cancelled
        if cancelled:
            return True
        if getattr(self.cleanup_store, 'enforces_execution_limits', False):
            try:
                return self.cleanup_store.job_cancelled(job_id)
            except Exception:
                raise TransportFailure('durable cancellation state unavailable') from None
        return False

    def run(self, *, job_id: UUID, payload: dict, budget, dispatch_deadline=None):
        from vercel.sandbox import NetworkPolicy, SandboxResources
        for key, maximum in LIMITS.items():
            if getattr(budget, key) > maximum:
                raise ValueError("invocation budget exceeds accepted deployment ceiling")
        payload = {**payload, "invocation_id": str(job_id)}
        raw = json.dumps(payload, separators=(",", ":")).encode()
        if len(raw) > 262144:
            raise ValueError("invocation payload exceeds deployment input ceiling")
        if self.is_cancelled(job_id) or (dispatch_deadline is not None and time.monotonic() >= dispatch_deadline):
            raise TransportFailure("invocation cancelled before launch")
        try:
            staged_files = guest_files()
            for file in staged_files.values():
                if not file.is_file():
                    raise ValueError("Missing native deployment asset")
        except Exception:
            raise TransportFailure("native build unavailable or stale", phase="native_preflight") from None
        name = "viva-inv-" + secrets.token_hex(12)
        if self.cleanup_store is not None:
            try:
                self.cleanup_store.register(name, job_id)
            except Exception:
                raise TransportFailure("durable cleanup registration failed", phase="cleanup_registration") from None
        with self.lock:
            self.inflight_names.add(name)
        client = None
        box = None
        cleanup_ok = False
        provider_absence_verified = False
        creation_attempted = False
        creation_returned = False
        phase = "client_setup"
        safe_error = None
        transport_failure = None
        try:
            client = self._client()
            if self.is_cancelled(job_id) or (dispatch_deadline is not None and time.monotonic() >= dispatch_deadline):
                raise TransportFailure('invocation cancelled before cloud creation')
            phase = "creation"
            creation_attempted = True
            operation = client.create_sandbox(name=name, image=CREATION_IMAGE, persistent=False,
                execution_time_limit=20, network_policy=NetworkPolicy.deny_all(),
                resources=SandboxResources(vcpus=1), ports=[], env={}, mounts={})
            box = operation.__enter__()
            creation_returned = True
            # Verify cached creation metadata before staging or starting a learner.
            if box.image != IMAGE or box.persistent is not False or box.network_policy.mode != "deny-all":
                raise TransportFailure("sandbox creation policy mismatch")
            if self.cleanup_store is not None:
                self.cleanup_store.acknowledge(name)
            with self.lock:
                self.active.setdefault(job_id, {})[name] = box
            if self.is_cancelled(job_id):
                raise TransportFailure("invocation cancelled during creation")
            phase = "staging"
            created_dirs = set()
            for relative, path in staged_files.items():
                remote = "/vercel/sandbox/viva/" + relative
                directory = str(Path(remote).parent)
                if directory not in created_dirs:
                    box.fs.mkdir(directory)
                    created_dirs.add(directory)
                box.fs.write_bytes(remote, path.read_bytes())
            def mark_ready():
                with self.lock:
                    self.ready_jobs.add(job_id)
            stdout, stderr = _BoundedSink(1048576, mark_ready), _BoundedSink(4096)
            phase = "supervision"
            result = box.run_command("python3", ["-I", "/vercel/sandbox/viva/supervisor.py"],
                input=raw, stdout=stdout, stderr=stderr, sudo=True, kill_after=12)
            if result.returncode != 0 or stderr.data:
                raise TransportFailure("supervisor command failed")
            marker = b"VIVA_SUPERVISOR_READY_V1\n"
            response = json.loads(stdout.data[len(marker):] if stdout.ready else stdout.data)
            if response.get("schema") != "viva-supervisor-v1":
                raise TransportFailure("supervisor schema not verified")
            diagnostic = _supervisor_diagnostic(response)
            diagnostic_phase = (diagnostic["failure"]["phase"]
                                if diagnostic and diagnostic["failure"] else phase)
            if response.get("cleanup_verified") is not True:
                raise TransportFailure("supervisor cleanup not verified", phase=diagnostic_phase,
                    supervisor_diagnostic=diagnostic)
            if response.get("reason") == "setup_failure":
                raise TransportFailure("supervisor setup failed", phase=diagnostic_phase,
                    supervisor_diagnostic=diagnostic)
            if not stdout.ready:
                raise TransportFailure("supervisor startup not verified")
            if self.is_cancelled(job_id):
                raise TransportFailure("invocation cancelled")
            response["sandbox_name"] = name
            response["supervisor_ready_verified"] = stdout.ready
            return response
        except TransportFailure as failure:
            transport_failure = failure
            if failure.sandbox_name is None:
                failure.sandbox_name = name
            if failure.phase is None:
                failure.phase = phase
            raise
        except Exception as exc:
            safe_error = {"phase": phase, "error_type": type(exc).__name__, "status_code": getattr(exc, "status_code", None)}
            transport_failure = TransportFailure("sandbox service unavailable", sandbox_name=name, **safe_error)
            raise transport_failure from None
        finally:
            with self.lock:
                self.active.get(job_id, {}).pop(name, None)
                if not self.active.get(job_id):
                    self.active.pop(job_id, None)
                    self.ready_jobs.discard(job_id)
            if not creation_attempted:
                cleanup_ok = True
            else:
                try:
                    # A chosen name lets cleanup find a VM after ambiguous creation.
                    if box is None:
                        box = client.get_sandbox(name=name)
                    box.destroy(delete_orphan_snapshots=True)
                    cleanup_ok = True
                    provider_absence_verified = True
                except Exception as exc:
                    # A 404 also verifies that a concurrently cancelled VM is absent.
                    cleanup_ok = getattr(exc, "status_code", None) == 404
                    provider_absence_verified = cleanup_ok
            if creation_attempted and not creation_returned:
                # A failed/ambiguous request can still be completing remotely.
                # Never erase its durable name based on an immediate 404.
                cleanup_ok = False
                provider_absence_verified = False
            # Retain the obligation before client closure, even if both fail.
            if not cleanup_ok:
                with self.lock:
                    self.cleanup_obligations.add(name)
                if self.cleanup_store is not None:
                    try:
                        self.cleanup_store.require_cleanup(name)
                    except Exception:
                        pass  # The pre-creation durable registration remains.
            elif self.cleanup_store is not None:
                try:
                    self.cleanup_store.complete(name)
                except Exception:
                    cleanup_ok = False
                    with self.lock:
                        self.cleanup_obligations.add(name)
            with self.lock:
                self.inflight_names.discard(name)
            if transport_failure is not None:
                transport_failure.provider_deletion_verified = provider_absence_verified
            if client is not None:
                try:
                    client.close()
                except Exception:
                    raise TransportFailure("sandbox client cleanup failed", sandbox_name=name, phase="client_cleanup",
                        supervisor_diagnostic=transport_failure.supervisor_diagnostic if transport_failure else None,
                        provider_deletion_verified=provider_absence_verified) from None
            if not cleanup_ok:
                raise TransportFailure("sandbox deletion not verified", sandbox_name=name,
                    supervisor_diagnostic=transport_failure.supervisor_diagnostic if transport_failure else None,
                    provider_deletion_verified=provider_absence_verified,
                    **(safe_error or {"phase": "cleanup"}))

    def recover_cleanup(self, job_id: UUID | None = None):
        """Destroy only names previously registered by this trusted backend."""
        if self.cleanup_store is None:
            raise TransportFailure("durable cleanup store unavailable")
        claims = self.cleanup_store.claim_expired() if job_id is None else self.cleanup_store.claim_expired(job_id)
        if not claims:
            return
        client = self._client()
        try:
            for name, creation_acknowledged in claims:
                if not NAME.fullmatch(name):
                    raise TransportFailure("invalid cleanup obligation")
                with self.lock:
                    if name in self.inflight_names:
                        continue
                try:
                    client.get_sandbox(name=name).destroy(delete_orphan_snapshots=True)
                except Exception as exc:
                    if getattr(exc, "status_code", None) != 404:
                        raise TransportFailure("registered Sandbox cleanup failed", sandbox_name=name, phase="recovery") from None
                if not creation_acknowledged:
                    raise TransportFailure("ambiguous creation requires inventory confirmation", sandbox_name=name, phase="recovery")
                self.cleanup_store.complete(name)
                with self.lock:
                    self.cleanup_obligations.discard(name)
        finally:
            try:
                client.close()
            except Exception:
                raise TransportFailure("sandbox recovery client cleanup failed", phase="client_cleanup") from None


def _decode(response: dict, budget):
    allowed = {"exited", "wall_timeout", "startup_timeout", "cpu_limit", "memory_limit", "stdout_limit", "stderr_limit", "setup_failure"}
    reason = response.get("reason")
    if reason not in allowed or type(response.get("duration_ms")) is not int:
        raise TransportFailure("invalid supervisor response")
    def stream(key, cap):
        value = response.get(key)
        if not isinstance(value, str) or len(value) > ((cap + 2) // 3) * 4:
            raise TransportFailure("invalid supervisor stream")
        try:
            decoded = base64.b64decode(value, validate=True)
        except ValueError:
            raise TransportFailure("invalid supervisor stream") from None
        if len(decoded) > cap:
            raise TransportFailure("invalid supervisor stream")
        try:
            return decoded.decode("utf-8", errors="strict" if key == "stdout_b64" else "replace")
        except UnicodeDecodeError:
            raise InvalidRunnerOutput("invalid UTF-8 in guest protocol") from None
    stdout = stream("stdout_b64", budget.max_stdout_bytes + budget.max_trace_bytes + 4096)
    stderr = stream("stderr_b64", budget.max_stderr_bytes)
    return _ContainerRunOutcome(
        returncode=137 if reason in {"cpu_limit", "memory_limit", "stderr_limit"} else response.get("returncode"),
        stdout_text=stdout, stderr_text=stderr, stdout_overflow=reason == "stdout_limit",
        stderr_overflow=reason == "stderr_limit", timed_out=reason in {"wall_timeout", "startup_timeout"},
        startup_timed_out=reason == "startup_timeout", cancelled=False, duration_ms=response["duration_ms"])


class VercelRuntimePreflight(SandboxRuntimePreflight):
    @property
    def summary(self):
        return f"Vercel runtime ready ({self.runtime_version})" if self.ready else "; ".join(self.failure_reasons)[:512]


class VercelSandboxRunner(GVisorSandboxRunner):
    """Existing worker interface with independent, fail-closed Vercel acceptance."""
    def __init__(self, *, transport=None, acceptance_path=None, acceptance_sha256=None, public_execution_enabled=None):
        super().__init__()
        self.transport = transport or VercelSandboxTransport()
        self.acceptance_path = os.environ.get("VCC_VERCEL_SANDBOX_ACCEPTANCE_PATH", "") if acceptance_path is None else acceptance_path
        self.acceptance_sha256 = os.environ.get("VCC_VERCEL_SANDBOX_ACCEPTANCE_SHA256", "") if acceptance_sha256 is None else acceptance_sha256
        self.evidence = None
        self._public_execution_enabled = public_execution_enabled
        self._canary_local = threading.local()
        self._dispatch_local = threading.local()

    def set_dispatch_deadline(self, deadline):
        self._dispatch_local.deadline = deadline

    def check_preflight(self):
        reasons = []
        try:
            if any(version(name) != accepted for name, accepted in SDK_VERSIONS.items()):
                raise ValueError("unaccepted SDK version")
            verify_sdk_creation_source()
            self.evidence = load_acceptance(self.acceptance_path, self.acceptance_sha256)
        except Exception:
            reasons.append("Vercel execution acceptance unavailable or stale")
        enabled = (self._public_execution_enabled() if self._public_execution_enabled is not None else
                   os.environ.get("VCC_PUBLIC_EXECUTION_ENABLED", "").lower() in {"1", "true", "yes", "on"})
        enabled = enabled or getattr(self._canary_local, 'allowed', False)
        if not enabled:
            reasons.append("Public execution is disabled")
        with self.transport.lock:
            if self.transport.cleanup_obligations:
                reasons.append("Unresolved Sandbox deletion obligations")
            inflight = set(self.transport.inflight_names)
        try:
            store = self.transport.cleanup_store
            if store is None or store.durable is not True:
                reasons.append("Durable Sandbox cleanup store unavailable")
            elif getattr(store, 'enforces_execution_limits', False) is not True:
                reasons.append('Shared Sandbox execution limits unavailable')
            elif getattr(store, 'requires_repository_job', False) is not True:
                reasons.append('Durable execution revision guard unavailable')
            elif set(store.blocking()) - inflight:
                reasons.append("Unresolved durable Sandbox cleanup obligations")
            elif not store.quota_available():
                reasons.append('Sandbox invocation quota exhausted')
        except Exception:
            reasons.append("Durable Sandbox cleanup store unavailable")
        ready = not reasons
        return VercelRuntimePreflight(ready=ready, platform_system="Vercel microVM",
            docker_available=False, runsc_registered=False, runsc_binary_available=False,
            runner_image_present=ready, runner_image=IMAGE,
            runtime_version="vercel-python3.14-kernel6.18.56" if ready else "vercel-unavailable",
            failure_reasons=tuple(reasons), acceptance_verified=ready)

    def execute(self, req):
        if hashlib.sha256(req.source_code.encode()).hexdigest() != req.revision.code_hash:
            raise ValueError("Code hash mismatch")
        return super().execute(req)

    def check_canary_preflight(self):
        self._canary_local.allowed = True
        try:
            return self.check_preflight()
        finally:
            self._canary_local.allowed = False

    def execute_operator_canary(self, req):
        from backend.app.core.worker_factory import OPERATOR_CANARY_SOURCE, OPERATOR_CANARY_INPUT
        if (req.source_code != OPERATOR_CANARY_SOURCE
                or json.dumps(req.input_args,sort_keys=True)!=json.dumps(OPERATOR_CANARY_INPUT,sort_keys=True)
                or req.revision.exercise_id != 'ex2_binary_search'
                or req.revision.spec_version != 'v1_sorted_with_duplicates'):
            raise PermissionError('Only the fixed operator canary is permitted')
        self._canary_local.allowed = True
        try:
            return self.execute(req)
        finally:
            self._canary_local.allowed = False

    def trace(self, req):
        if hashlib.sha256(req.source_code.encode()).hexdigest() != req.revision.code_hash:
            raise ValueError("Code hash mismatch")
        return super().trace(req)

    def cancel_invocation(self, job_id: UUID):
        return self.transport.cancel_invocation(job_id)

    def recover_cleanup(self, job_id: UUID):
        return self.transport.recover_cleanup(job_id)

    def is_cancelled(self, job_id: UUID):
        return self.transport.is_cancelled(job_id)

    def _launch_disposable_container(self, *, job_id, payload, budget, **_unused):
        start = time.monotonic()
        try:
            payload = {**payload, "expected_runtime": self.evidence["runtime"] if self.evidence else None}
            response = self.transport.run(job_id=job_id, payload=payload, budget=budget,
                dispatch_deadline=getattr(self._dispatch_local, 'deadline', None))
            if not self.evidence or response.get("runtime") != self.evidence["runtime"]:
                raise TransportFailure("runtime acceptance identity mismatch")
            if response.get("reason") == "setup_failure":
                raise TransportFailure("isolation setup failed")
            return _decode(response, budget)
        except InvalidRunnerOutput:
            return _ContainerRunOutcome(returncode=1, stdout_text="", stderr_text="Invalid guest protocol bytes",
                stdout_overflow=False, stderr_overflow=False, timed_out=False, startup_timed_out=False,
                cancelled=False, duration_ms=int((time.monotonic() - start) * 1000))
        except TransportFailure:
            try:
                cancelled = self.is_cancelled(job_id)
            except TransportFailure:
                cancelled = True
            return _ContainerRunOutcome(returncode=None, stdout_text="", stderr_text="Sandbox unavailable or cancelled",
                stdout_overflow=False, stderr_overflow=False, timed_out=False, startup_timed_out=False,
                cancelled=cancelled, duration_ms=int((time.monotonic() - start) * 1000))

    def _map_execution_outcome(self, outcome, budget):
        if outcome.returncode is None and not outcome.stdout_text and outcome.stderr_text == "Sandbox unavailable or cancelled":
            return ExecutionObservation(kind=ExecutionObservationKind.UNAVAILABLE,
                return_value=None, error_type="SandboxUnavailableError",
                error_message="Sandbox unavailable or invocation cancelled", stdout_excerpt="",
                stderr_excerpt="", duration_ms=outcome.duration_ms)
        return super()._map_execution_outcome(outcome, budget)

    def _map_trace_outcome(self, req, outcome, runtime_version):
        if outcome.returncode is None and not outcome.stdout_text and outcome.stderr_text == "Sandbox unavailable or cancelled":
            return TraceExecutionReport(trace_id=req.trace_id, revision=req.revision, case_hash=req.case_hash,
                status=TraceExecutionStatus.TRACE_UNAVAILABLE, steps=[], total_observed=0,
                trace_truncated=False, termination_reason="Sandbox unavailable or invocation cancelled",
                observation=self._map_execution_outcome(outcome, req.budget), runtime_version=runtime_version)
        if outcome.stdout_overflow or outcome.stderr_overflow or outcome.returncode == 137:
            return TraceExecutionReport(trace_id=req.trace_id, revision=req.revision, case_hash=req.case_hash,
                status=TraceExecutionStatus.PARTIAL, steps=[], total_observed=0,
                trace_truncated=True, termination_reason="Trace resource limit exceeded",
                observation=self._map_execution_outcome(outcome, req.budget), runtime_version=runtime_version)
        return super()._map_trace_outcome(req, outcome, runtime_version)
