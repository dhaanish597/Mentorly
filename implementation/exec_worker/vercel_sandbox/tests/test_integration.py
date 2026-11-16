"""In-process coordinator contract tests; no learner source is executed here."""
import hashlib
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.models.domain import ExecutionObservation, ExecutionRequest, RevisionRef, TraceExecutionReport, TraceRequest, VerificationReport, VerifyJobRequest
from backend.app.orchestration.worker_client import BrokerCommunicationError, PublicCustomCodeDisabledError
from exec_worker.vercel_sandbox.integration import InProcessWorkerClient

SOURCE = "def shortest_subarray_ge_target(nums, target):\n return 1\n"


class Repository:
    def __init__(self, revision):
        self.revision = revision
        self.version = revision.code_version_id
    def get_session(self, _session_id, **_kwargs):
        return SimpleNamespace(deleted_at=None, state="CODE_EDITING", exercise_id=self.revision.exercise_id,
            spec_version=self.revision.spec_version, active_code_version_id=self.version,
            active_turn_generation=self.revision.turn_generation)
    def get_code_version(self, _session_id, _version):
        return SimpleNamespace(code_hash=self.revision.code_hash)


class Runner:
    runtime_version = "controlled-test-double"
    def __init__(self):
        self.executed = 0
        self.cancelled = []
        self.on_execute = None
    def execute(self, _req):
        self.executed += 1
        if self.on_execute:
            self.on_execute()
        return ExecutionObservation(kind="RETURN", return_value=7, error_type=None, error_message=None,
            stdout_excerpt="", stderr_excerpt="", duration_ms=1)
    def trace(self, req):
        return TraceExecutionReport(trace_id=req.trace_id, revision=req.revision, case_hash=req.case_hash,
            status="COMPLETED", steps=[], total_observed=0, trace_truncated=False,
            termination_reason="Controlled test report", observation=self.execute(req), runtime_version=self.runtime_version)
    def cancel_invocation(self, job_id):
        self.cancelled.append(job_id)
        return False
    def check_preflight(self):
        return SimpleNamespace(ready=False, acceptance_verified=False)


@pytest.fixture
def setup():
    revision = RevisionRef(session_id=uuid4(), exercise_id="ex1_shortest_subarray",
        spec_version="v1_positive_only", code_version_id=1,
        code_hash=hashlib.sha256(SOURCE.encode()).hexdigest(), turn_generation=0)
    req = ExecutionRequest(job_id=uuid4(), revision=revision, source_code=SOURCE,
        input_args={"nums": [1], "target": 1}, case_hash="a" * 64)
    repo, runner = Repository(revision), Runner()
    return req, repo, runner


def test_public_gate_is_preserved_before_runner_dispatch(setup):
    req, repo, runner = setup
    client = InProcessWorkerClient(runner=runner, session_repository=repo)
    with pytest.raises(PublicCustomCodeDisabledError):
        client.submit_execution(req, is_public_custom_code=True)
    assert runner.executed == 0


def test_execution_uses_runner_contract_without_http_or_host_execution(setup, monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: pytest.fail("Unexpected broker HTTP"))
    req, repo, runner = setup
    client = InProcessWorkerClient(runner=runner, session_repository=repo)
    result = client.submit_execution(req)
    assert result.status == "COMPLETE" and result.observation.return_value == 7
    assert runner.executed == 1 and client.registry.active_count() == 0


def test_late_result_is_discarded_after_revision_change(setup):
    req, repo, runner = setup
    runner.on_execute = lambda: setattr(repo, "version", 2)
    client = InProcessWorkerClient(runner=runner, session_repository=repo)
    result = client.submit_execution(req)
    assert result.status == "SUPERSEDED" and result.observation is None
    assert req.job_id in runner.cancelled


def test_cancel_before_dispatch_prevents_runner_execution(setup):
    req, repo, runner = setup
    client = InProcessWorkerClient(runner=runner, session_repository=repo)
    assert client.cancel(req.job_id)
    result = client.submit_execution(req)
    assert result.status == "SUPERSEDED" and runner.executed == 0


def test_external_durable_cancellation_is_checked(setup):
    req, repo, runner = setup
    client = InProcessWorkerClient(runner=runner, session_repository=repo,
        external_cancel_check=lambda job_id: job_id == req.job_id)
    assert client.submit_execution(req).status == "SUPERSEDED"
    assert runner.executed == 0


def test_busy_capacity_is_bounded_and_unregistered(setup):
    req, repo, runner = setup
    client = InProcessWorkerClient(runner=runner, session_repository=repo)
    client._capacity.acquire()
    try:
        with pytest.raises(BrokerCommunicationError, match="capacity is busy"):
            client._post_json("/internal/execute", req.model_dump(mode="json"), timeout_seconds=0)
    finally:
        client._capacity.release()
    assert runner.executed == 0 and client.registry.active_count() == 0


def test_verification_uses_existing_harness_and_cancellation_guard(setup, monkeypatch):
    req, repo, runner = setup
    request = VerifyJobRequest(job_id=req.job_id, revision=req.revision, source_code=SOURCE)
    def controlled_harness(_req, _runner, *, cancel_check_fn):
        assert not cancel_check_fn()
        return VerificationReport(status="NO_FAILURE_FOUND", curated_cases_run=1, curated_cases_total=1,
            generated_cases_run=0, generated_cases_target=0, completed_stages=["controlled"],
            terminal_reason="Controlled test report", seed=None, runtime_version=runner.runtime_version)
    monkeypatch.setattr("exec_worker.vercel_sandbox.integration.run_verification_job", controlled_harness)
    client = InProcessWorkerClient(runner=runner, session_repository=repo)
    result = client.submit_verify(request)
    assert result.status == "COMPLETE" and result.verification_report.curated_cases_run == 1


def test_trace_contract_is_preserved(setup):
    req, repo, runner = setup
    request = TraceRequest(**req.model_dump(), trace_id=uuid4())
    client = InProcessWorkerClient(runner=runner, session_repository=repo)
    result = client.submit_trace(request)
    assert result.status == "COMPLETE" and result.trace_report.trace_id == request.trace_id


def test_repository_is_required(setup):
    _, _, runner = setup
    with pytest.raises(ValueError, match="session repository"):
        InProcessWorkerClient(runner=runner, session_repository=None)


def test_runner_failure_releases_capacity(setup):
    req, repo, runner = setup
    def fail():
        raise RuntimeError("Controlled failure")
    runner.on_execute = fail
    client = InProcessWorkerClient(runner=runner, session_repository=repo)
    with pytest.raises(RuntimeError, match="Controlled failure"):
        client.submit_execution(req)
    assert client.registry.active_count() == 0
    assert client._capacity.acquire(timeout=0)
    client._capacity.release()


def test_cancellation_state_failure_before_dispatch_completes_registry(setup):
    req, repo, runner = setup
    def unavailable(_job):
        raise RuntimeError("Controlled state failure")
    client = InProcessWorkerClient(runner=runner, session_repository=repo,
        external_cancel_check=unavailable)
    with pytest.raises(BrokerCommunicationError, match="state unavailable"):
        client.submit_execution(req)
    assert runner.executed == 0 and client.registry.active_count() == 0
    assert client._capacity.acquire(timeout=0)
    client._capacity.release()


def test_superseded_runner_cancellation_failure_completes_new_registry_entry(setup):
    req, repo, runner = setup
    client = InProcessWorkerClient(runner=runner, session_repository=repo)
    old_revision = req.revision.model_copy(update={"turn_generation": 0})
    old_job = uuid4()
    client.registry.register_job(old_job, old_revision)
    newer = req.model_copy(update={"revision": req.revision.model_copy(update={"turn_generation": 1})})
    def unavailable(_job):
        raise RuntimeError("Controlled cancellation failure")
    runner.cancel_invocation = unavailable
    with pytest.raises(RuntimeError, match="Controlled cancellation failure"):
        client._post_json("/internal/execute", newer.model_dump(mode="json"))
    assert runner.executed == 0 and client.registry.active_count() == 0


def test_response_deadline_cancels_active_runner_and_rejects_late_return(setup):
    req, repo, runner = setup
    cancelled = threading.Event()
    def cancel(job):
        runner.cancelled.append(job)
        cancelled.set()
        return True
    runner.cancel_invocation = cancel
    runner.on_execute = lambda: cancelled.wait(timeout=1)
    client = InProcessWorkerClient(runner=runner, session_repository=repo)
    with pytest.raises(BrokerCommunicationError, match="response deadline exceeded"):
        client._post_json("/internal/execute", req.model_dump(mode="json"), timeout_seconds=.02)
    assert cancelled.wait(timeout=1) and req.job_id in runner.cancelled
    assert client.registry.active_count() == 0
    assert client._capacity.acquire(timeout=1)
    client._capacity.release()


def test_expired_response_deadline_dispatches_nothing(setup):
    req, repo, runner = setup
    client = InProcessWorkerClient(runner=runner, session_repository=repo)
    with pytest.raises(BrokerCommunicationError, match="response deadline exceeded"):
        client._post_json("/internal/execute", req.model_dump(mode="json"), timeout_seconds=0)
    assert runner.executed == 0 and client.registry.active_count() == 0


def test_verification_deadline_fences_between_invocations(setup, monkeypatch):
    req, repo, runner = setup
    request = VerifyJobRequest(job_id=req.job_id, revision=req.revision, source_code=SOURCE)
    cancelled = threading.Event()
    runner.cancel_invocation = lambda _job: cancelled.set()
    def controlled_harness(_req, _runner, *, cancel_check_fn):
        assert not cancel_check_fn()
        assert cancelled.wait(timeout=1)
        assert cancel_check_fn()
        return VerificationReport(status="SUPERSEDED", curated_cases_run=0, curated_cases_total=1,
            generated_cases_run=0, generated_cases_target=0, completed_stages=[],
            terminal_reason="Controlled cancellation", seed=None, runtime_version=runner.runtime_version)
    monkeypatch.setattr("exec_worker.vercel_sandbox.integration.run_verification_job", controlled_harness)
    client = InProcessWorkerClient(runner=runner, session_repository=repo)
    with pytest.raises(BrokerCommunicationError, match="response deadline exceeded"):
        client._post_json("/internal/verify", request.model_dump(mode="json"), timeout_seconds=.02)
    assert client._capacity.acquire(timeout=1)
    client._capacity.release()
    assert client.registry.active_count() == 0


def test_timeout_retains_capacity_until_blocked_transport_finishes(setup):
    req, repo, runner = setup
    transport_finished = threading.Event()
    cancelled = threading.Event()
    runner.on_execute = lambda: transport_finished.wait(timeout=1)
    runner.cancel_invocation = lambda _job: cancelled.set()
    client = InProcessWorkerClient(runner=runner, session_repository=repo)
    try:
        with pytest.raises(BrokerCommunicationError, match="response deadline exceeded"):
            client._post_json("/internal/execute", req.model_dump(mode="json"), timeout_seconds=.02)
        assert cancelled.wait(timeout=1)
        assert not client._capacity.acquire(timeout=0)
        other = req.model_copy(update={"job_id": uuid4()})
        with pytest.raises(BrokerCommunicationError, match="capacity is busy"):
            client._post_json("/internal/execute", other.model_dump(mode="json"), timeout_seconds=0)
        assert runner.executed == 1
    finally:
        transport_finished.set()
    assert client._capacity.acquire(timeout=1)
    client._capacity.release()
    assert client.registry.active_count() == 0


def test_explicit_cancellation_deadline_works_with_execution_capacity_held(setup):
    req, repo, runner = setup
    finished = threading.Event()
    runner.cancel_invocation = lambda _job: finished.wait(timeout=1)
    client = InProcessWorkerClient(runner=runner, session_repository=repo)
    client._capacity.acquire()
    try:
        with pytest.raises(BrokerCommunicationError, match="Cancellation response deadline exceeded"):
            client._post_json(f"/internal/cancel/{req.job_id}", timeout_seconds=.02)
        assert client.registry.is_cancelled_or_superseded(req.job_id)
        assert not finished.is_set()
    finally:
        finished.set()
        client._capacity.release()
