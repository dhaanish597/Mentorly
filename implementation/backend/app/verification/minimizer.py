"""Deterministic structural counterexample shrinker (`backend/app/verification/minimizer.py`).

Implements Plan §9.3 / P4 (T-05):
- Preserves legal domain invariants via `registry.validate_input(exercise_id, spec_version, candidate)`.
- Shrinks in 3 deterministic stages:
  Stage A: Array length reduction toward `spec.min_length` (prefix/suffix/element removal; preserves sorted order for `ex2_binary_search` and allows empty list `[]`).
  Stage B: Element magnitude reduction toward `0` or `spec.min_value` (`1` for `v1_positive_only`).
  Stage C: Target reduction toward boundary/sum values within `spec.target_bounds`.
- Enforces `shrink_wall_ms` (default 20,000 ms) and `max_probes` (default 25) budgets.
- Returns `(minimized_input, MinimizationStatus.SHRINK_COMPLETED | MinimizationStatus.BUDGET_LIMITED)`.
"""

from __future__ import annotations

from copy import deepcopy
import time
from typing import Any, Callable

try:
    from backend.app.exercises import registry as exercise_registry
    from backend.app.models.enums import MinimizationStatus
except ImportError:  # pragma: no cover
    from app.exercises import registry as exercise_registry  # type: ignore[no-redef]
    from app.models.enums import MinimizationStatus  # type: ignore[no-redef]


def _input_complexity_key(input_args: dict[str, Any]) -> tuple[int, int, int]:
    nums = input_args.get("nums", [])
    length = len(nums) if isinstance(nums, list) else 0
    mag_sum = sum(abs(int(x)) for x in nums) if isinstance(nums, list) else 0
    target_mag = abs(int(input_args["target"])) if "target" in input_args else 0
    return (length, mag_sum, target_mag)


def _generate_length_shrink_candidates(
    exercise_id: str,
    spec_version: str,
    current_input: dict[str, Any],
) -> list[dict[str, Any]]:
    spec = exercise_registry.get_spec(exercise_id, spec_version)
    nums = list(current_input["nums"])
    n = len(nums)
    if n <= spec.min_length:
        return []

    candidates: list[dict[str, Any]] = []

    def _try_add(new_nums: list[int]) -> None:
        if len(new_nums) < spec.min_length:
            return
        cand = deepcopy(current_input)
        cand["nums"] = sorted(new_nums) if spec.sorted_required else new_nums
        try:
            validated = exercise_registry.validate_input(exercise_id, spec_version, cand)
            if validated != current_input and validated not in candidates:
                candidates.append(validated)
        except ValueError:
            return

    if spec.min_length == 0:
        _try_add([])
    if n >= 2 and spec.min_length <= 1:
        _try_add([nums[0]])
        _try_add([nums[-1]])
        _try_add([nums[n // 2]])
    if n >= 4:
        mid = n // 2
        if mid >= spec.min_length:
            _try_add(nums[:mid])
            _try_add(nums[n - mid :])
    for idx in range(n):
        _try_add(nums[:idx] + nums[idx + 1 :])
    return candidates


def _generate_magnitude_shrink_candidates(
    exercise_id: str,
    spec_version: str,
    current_input: dict[str, Any],
) -> list[dict[str, Any]]:
    spec = exercise_registry.get_spec(exercise_id, spec_version)
    nums = list(current_input["nums"])
    candidates: list[dict[str, Any]] = []
    floor_val = max(0, spec.min_value) if spec.min_value > 0 else 0

    for idx, val in enumerate(nums):
        if val == floor_val:
            continue
        trial_values: list[int] = [floor_val]
        half = int(val / 2)
        if half != val and half not in trial_values:
            trial_values.append(half)
        if val < 0 and -1 >= spec.min_value and -1 not in trial_values:
            trial_values.append(-1)
        elif val > 1 and 1 not in trial_values:
            trial_values.append(1)

        for tv in trial_values:
            if not (spec.min_value <= tv <= spec.max_value):
                continue
            if abs(tv) >= abs(val) and tv != floor_val:
                continue
            new_nums = list(nums)
            new_nums[idx] = tv
            if spec.sorted_required:
                new_nums.sort()
            cand = deepcopy(current_input)
            cand["nums"] = new_nums
            try:
                validated = exercise_registry.validate_input(exercise_id, spec_version, cand)
                if validated != current_input and validated not in candidates:
                    candidates.append(validated)
            except ValueError:
                continue
    return candidates


def _generate_target_shrink_candidates(
    exercise_id: str,
    spec_version: str,
    current_input: dict[str, Any],
) -> list[dict[str, Any]]:
    spec = exercise_registry.get_spec(exercise_id, spec_version)
    if spec.target_bounds is None or "target" not in current_input:
        return []
    lo_t, hi_t = spec.target_bounds
    cur_t = int(current_input["target"])
    nums = list(current_input["nums"])
    candidates: list[dict[str, Any]] = []

    trial_targets: list[int] = []
    if lo_t <= 1 <= hi_t:
        trial_targets.append(1)
    if lo_t <= 0 <= hi_t:
        trial_targets.append(0)
    half_t = int(cur_t / 2)
    if lo_t <= half_t <= hi_t:
        trial_targets.append(half_t)
    if nums:
        total_sum = sum(nums)
        if lo_t <= total_sum <= hi_t:
            trial_targets.append(total_sum)
        max_elem = max(nums)
        if lo_t <= max_elem <= hi_t:
            trial_targets.append(max_elem)

    for tt in trial_targets:
        if abs(tt) >= abs(cur_t) and tt not in (0, 1):
            continue
        cand = deepcopy(current_input)
        cand["target"] = tt
        try:
            validated = exercise_registry.validate_input(exercise_id, spec_version, cand)
            if validated != current_input and validated not in candidates:
                candidates.append(validated)
        except ValueError:
            continue
    return candidates


def _typed_complexity(arguments: dict[str, Any]) -> tuple[int, int]:
    def weight(value: object) -> tuple[int, int]:
        if type(value) is list:
            parts = [weight(x) for x in value]
            return len(value) + sum(p[0] for p in parts), sum(p[1] for p in parts)
        if type(value) is str:
            return len(value), sum(ord(c) for c in value)
        return 0, abs(int(value))
    parts = [weight(v) for v in arguments.values()]
    return sum(p[0] for p in parts), sum(p[1] for p in parts)


def _typed_candidates(arguments: dict, schema: dict) -> list[dict]:
    def variants(value: object, rule: dict) -> list:
        if type(value) is bool:
            return [False] if value else []
        if type(value) is int:
            floor = min(rule['maximum'], max(rule['minimum'], 0))
            return [floor, int(value / 2)]
        if type(value) is str:
            return [value[:rule['min_length']], value[:len(value)//2], value[:-1]]
        result = [value[:rule['min_length']], value[:len(value)//2]]
        result += [value[:i] + value[i+1:] for i in range(len(value))]
        for i, item in enumerate(value):
            result += [value[:i] + [replacement] + value[i+1:] for replacement in variants(item, rule['items'])]
        if rule.get('sorted_required'):
            result = [sorted(v) for v in result]
        return result
    return [{**arguments, name: value} for name, rule in schema.items() for value in variants(arguments[name], rule)]


def _shrink_typed(exercise_id: str, spec_version: str, best: dict, reproduces_failure_fn: Callable,
                  shrink_wall_ms: int, max_probes: int, clock_fn: Callable) -> tuple[dict, MinimizationStatus]:
    deadline = clock_fn() + shrink_wall_ms / 1000
    probes = 0
    schema = exercise_registry.get_spec(exercise_id, spec_version).input_schema
    while True:
        improved = False
        for candidate in _typed_candidates(best, schema):
            if clock_fn() >= deadline or probes >= max_probes:
                return deepcopy(best), MinimizationStatus.BUDGET_LIMITED
            try:
                candidate = exercise_registry.validate_input(exercise_id, spec_version, candidate)
            except ValueError:
                continue
            if _typed_complexity(candidate) >= _typed_complexity(best):
                continue
            probes += 1
            if reproduces_failure_fn(deepcopy(candidate)):
                best, improved = candidate, True
                break
        if not improved:
            return deepcopy(best), MinimizationStatus.SHRINK_COMPLETED


def shrink_counterexample(
    exercise_id: str,
    spec_version: str,
    failing_input: dict[str, Any],
    reproduces_failure_fn: Callable[[dict[str, Any]], bool],
    *,
    shrink_wall_ms: int = 20_000,
    max_probes: int = 25,
    clock_fn: Callable[[], float] = time.monotonic,
) -> tuple[dict[str, Any], MinimizationStatus]:
    """Deterministically shrink a confirmed counterexample while preserving legal domain constraints."""
    best = exercise_registry.validate_input(exercise_id, spec_version, deepcopy(failing_input))
    if shrink_wall_ms <= 0 or max_probes <= 0:
        return best, MinimizationStatus.NOT_ATTEMPTED
    if spec_version == 'v1_typed_bounded':
        return _shrink_typed(exercise_id, spec_version, best, reproduces_failure_fn, shrink_wall_ms, max_probes, clock_fn)

    start_ts = clock_fn()
    probes_used = 0
    budget_exhausted = False

    def _within_budget() -> bool:
        nonlocal budget_exhausted
        elapsed_ms = int((clock_fn() - start_ts) * 1000)
        if elapsed_ms >= shrink_wall_ms or probes_used >= max_probes:
            budget_exhausted = True
            return False
        return True

    # Stage A: Shrink array length until minimal
    improved = True
    while improved and _within_budget():
        improved = False
        for cand in _generate_length_shrink_candidates(exercise_id, spec_version, best):
            if not _within_budget():
                break
            probes_used += 1
            if reproduces_failure_fn(deepcopy(cand)):
                best = cand
                improved = True
                break

    # Stage B: Shrink element magnitudes
    improved = True
    while improved and _within_budget():
        improved = False
        for cand in _generate_magnitude_shrink_candidates(exercise_id, spec_version, best):
            if not _within_budget():
                break
            probes_used += 1
            if _input_complexity_key(cand) < _input_complexity_key(best) and reproduces_failure_fn(
                deepcopy(cand)
            ):
                best = cand
                improved = True
                break

    # Stage C: Shrink target magnitude
    for cand in _generate_target_shrink_candidates(exercise_id, spec_version, best):
        if not _within_budget():
            break
        probes_used += 1
        if reproduces_failure_fn(deepcopy(cand)):
            best = cand
            break

    status = (
        MinimizationStatus.BUDGET_LIMITED
        if budget_exhausted
        else MinimizationStatus.SHRINK_COMPLETED
    )
    return deepcopy(best), status
