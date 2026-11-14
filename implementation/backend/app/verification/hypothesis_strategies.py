"""Shared seeded Hypothesis generation for the four immutable domains (§9.3).

Only trusted, bounded data strategies run here, never learner code. Boundaries
have priority; both boundaries and Hypothesis examples consume the attempt cap.
Wall cutoff is cooperative between bounded draws/validation operations, not a
sandbox deadline. An interrupted search returns fewer cases, never completion.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import time
from typing import Any, Callable

from hypothesis import HealthCheck, Phase, __version__ as hypothesis_version
from hypothesis import given, seed as hypothesis_seed, settings
from hypothesis import strategies as st
from hypothesis.errors import FlakyStrategyDefinition

MAX_GENERATED_CASES = 200
ATTEMPTS_PER_CASE = 15
MIN_GENERATION_ATTEMPTS = 100
MAX_GENERATION_ATTEMPTS = MAX_GENERATED_CASES * ATTEMPTS_PER_CASE
DEFAULT_GENERATION_WALL_MS = 2000
MAX_GENERATION_WALL_MS = 300000

try:
    from backend.app.exercises import registry as exercise_registry
except ImportError:  # pragma: no cover
    from app.exercises import registry as exercise_registry  # type: ignore[no-redef]


def _structured_boundary_candidates(exercise_id: str, spec_version: str) -> list[dict[str, Any]]:
    exercise_registry.get_spec(exercise_id, spec_version)
    candidates: list[dict[str, Any]] = []

    if exercise_id == "ex1_shortest_subarray":
        if spec_version == "v1_positive_only":
            candidates.extend(
                [
                    {"nums": [1], "target": 1},
                    {"nums": [1], "target": 2},
                    {"nums": [5, 1, 5], "target": 5},
                    {"nums": [2, 3, 1, 2, 4, 3], "target": 7},
                    {"nums": [1, 1, 1, 1, 1], "target": 6},
                ]
            )
        else:
            candidates.extend(
                [
                    {"nums": [3, -2, 5], "target": 6},
                    {"nums": [4, -3, 4, -2, 5], "target": 7},
                    {"nums": [-5, 8, -2, 6], "target": 10},
                    {"nums": [2, -1, 2, 3], "target": 5},
                    {"nums": [-10, -5, 12], "target": 12},
                ]
            )
    elif exercise_id == "ex2_binary_search":
        candidates.extend(
            [
                {"nums": [], "target": 0},
                {"nums": [5], "target": 5},
                {"nums": [5], "target": 6},
                {"nums": [5], "target": 4},
                {"nums": [2, 2, 2, 2], "target": 2},
                {"nums": [-10, -5, -5, 0, 0, 5], "target": -5},
                {"nums": [-10, -5, -5, 0, 0, 5], "target": 6},
            ]
        )
    elif exercise_id == "ex3_max_product":
        candidates.extend(
            [
                {"nums": [-2]},
                {"nums": [0, -2, 0]},
                {"nums": [-2, 3, -4]},
                {"nums": [-2, 0, -1]},
                {"nums": [2, -5, -2, -4, 3]},
                {"nums": [-1, -2, -3, 0, -4, -5]},
            ]
        )

    else:
        candidates.extend(exercise_registry.cases(exercise_id, spec_version, 'boundary'))
    # Validation happens in the collector, inside its time and attempt limits.
    return candidates


def _input_strategy(exercise_id: str, spec_version: str) -> st.SearchStrategy[dict[str, Any]]:
    """Plan §3.1.4/3.2.3/3.3.3 strategies, parameterized by the trusted spec."""
    spec = exercise_registry.get_spec(exercise_id, spec_version)
    def strategy(rule: dict) -> st.SearchStrategy:
        kind = rule['kind']
        if kind == 'integer':
            return st.integers(min_value=rule['minimum'], max_value=rule['maximum'])
        if kind == 'boolean':
            return st.booleans()
        if kind == 'string':
            return st.text(alphabet=' abcdefghijklmnopqrstuvwxyzABCDE0123456789()[]{}\t\nதமிழ்', min_size=rule['min_length'], max_size=rule['max_length'])
        values = st.lists(strategy(rule['items']), min_size=rule['min_length'], max_size=rule['max_length'])
        return values.map(sorted) if rule.get('sorted_required') else values
    return st.fixed_dictionaries({name: strategy(rule) for name, rule in spec.input_schema.items()})


@dataclass(frozen=True)
class GenerationBatch:
    """Local generation provenance; this is not an execution evidence contract."""
    cases: tuple[dict[str, Any], ...]
    seed: int
    attempts: int
    invalid: int
    duplicates: int
    excluded: int
    max_attempts: int
    generation_wall_ms: int
    stop_reason: str
    hypothesis_version: str = hypothesis_version


class _GenerationStopped(BaseException):
    """Control flow, not a failing property to shrink or replay in Hypothesis."""


class _Collector:
    def __init__(
        self, exercise_id: str, spec_version: str, count: int, seed: int,
        max_attempts: int, generation_wall_ms: int, exclude_hashes: set[str],
        clock_fn: Callable[[], float], cancel_check_fn: Callable[[], bool] | None,
        start_ts: float,
    ) -> None:
        self.exercise_id, self.spec_version = exercise_id, spec_version
        self.count, self.seed = count, seed
        self.max_attempts, self.generation_wall_ms = max_attempts, generation_wall_ms
        self.clock_fn, self.cancel_check_fn = clock_fn, cancel_check_fn
        self.deadline = start_ts + generation_wall_ms / 1000
        self.reserved = set(exclude_hashes)
        self.seen: set[str] = set()
        self.results: list[dict[str, Any]] = []
        self.attempts = self.invalid = self.duplicates = self.excluded = 0
        self.stop_reason = "empty_request" if count <= 0 else "hypothesis_exhausted"

    def _stop(self, reason: str) -> None:
        self.stop_reason = reason
        raise _GenerationStopped()

    def check_time(self) -> None:
        if self.cancel_check_fn is not None and self.cancel_check_fn():
            self._stop("cancelled")
        if self.clock_fn() >= self.deadline:
            self._stop("wall_time_limit")

    def check_budget(self) -> None:
        self.check_time()
        if self.attempts >= self.max_attempts:
            self._stop("attempt_limit")

    def collect(self, candidate: dict[str, Any]) -> None:
        self.check_budget()
        self.attempts += 1
        self._accept(candidate)

    def _accept(self, candidate: dict[str, Any]) -> None:
        self.check_time()
        try:
            canonical = exercise_registry.validate_input(self.exercise_id, self.spec_version, candidate)
        except ValueError:
            self.invalid += 1
            self.check_time()
            return
        key = exercise_registry.case_key(self.exercise_id, self.spec_version, canonical)
        self.check_time()
        if key in self.reserved:
            self.excluded += 1
        elif key in self.seen:
            self.duplicates += 1
        else:
            copied = deepcopy(canonical)
            self.check_time()
            self.seen.add(key)
            self.results.append(copied)
            if len(self.results) >= self.count:
                self._stop("target_reached")

    def _hypothesis_collect(self) -> None:
        self.check_budget()
        strategy = _input_strategy(self.exercise_id, self.spec_version)

        @hypothesis_seed(self.seed)
        @settings(
            max_examples=self.max_attempts - self.attempts,
            database=None,
            deadline=None,
            phases=(Phase.generate,),
            suppress_health_check=(HealthCheck.too_slow,),
        )
        @given(data=st.data())
        def collect(data: st.DataObject) -> None:
            # Enter before drawing so even Hypothesis-rejected draws consume
            # an attempt. No assumptions/filters can bypass our outer cap.
            self.check_budget()
            self.attempts += 1
            drawn = False
            try:
                candidate = data.draw(strategy)
                drawn = True
            finally:
                if not drawn:
                    self.invalid += 1
            self._accept(candidate)

        self.check_budget()
        collect()
        self.check_budget()

    def run(self) -> GenerationBatch:
        if self.count > 0:
            try:
                self.check_budget()
                for case in exercise_registry.cases(self.exercise_id, self.spec_version, "holdout"):
                    self.check_budget()
                    self.reserved.add(exercise_registry.case_key(self.exercise_id, self.spec_version, case))
                self.check_budget()
                for case in _structured_boundary_candidates(self.exercise_id, self.spec_version):
                    self.collect(case)
                self._hypothesis_collect()
            except _GenerationStopped:
                pass
            except FlakyStrategyDefinition as exc:
                # Hypothesis can wrap an early stop before data.draw() when
                # revisiting a previously rejected draw prefix. Only our exact
                # control exception is a bounded interruption, never a pass.
                if not isinstance(exc.__context__, _GenerationStopped):
                    raise
            # Hypothesis teardown is also part of generation time. Do not let
            # the list compatibility API imply completion after a late cutoff.
            try:
                self.check_time()
            except _GenerationStopped:
                if len(self.results) >= self.count:
                    self.results = self.results[:-1]
        return GenerationBatch(
            cases=tuple(self.results), seed=self.seed, attempts=self.attempts,
            invalid=self.invalid, duplicates=self.duplicates, excluded=self.excluded,
            max_attempts=self.max_attempts, generation_wall_ms=self.generation_wall_ms,
            stop_reason=self.stop_reason,
        )


def _validated_limits(count: int, seed: int, max_attempts: int | None, generation_wall_ms: int) -> int:
    if type(count) is not int or count > MAX_GENERATED_CASES:
        raise ValueError(f"count must be an integer no greater than {MAX_GENERATED_CASES}")
    if type(seed) is not int:
        raise ValueError("seed must be a strict integer")
    if max_attempts is None:
        max_attempts = max(count * ATTEMPTS_PER_CASE, MIN_GENERATION_ATTEMPTS)
    if type(max_attempts) is not int or not 0 <= max_attempts <= MAX_GENERATION_ATTEMPTS:
        raise ValueError(f"max_attempts must be an integer in [0, {MAX_GENERATION_ATTEMPTS}]")
    if type(generation_wall_ms) is not int or not 0 <= generation_wall_ms <= MAX_GENERATION_WALL_MS:
        raise ValueError(f"generation_wall_ms must be an integer in [0, {MAX_GENERATION_WALL_MS}]")
    return max_attempts


def generate_property_batch(
    exercise_id: str,
    spec_version: str,
    *,
    count: int = 100,
    seed: int = 0,
    exclude_hashes: set[str] | None = None,
    max_attempts: int | None = None,
    generation_wall_ms: int = DEFAULT_GENERATION_WALL_MS,
    clock_fn: Callable[[], float] = time.monotonic,
    cancel_check_fn: Callable[[], bool] | None = None,
) -> GenerationBatch:
    """Collect copied legal inputs and provenance using only public Hypothesis APIs.

    Reproducibility requires the same seed, pinned version and configuration,
    with enough wall budget to finish. Finite-domain/attempt exhaustion is not
    silently padded to the requested count; the verifier must remain incomplete.
    """
    start_ts = clock_fn()
    attempts = _validated_limits(count, seed, max_attempts, generation_wall_ms)
    if exclude_hashes is not None and (
        type(exclude_hashes) not in (set, frozenset)
        or any(type(key) is not str or len(key) != 64 or any(c not in "0123456789abcdef" for c in key) for key in exclude_hashes)
    ):
        raise ValueError("exclude_hashes must contain SHA-256 hex strings")
    exercise_registry.get_spec(str(exercise_id), str(spec_version))
    return _Collector(
        str(exercise_id), str(spec_version), count, seed, attempts,
        generation_wall_ms, set(exclude_hashes or ()), clock_fn, cancel_check_fn, start_ts,
    ).run()


def generate_property_cases(
    exercise_id: str,
    spec_version: str,
    *,
    count: int = 100,
    seed: int = 0,
    exclude_hashes: set[str] | None = None,
    max_attempts: int | None = None,
    generation_wall_ms: int = DEFAULT_GENERATION_WALL_MS,
    clock_fn: Callable[[], float] = time.monotonic,
    cancel_check_fn: Callable[[], bool] | None = None,
    stats_callback: Callable[[GenerationBatch], None] | None = None,
) -> list[dict[str, Any]]:
    """List compatibility API; underfilled output cannot complete a required suite."""
    result = generate_property_batch(
        exercise_id, spec_version, count=count, seed=seed, exclude_hashes=exclude_hashes,
        max_attempts=max_attempts, generation_wall_ms=generation_wall_ms,
        clock_fn=clock_fn, cancel_check_fn=cancel_check_fn,
    )
    if stats_callback is not None:
        stats_callback(result)
    return list(result.cases)
