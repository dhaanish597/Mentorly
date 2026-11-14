"""Seeded generation and verifier state tests, NOT sandbox/isolation evidence.

Protocol doubles never evaluate learner source; only trusted oracle code is run.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
from pathlib import Path
import time
from typing import Any
from uuid import uuid4

import hypothesis
from hypothesis import strategies as st
import pytest

from backend.app.exercises import registry
from backend.app.models.domain import (
    ExecutionBudgetConfig,
    ExecutionObservation,
    RevisionRef,
    VerifyJobRequest,
)
from backend.app.models.enums import ExecutionObservationKind, VerificationStatus
from backend.app.verification import hypothesis_strategies as generation
from exec_worker.worker_app import verifier_harness as harness

SPECS = [(spec.exercise_id, spec.spec_version) for spec in registry.list_specs()]
EX, SPEC = "ex3_max_product", "v1_bounded_ints"


def batch(**kwargs: Any) -> Any:
    return generation.generate_property_batch(EX, SPEC, **kwargs)


def keys(exercise_id: str, spec_version: str, cases: Any) -> set[str]:
    return {registry.case_key(exercise_id, spec_version, case) for case in cases}


@pytest.mark.parametrize("exercise_id,spec_version", SPECS)
def test_seeded_generation_is_reproducible_legal_unique_and_reserved_free(
    exercise_id: str, spec_version: str,
) -> None:
    exclusions = keys(exercise_id, spec_version, registry.cases(exercise_id, spec_version, "curriculum"))
    original = set(exclusions)
    first = generation.generate_property_cases(
        exercise_id, spec_version, count=100, seed=23, exclude_hashes=exclusions,
    )
    second = generation.generate_property_cases(
        exercise_id, spec_version, count=100, seed=23, exclude_hashes=exclusions,
    )
    assert first == second
    expected_count = min(100, registry.generated_case_capacity(exercise_id, spec_version, exclusions))
    assert len(first) == len(keys(exercise_id, spec_version, first)) == expected_count
    reserved = keys(exercise_id, spec_version, registry.cases(exercise_id, spec_version, "holdout"))
    assert keys(exercise_id, spec_version, first).isdisjoint(reserved | exclusions)
    assert all(registry.validate_input(exercise_id, spec_version, case) == case for case in first)
    assert exclusions == original


@pytest.mark.parametrize("exercise_id,spec_version", SPECS)
def test_shared_worker_generator_preserves_boundary_priority(
    exercise_id: str, spec_version: str,
) -> None:
    boundaries = generation._structured_boundary_candidates(exercise_id, spec_version)
    reserved = keys(exercise_id, spec_version, registry.cases(exercise_id, spec_version, "holdout"))
    expected = []
    for case in boundaries:
        key = registry.case_key(exercise_id, spec_version, case)
        if key not in reserved:
            expected.append(case)
            reserved.add(key)
    actual = harness.generate_bounded_cases(exercise_id, spec_version, count=20, seed=41)
    assert actual[:len(expected)] == expected
    assert actual == generation.generate_property_cases(exercise_id, spec_version, count=20, seed=41)


def test_seed_changes_hypothesis_tail_not_boundary_prefix() -> None:
    first = batch(count=40, seed=1)
    second = batch(count=40, seed=2)
    assert first.cases[:6] == second.cases[:6]
    assert first.cases[6:] != second.cases[6:]
    assert first.stop_reason == second.stop_reason == "target_reached"
    assert first.seed == 1 and second.seed == 2


def test_records_installed_version_and_bounded_configuration() -> None:
    result = batch(count=30, seed=9, max_attempts=60, generation_wall_ms=1500)
    assert result.hypothesis_version == hypothesis.__version__ == "6.170.15"
    assert result.max_attempts == 60 and result.generation_wall_ms == 1500
    assert 30 <= result.attempts <= 60
    assert result.invalid >= 0  # Includes Hypothesis-discarded draws, not just schema rejection.
    assert result.attempts == len(result.cases) + result.invalid + result.duplicates + result.excluded


def test_only_public_generate_phase_is_used_without_database(monkeypatch: pytest.MonkeyPatch) -> None:
    configured = []
    original = hypothesis.settings

    def capture_settings(*args: Any, **kwargs: Any) -> Any:
        configured.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(generation, "settings", capture_settings, raising=False)
    monkeypatch.setattr(generation, "_structured_boundary_candidates", lambda *args: [])
    actual = generation.generate_property_cases(EX, SPEC, count=10, seed=3)
    assert len(actual) == 10
    assert configured
    assert configured[0]["database"] is None
    assert configured[0]["deadline"] is None
    assert configured[0]["phases"] == (hypothesis.Phase.generate,)
    assert configured[0]["max_examples"] <= 150


def test_worker_delegates_to_one_shared_generator(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    sentinel = [{"nums": [9]}]

    def shared(exercise_id: str, spec_version: str, **kwargs: Any) -> list[dict[str, Any]]:
        calls.append((exercise_id, spec_version, kwargs))
        return deepcopy(sentinel)

    monkeypatch.setattr(generation, "generate_property_cases", shared)
    excluded = {"a" * 64}
    actual = harness.generate_bounded_cases(EX, SPEC, 1, 7, exclude_hashes=excluded)
    assert actual == sentinel
    assert len(calls) == 1
    assert calls[0][2]["count"] == 1 and calls[0][2]["seed"] == 7
    assert calls[0][2]["exclude_hashes"] == excluded


@pytest.mark.parametrize("count", [0, -1])
def test_empty_requested_count_does_not_start_hypothesis(count: int, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Hypothesis must not start for an empty requested count")

    monkeypatch.setattr(generation, "_input_strategy", forbidden, raising=False)
    assert generation.generate_property_cases(EX, SPEC, count=count) == []
    assert harness.generate_bounded_cases(EX, SPEC, count=count) == []


@pytest.mark.parametrize("count", [None, True, 1.5, "2", [], 10_000])
def test_invalid_or_excessive_count_fails_fast(count: Any) -> None:
    with pytest.raises(ValueError):
        generation.generate_property_cases(EX, SPEC, count=count)


@pytest.mark.parametrize("seed", [None, True, 1.5, "7"])
def test_invalid_seed_fails_fast(seed: Any) -> None:
    with pytest.raises(ValueError):
        generation.generate_property_cases(EX, SPEC, seed=seed)


@pytest.mark.parametrize("exercise_id,spec_version", [(None, SPEC), (EX, None), ("", SPEC), ("ex3_max_product​", SPEC), (EX, "DROP TABLE;")])
def test_invalid_spec_identity_is_rejected(exercise_id: Any, spec_version: Any) -> None:
    with pytest.raises(ValueError):
        generation.generate_property_cases(exercise_id, spec_version, count=1)


@pytest.mark.parametrize("option,value", [("max_attempts", -1), ("max_attempts", True), ("max_attempts", 10_000), ("generation_wall_ms", -1), ("generation_wall_ms", float("nan")), ("generation_wall_ms", None)])
def test_invalid_generation_limits_fail_fast(option: str, value: Any) -> None:
    with pytest.raises(ValueError):
        batch(**{option: value})


def test_boundary_and_hypothesis_candidates_share_attempt_limit() -> None:
    result = batch(count=100, max_attempts=2)
    assert len(result.cases) == result.attempts == 2
    assert result.stop_reason == "attempt_limit"


def test_zero_attempt_budget_never_emits_boundaries() -> None:
    result = batch(count=10, max_attempts=0)
    assert result.cases == () and result.attempts == 0
    assert result.stop_reason == "attempt_limit"


def test_zero_wall_budget_never_emits_boundaries() -> None:
    result = batch(count=10, generation_wall_ms=0)
    assert result.cases == () and result.attempts == 0
    assert result.stop_reason == "wall_time_limit"


def test_generation_wall_budget_includes_spec_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [0.0]
    original = registry.get_spec
    first = [True]

    def slow_initial_spec(*args: Any) -> Any:
        if first[0]:
            now[0] += 0.020
            first[0] = False
        return original(*args)

    monkeypatch.setattr(registry, "get_spec", slow_initial_spec)
    monkeypatch.setattr(registry, "cases", lambda *args: [])
    monkeypatch.setattr(generation, "_structured_boundary_candidates", lambda *args: [{"nums": [7]}])
    result = batch(count=1, generation_wall_ms=10, clock_fn=lambda: now[0])
    assert result.cases == () and result.stop_reason == "wall_time_limit"


@pytest.mark.parametrize("count", [1, 100])
def test_late_case_copy_cannot_imply_generation_completion(count: int, monkeypatch: pytest.MonkeyPatch) -> None:
    now = [0.0]
    original = generation.deepcopy

    def slow_copy(value: Any) -> Any:
        now[0] += 0.020
        return original(value)

    monkeypatch.setattr(generation, "deepcopy", slow_copy)
    result = batch(count=count, generation_wall_ms=10, clock_fn=lambda: now[0])
    assert result.cases == () and result.stop_reason == "wall_time_limit"


def test_total_wall_budget_includes_boundary_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [0.0]
    original = registry.validate_input

    def slow_validation(*args: Any) -> Any:
        now[0] += 0.020
        return original(*args)

    monkeypatch.setattr(registry, "validate_input", slow_validation)
    result = batch(count=100, generation_wall_ms=10, clock_fn=lambda: now[0])
    assert result.cases == ()
    assert result.stop_reason == "wall_time_limit"
    assert now[0] < 1.0


def test_cutoff_during_hypothesis_keeps_prior_cases_not_late_case(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [0.0]
    monkeypatch.setattr(generation, "_structured_boundary_candidates", lambda *args: [])
    monkeypatch.setattr(registry, "cases", lambda *args: [])
    candidates = [{"nums": [7]}, {"nums": [8]}]
    monkeypatch.setattr(generation, "_input_strategy", lambda *args: st.sampled_from(candidates), raising=False)
    original = registry.validate_input

    def slow_validation(*args: Any) -> Any:
        now[0] += 0.010
        return original(*args)

    monkeypatch.setattr(registry, "validate_input", slow_validation)
    result = batch(count=10, generation_wall_ms=25, clock_fn=lambda: now[0])
    assert result.cases == ({"nums": [7]},)
    assert result.stop_reason == "wall_time_limit"


@pytest.mark.parametrize("candidate,category", [({"nums": [7]}, "duplicates"), ({"nums": [True]}, "invalid"), ({"nums": [-2, -3, -4]}, "excluded")])
def test_duplicate_invalid_and_holdout_streams_terminate_honestly(
    candidate: dict[str, Any], category: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(generation, "_structured_boundary_candidates", lambda *args: [candidate] * 3)
    monkeypatch.setattr(generation, "_input_strategy", lambda *args: st.just(candidate), raising=False)
    result = batch(count=5, max_attempts=8)
    assert result.attempts <= 8
    assert len(result.cases) <= 1
    assert getattr(result, category) > 0
    assert result.stop_reason in {"attempt_limit", "hypothesis_exhausted"}


def test_rejected_hypothesis_draws_also_consume_attempt_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generation, "_structured_boundary_candidates", lambda *args: [])
    monkeypatch.setattr(generation, "_input_strategy", lambda *args: st.integers().filter(lambda value: False))
    result = batch(count=5, max_attempts=2)
    assert result.attempts == 2
    assert result.cases == () and result.stop_reason == "attempt_limit"


def test_unexpected_hypothesis_strategy_errors_are_not_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    from hypothesis.errors import FlakyStrategyDefinition

    def broken_strategy(*args: Any) -> Any:
        raise FlakyStrategyDefinition("broken trusted strategy")

    monkeypatch.setattr(generation, "_structured_boundary_candidates", lambda *args: [])
    monkeypatch.setattr(generation, "_input_strategy", broken_strategy)
    with pytest.raises(FlakyStrategyDefinition, match="broken trusted strategy"):
        batch(count=5)


def test_supplied_exclusion_filters_hypothesis_not_only_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    candidate = {"nums": [7]}
    exclusion = keys(EX, SPEC, [candidate])
    monkeypatch.setattr(generation, "_structured_boundary_candidates", lambda *args: [])
    monkeypatch.setattr(generation, "_input_strategy", lambda *args: st.just(candidate), raising=False)
    result = batch(count=5, exclude_hashes=exclusion)
    assert result.cases == () and result.excluded > 0
    assert exclusion == keys(EX, SPEC, [candidate])


def test_outputs_do_not_alias_candidates_or_subsequent_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    candidate = {"nums": [7]}
    monkeypatch.setattr(generation, "_structured_boundary_candidates", lambda *args: [])
    monkeypatch.setattr(generation, "_input_strategy", lambda *args: st.just(candidate), raising=False)
    first = generation.generate_property_cases(EX, SPEC, count=1)
    first[0]["nums"].append(8)
    second = generation.generate_property_cases(EX, SPEC, count=1)
    assert candidate == second[0] == {"nums": [7]}


def test_sorted_duplicates_and_legal_empty_array_remain_available() -> None:
    actual = generation.generate_property_cases("ex2_binary_search", "v1_sorted_with_duplicates", count=20)
    assert {"nums": [], "target": 0} in actual
    assert {"nums": [2, 2, 2, 2], "target": 2} in actual
    assert all(case["nums"] == sorted(case["nums"]) for case in actual)


def test_concurrent_seeded_calls_have_no_shared_result_state() -> None:
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: generation.generate_property_cases(EX, SPEC, count=30, seed=11), range(2)))
    assert results[0] == results[1] and len(results[0]) == 30
    results[0][0]["nums"].append(10)
    assert results[0] != results[1]


class StateOnlyRunner:
    """Verifier protocol fixture. No learner execution or sandbox evidence."""
    runtime_version = "state-only-fixture"

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def execute(self, request: Any) -> ExecutionObservation:
        self.calls.append(request)
        return ExecutionObservation(
            kind=ExecutionObservationKind.RETURN,
            return_value=registry.evaluate(str(request.revision.exercise_id), str(request.revision.spec_version), request.input_args),
            duration_ms=1,
        )


def request(*, count: int = 20, curated: bool = False) -> VerifyJobRequest:
    source = "raise RuntimeError('learner source must never execute in generation')\n"
    return VerifyJobRequest(
        job_id=uuid4(),
        revision=RevisionRef(
            session_id=uuid4(), exercise_id=EX, spec_version=SPEC,
            code_version_id=1, code_hash=hashlib.sha256(source.encode()).hexdigest(), turn_generation=1,
        ),
        source_code=source, run_curated_suite=curated, generated_cases_target=count, seed=3,
        budget=ExecutionBudgetConfig(job_wall_ms=2500, replay_reserve_ms=1000),
    )


def test_worker_passes_remaining_wall_budget_and_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    observed = []
    tick = iter([0.0, 0.4])

    def clock() -> float:
        return next(tick, 0.4)

    def generate(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        observed.append(kwargs)
        return []

    monkeypatch.setattr(harness, "generate_bounded_cases", generate)
    runner = StateOnlyRunner()
    report = harness.run_verification_job(request(), runner, clock_fn=clock)
    assert report.status == VerificationStatus.VERIFICATION_INCOMPLETE
    assert not runner.calls
    assert 0 < observed[0]["generation_wall_ms"] <= 1100
    assert observed[0]["clock_fn"] is clock


def test_exhausted_verification_budget_does_not_start_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    tick = iter([0.0, 2.0])
    monkeypatch.setattr(generation, "_input_strategy", lambda *args: pytest.fail("generation started after budget expired"), raising=False)
    runner = StateOnlyRunner()
    report = harness.run_verification_job(request(), runner, clock_fn=lambda: next(tick, 2.0))
    assert report.status == VerificationStatus.VERIFICATION_INCOMPLETE
    assert report.generated_cases_run == 0 and not runner.calls


@pytest.mark.parametrize("curated", [False, True])
def test_underfilled_generated_search_cannot_report_success(curated: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(harness, "generate_bounded_cases", lambda *args, **kwargs: [{"nums": [7]}])
    runner = StateOnlyRunner()
    report = harness.run_verification_job(request(count=20, curated=curated), runner)
    assert report.status == VerificationStatus.VERIFICATION_INCOMPLETE
    assert report.generated_cases_run == 1 and report.generated_cases_target == 20


def test_zero_required_cases_never_succeeds() -> None:
    runner = StateOnlyRunner()
    report = harness.run_verification_job(request(count=0), runner)
    assert report.status == VerificationStatus.VERIFICATION_INCOMPLETE
    assert report.completed_stages == [] and not runner.calls


def test_actual_generated_suite_completes_only_via_state_only_protocol_runner() -> None:
    runner = StateOnlyRunner()
    report = harness.run_verification_job(request(count=20), runner)
    assert report.status == VerificationStatus.NO_FAILURE_FOUND
    assert report.runtime_version == "state-only-fixture"
    assert report.generated_cases_run == 20 and len(runner.calls) == 20
    assert len(set(report.executed_case_hashes)) == 20


def test_real_elapsed_cutoff_is_bounded_without_learner_execution() -> None:
    start = time.monotonic()
    result = batch(count=200, generation_wall_ms=1)
    assert time.monotonic() - start < 0.5
    assert len(result.cases) < 200 and result.stop_reason == "wall_time_limit"


@pytest.mark.parametrize("exclusions", [[], {"invalid"}, {None}, {"A" * 64}])
def test_malformed_supplied_exclusions_fail_fast(exclusions: Any) -> None:
    with pytest.raises(ValueError):
        batch(exclude_hashes=exclusions)


def test_cancelled_generation_never_draws(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generation, "_input_strategy", lambda *args: pytest.fail("cancelled generation drew an input"))
    result = batch(cancel_check_fn=lambda: True)
    assert result.cases == () and result.attempts == 0
    assert result.stop_reason == "cancelled"


def test_cancelled_generation_job_remains_superseded() -> None:
    runner = StateOnlyRunner()
    report = harness.run_verification_job(request(), runner, cancel_check_fn=lambda: True)
    assert report.status == VerificationStatus.SUPERSEDED
    assert report.generated_cases_run == 0 and not runner.calls


@pytest.mark.parametrize("exercise_id,spec_version", SPECS)
def test_maximum_configured_count_is_met(exercise_id: str, spec_version: str) -> None:
    actual = harness.generate_bounded_cases(exercise_id, spec_version, count=200, seed=23)
    expected_count = registry.generated_case_capacity(exercise_id, spec_version)
    assert len(actual) == len(keys(exercise_id, spec_version, actual)) == expected_count


def test_worker_caps_generation_to_shared_default(monkeypatch: pytest.MonkeyPatch) -> None:
    observed = []

    def shared(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        observed.append(kwargs)
        return []

    monkeypatch.setattr(generation, "generate_property_cases", shared)
    assert harness.generate_bounded_cases(EX, SPEC, generation_wall_ms=100_000) == []
    assert observed[0]["generation_wall_ms"] == generation.DEFAULT_GENERATION_WALL_MS


@pytest.mark.parametrize("wall_ms", [-1, True, float("inf")])
def test_worker_rejects_invalid_remaining_wall_budget(wall_ms: Any) -> None:
    with pytest.raises(ValueError):
        harness.generate_bounded_cases(EX, SPEC, generation_wall_ms=wall_ms)


def test_requirement_pins_match_already_installed_hypothesis() -> None:
    root = Path(__file__).resolve().parents[2]
    for relative in ("backend/requirements.txt", "exec_worker/requirements.worker.txt"):
        assert f"hypothesis=={hypothesis.__version__}" in (root / relative).read_text().splitlines()
