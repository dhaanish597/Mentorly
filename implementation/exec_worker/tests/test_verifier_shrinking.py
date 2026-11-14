"""Trusted control-flow tests; doubles return observations without running source."""
from collections import Counter
import hashlib
from uuid import uuid4

from backend.app.exercises import registry
from backend.app.models.domain import ExecutionObservation, RevisionRef, VerifyJobRequest
from backend.app.models.enums import ExecutionObservationKind, ExerciseId, SpecVersion, VerificationStatus, MinimizationStatus
from exec_worker.worker_app.verifier_harness import run_verification_job


class ObservationsOnlyRunner:
    runtime_version = 'controlled-observation-double'
    def __init__(self, decide):
        self.decide = decide
        self.calls = []
        self.counts = Counter()
    def execute(self, request):
        self.calls.append(request)
        self.counts[request.case_hash] += 1
        return ExecutionObservation(kind=ExecutionObservationKind.RETURN,
            return_value=self.decide(request, self.counts[request.case_hash]), duration_ms=0)


def request_for(nums):
    source = 'def max_product_subarray(nums):\n    return 999\n'
    return VerifyJobRequest(job_id=uuid4(), revision=RevisionRef(
        session_id=uuid4(), exercise_id=ExerciseId.EX3_MAX_PRODUCT,
        spec_version=SpecVersion.EX3_V1_BOUNDED_INTS, code_version_id=1,
        code_hash=hashlib.sha256(source.encode()).hexdigest(), turn_generation=1),
        source_code=source, target_input={'nums': nums}, run_curated_suite=False)


def oracle(request):
    return registry.evaluate(str(request.revision.exercise_id), str(request.revision.spec_version), request.input_args)


def test_counterexample_is_actually_shrunk_and_freshly_replayed_with_history():
    runner = ObservationsOnlyRunner(lambda req, n: 999)
    request = request_for([4, -3, 2])
    report = run_verification_job(request, runner)
    assert report.status == VerificationStatus.COUNTEREXAMPLE_CONFIRMED
    assert report.minimization_status == MinimizationStatus.SHRINK_COMPLETED
    assert report.counterexample_input == {'nums': [0]}
    assert runner.calls[-1].input_args == report.counterexample_input
    assert runner.counts[report.counterexample_case_hash] == 2
    assert set(report.executed_case_hashes) == {call.case_hash for call in runner.calls}
    assert all(call.job_id == request.job_id for call in runner.calls)


def test_shrinking_never_executes_reserved_holdout_candidate():
    original = [-2, -3, -4, 1]
    holdout = [-2, -3, -4]
    runner = ObservationsOnlyRunner(lambda req, n: 999 if req.input_args['nums'] in [original, holdout] else oracle(req))
    report = run_verification_job(request_for(original), runner)
    reserved = {registry.case_key('ex3_max_product', 'v1_bounded_ints', c)
                for c in registry.cases('ex3_max_product', 'v1_bounded_ints', 'holdout')}
    assert not reserved.intersection(report.executed_case_hashes)
    assert report.counterexample_input == {'nums': original}


def test_shrunk_candidate_that_does_not_replay_is_not_confirmed():
    runner = ObservationsOnlyRunner(lambda req, n: oracle(req) if req.input_args == {'nums':[0]} and n > 1 else 999)
    report = run_verification_job(request_for([4, -3, 2]), runner)
    assert report.status == VerificationStatus.REPLAY_UNCONFIRMED
    assert 'did not reproduce' in report.terminal_reason


def test_probe_budget_is_honestly_limited():
    original = [10] * 12
    runner = ObservationsOnlyRunner(lambda req, n: 999 if req.input_args['nums'] == original else oracle(req))
    report = run_verification_job(request_for(original), runner)
    assert report.minimization_status == MinimizationStatus.BUDGET_LIMITED
    assert len(runner.calls) <= 27  # Initial + fresh replay + at most 25 shrink probes.
    assert report.counterexample_input == {'nums': original}
