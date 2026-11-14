"""Generation provenance is metadata, never learner execution evidence."""
import pytest
from pydantic import ValidationError

from backend.app.models.domain import HypothesisStatistics
from exec_worker.worker_app.verifier_harness import run_verification_job
from exec_worker.tests.test_hypothesis_budgets import StateOnlyRunner, request


def test_verification_serializes_safe_seeded_generation_metadata():
    job = request(count=20)
    report = run_verification_job(job, StateOnlyRunner())
    stats = report.hypothesis_stats
    assert stats is not None
    assert stats.engine == "hypothesis"
    assert stats.version == "6.170.15"
    assert stats.seed == job.seed
    assert stats.requested_cases == 20
    assert stats.accepted_cases == 20
    assert stats.executed_cases == report.generated_cases_run == 20
    assert stats.stop_reason == "target_reached"
    assert "cases" not in stats.model_dump()
    assert "nums" not in stats.model_dump_json()


def test_statistics_reject_hidden_inputs_and_invalid_counts():
    valid = dict(version="6.170.15", seed=1, requested_cases=1, accepted_cases=1,
        attempts=1, invalid=0, duplicates=0, excluded=0, executed_cases=0,
        max_attempts=100, generation_wall_ms=2000, stop_reason="target_reached")
    with pytest.raises(ValidationError):
        HypothesisStatistics(**valid, cases=[{"nums": [1]}])
    with pytest.raises(ValidationError):
        HypothesisStatistics(**{**valid, "attempts": -1})


def test_no_generation_does_not_fabricate_engine_statistics():
    report = run_verification_job(request(count=0, curated=True), StateOnlyRunner())
    assert report.hypothesis_stats is None
