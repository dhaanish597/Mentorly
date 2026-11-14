"""Verifier harness for Phase 1 & Phase 2 safe execution broker (§9.3, R2, R4, R8, S2 repaired).

Repairs Applied:
- R2 (Empty verification schedule rejection): When `scheduled_stages` is empty or the total
  number of scheduled cases across all stages is 0, returns `VerificationReport` with
  `status=VerificationStatus.VERIFICATION_INCOMPLETE` and
  `terminal_reason="No verification stages or cases were scheduled"` (never `NO_FAILURE_FOUND`).
- R4 (Pre-launch hash & spec binding verification): At the start of `run_verification_job`,
  validates `exercise_registry.get_spec(exercise_id, spec_version)` and verifies
  `hashlib.sha256(req.source_code.encode("utf-8")).hexdigest() == req.revision.code_hash`
  BEFORE running any stage, raising `ValueError("Code hash mismatch...")` on mismatch.
- R8 (Holdout/transfer exclusion in bounded search): `generate_bounded_cases` loads all static
  holdout cases via `exercise_registry.cases(exercise_id, spec_version, "holdout")` and adds
  their `case_key` hashes to `seen` so `generate_bounded_cases` can NEVER emit a reserved
  holdout case (such as `[-2, -3, -4]` for `ex3_max_product` with `seed=23`).
- S2 (Parent cancellation propagation during fresh replay): Checks `cancel_check_fn()` and
  `runner.is_cancelled(req.job_id)` before and after replay, and passes `job_id=req.job_id`
  to `replay_req = ExecutionRequest(job_id=req.job_id, ...)` so parent job cancellation
  reaches fresh replay containers.
"""

from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import random
import time
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.app.verification.hypothesis_strategies import GenerationBatch

try:
    from backend.app.exercises import registry as exercise_registry
    from backend.app.models.domain import (
        ExecutionObservation,
        ExecutionRequest,
        VerificationReport,
        VerifyJobRequest,
    )
    from backend.app.models.enums import (
        ExecutionObservationKind,
        MinimizationStatus,
        VerificationStatus,
    )
except ImportError:  # pragma: no cover
    from app.exercises import registry as exercise_registry  # type: ignore[no-redef]
    from app.models.domain import (  # type: ignore[no-redef]
        ExecutionObservation,
        ExecutionRequest,
        VerificationReport,
        VerifyJobRequest,
    )
    from app.models.enums import (  # type: ignore[no-redef]
        ExecutionObservationKind,
        MinimizationStatus,
        VerificationStatus,
    )

from .sandbox_runner import SandboxRunnerProtocol


def generate_bounded_cases(
    exercise_id: str,
    spec_version: str,
    count: int = 100,
    seed: int = 0,
    *,
    exclude_hashes: set[str] | None = None,
    max_attempts: int | None = None,
    generation_wall_ms: int | None = None,
    clock_fn: Callable[[], float] = time.monotonic,
    cancel_check_fn: Callable[[], bool] | None = None,
    stats_callback: Callable[[GenerationBatch], None] | None = None,
) -> list[dict[str, Any]]:
    """Use the shared seeded Hypothesis generator, never execute learner source."""
    try:
        from backend.app.verification import hypothesis_strategies as generation
    except ImportError:  # pragma: no cover
        from app.verification import hypothesis_strategies as generation

    wall_ms = generation.DEFAULT_GENERATION_WALL_MS
    if generation_wall_ms is not None:
        if type(generation_wall_ms) is not int or generation_wall_ms < 0:
            raise ValueError("generation_wall_ms must be a nonnegative strict integer")
        wall_ms = min(wall_ms, generation_wall_ms)
    return generation.generate_property_cases(
        exercise_id, spec_version, count=count, seed=seed,
        exclude_hashes=exclude_hashes, max_attempts=max_attempts,
        generation_wall_ms=wall_ms, clock_fn=clock_fn,
        cancel_check_fn=cancel_check_fn, stats_callback=stats_callback,
    )


def _is_candidate_failure(obs: ExecutionObservation, expected_output: object) -> bool:
    if obs.kind == ExecutionObservationKind.RETURN:
        return not exercise_registry.compare_output(obs.return_value, expected_output)
    return obs.kind in (
        ExecutionObservationKind.EXCEPTION,
        ExecutionObservationKind.TIMEOUT,
        ExecutionObservationKind.RESOURCE_LIMIT,
        ExecutionObservationKind.INVALID_RESULT,
    )


def _classify_replayed_failure(
    initial_obs: ExecutionObservation,
    replay_obs: ExecutionObservation,
    replay_expected: object,
) -> tuple[VerificationStatus, str]:
    """Compare initial and fresh replay observations to confirm or reject a candidate failure."""
    if replay_obs.kind == ExecutionObservationKind.RETURN and exercise_registry.compare_output(
        replay_obs.return_value, replay_expected
    ):
        return (
            VerificationStatus.REPLAY_UNCONFIRMED,
            "Candidate failure did not reproduce on fresh replay (replay matched oracle)",
        )

    if replay_obs.kind != initial_obs.kind:
        return (
            VerificationStatus.REPLAY_UNCONFIRMED,
            f"Replay observation kind ({replay_obs.kind}) disagreed with initial ({initial_obs.kind})",
        )

    if initial_obs.kind == ExecutionObservationKind.RETURN:
        if not exercise_registry.compare_output(replay_obs.return_value, initial_obs.return_value):
            return (
                VerificationStatus.REPLAY_UNCONFIRMED,
                f"Non-deterministic return value across replay ({initial_obs.return_value} vs {replay_obs.return_value})",
            )
        return (
            VerificationStatus.COUNTEREXAMPLE_CONFIRMED,
            f"Confirmed counterexample: returned {replay_obs.return_value}, expected {replay_expected}",
        )

    if initial_obs.kind == ExecutionObservationKind.EXCEPTION:
        if replay_obs.error_type != initial_obs.error_type:
            return (
                VerificationStatus.REPLAY_UNCONFIRMED,
                f"Replay exception type ({replay_obs.error_type}) disagreed with initial ({initial_obs.error_type})",
            )
        return (
            VerificationStatus.COUNTEREXAMPLE_CONFIRMED,
            f"Confirmed counterexample raising {replay_obs.error_type or 'Exception'}",
        )

    if initial_obs.kind == ExecutionObservationKind.TIMEOUT:
        return (
            VerificationStatus.TIMEOUT,
            "Confirmed reproducible timeout on fresh sandbox replay",
        )

    return (
        VerificationStatus.EXECUTION_ERROR,
        f"Confirmed reproducible execution error ({replay_obs.kind}) on fresh sandbox replay",
    )


def run_verification_job(
    req: VerifyJobRequest,
    runner: SandboxRunnerProtocol,
    *,
    clock_fn: Callable[[], float] = time.monotonic,
    cancel_check_fn: Callable[[], bool] | None = None,
) -> VerificationReport:
    """Execute bounded verification stages with trusted external oracle and fresh replay."""
    executed_hashes: set[str] = set()
    generation_batch: GenerationBatch | None = None

    def capture_batch(batch: GenerationBatch) -> None:
        nonlocal generation_batch
        generation_batch = batch

    def _report(**kwargs: Any) -> VerificationReport:
        statistics = None
        if generation_batch is not None:
            batch = generation_batch
            statistics = {
                "version": batch.hypothesis_version, "seed": batch.seed,
                "requested_cases": req.generated_cases_target, "accepted_cases": len(batch.cases),
                "attempts": batch.attempts, "invalid": batch.invalid, "duplicates": batch.duplicates,
                "excluded": batch.excluded, "executed_cases": kwargs.get("generated_cases_run", 0),
                "max_attempts": batch.max_attempts, "generation_wall_ms": batch.generation_wall_ms,
                "stop_reason": batch.stop_reason,
            }
        return VerificationReport(executed_case_hashes=sorted(executed_hashes), hypothesis_stats=statistics, **kwargs)

    start_ts = clock_fn()
    exercise_id = str(req.revision.exercise_id)
    spec_version = str(req.revision.spec_version)

    # R4: Validate spec and source_code SHA-256 against revision.code_hash BEFORE running any stage
    exercise_registry.get_spec(exercise_id, spec_version)
    actual_code_hash = hashlib.sha256(req.source_code.encode("utf-8")).hexdigest()
    if actual_code_hash != req.revision.code_hash:
        raise ValueError(
            f"Code hash mismatch: source_code hash ({actual_code_hash}) "
            f"does not match revision.code_hash ({req.revision.code_hash})"
        )

    curated_suite_cases: list[dict[str, Any]] = (
        exercise_registry.cases(exercise_id, spec_version, "curriculum")
        if req.run_curated_suite
        else []
    )
    curated_cases_total = len(curated_suite_cases)
    runtime_ver = getattr(runner, "runtime_version", None) or "runsc-phase1"

    def _elapsed_ms() -> int:
        return max(0, int((clock_fn() - start_ts) * 1000))

    def _is_cancelled() -> bool:
        if cancel_check_fn is not None and cancel_check_fn():
            return True
        runner_cancel_check = getattr(runner, "is_cancelled", None)
        if callable(runner_cancel_check) and runner_cancel_check(req.job_id):
            return True
        return False

    try:
        ast.parse(req.source_code)
    except (SyntaxError, ValueError, TypeError) as syn_exc:
        line_info = getattr(syn_exc, "lineno", None)
        msg = f"Syntax error at line {line_info}: {syn_exc}" if line_info else f"Syntax error: {syn_exc}"
        return _report(
            status=VerificationStatus.SYNTAX_ERROR,
            curated_cases_run=0,
            curated_cases_total=curated_cases_total,
            generated_cases_run=0,
            generated_cases_target=req.generated_cases_target,
            completed_stages=[],
            terminal_reason=msg[:256],
            seed=req.seed,
            runtime_version=runtime_ver[:64],
            counterexample_input=None,
            counterexample_case_hash=None,
            student_observation=None,
            reference_output=None,
        )

    scheduled_stages: list[tuple[str, list[dict[str, Any]]]] = []
    seen_hashes: set[str] = set()

    if req.prior_failing_input is not None:
        canonical_prior = exercise_registry.validate_input(
            exercise_id, spec_version, deepcopy(req.prior_failing_input)
        )
        seen_hashes.add(exercise_registry.case_key(exercise_id, spec_version, canonical_prior))
        scheduled_stages.append(("prior_failing_input", [canonical_prior]))

    if req.target_input is not None:
        canonical_target = exercise_registry.validate_input(
            exercise_id, spec_version, deepcopy(req.target_input)
        )
        seen_hashes.add(exercise_registry.case_key(exercise_id, spec_version, canonical_target))
        scheduled_stages.append(("target_input", [canonical_target]))

    if req.run_curated_suite:
        validated_curated = [
            exercise_registry.validate_input(exercise_id, spec_version, deepcopy(c))
            for c in curated_suite_cases
        ]
        for c in validated_curated:
            seen_hashes.add(exercise_registry.case_key(exercise_id, spec_version, c))
        scheduled_stages.append(("curated_suite", validated_curated))

    effective_seed = req.seed if req.seed is not None else 0
    if req.generated_cases_target > 0:
        gen_cases = generate_bounded_cases(
            exercise_id,
            spec_version,
            req.generated_cases_target,
            effective_seed,
            exclude_hashes=seen_hashes,
            generation_wall_ms=max(
                0, req.budget.job_wall_ms - req.budget.replay_reserve_ms - _elapsed_ms(),
            ),
            clock_fn=clock_fn,
            cancel_check_fn=_is_cancelled,
            stats_callback=capture_batch,
        )
        if _is_cancelled():
            return _report(
                status=VerificationStatus.SUPERSEDED,
                curated_cases_run=0,
                curated_cases_total=curated_cases_total,
                generated_cases_run=0,
                generated_cases_target=req.generated_cases_target,
                completed_stages=[],
                terminal_reason="Verification job cancelled or superseded during generation",
                seed=req.seed,
                runtime_version=runtime_ver[:64],
            )
        scheduled_stages.append(("generated_suite", gen_cases))

    total_scheduled_cases = sum(len(cases) for _, cases in scheduled_stages)
    if not scheduled_stages or total_scheduled_cases == 0:
        return _report(
            status=VerificationStatus.VERIFICATION_INCOMPLETE,
            curated_cases_run=0,
            curated_cases_total=curated_cases_total,
            generated_cases_run=0,
            generated_cases_target=req.generated_cases_target,
            completed_stages=[],
            terminal_reason="No verification stages or cases were scheduled",
            seed=req.seed,
            runtime_version=runtime_ver[:64],
            counterexample_input=None,
            counterexample_case_hash=None,
            student_observation=None,
            reference_output=None,
        )

    completed_stages: list[str] = []
    curated_cases_run = 0
    generated_cases_run = 0
    usable_wall_ms = max(0, req.budget.job_wall_ms - req.budget.replay_reserve_ms)

    for stage_name, stage_cases in scheduled_stages:
        for case_input in stage_cases:
            if _is_cancelled():
                return _report(
                    status=VerificationStatus.SUPERSEDED,
                    curated_cases_run=curated_cases_run,
                    curated_cases_total=curated_cases_total,
                    generated_cases_run=generated_cases_run,
                    generated_cases_target=req.generated_cases_target,
                    completed_stages=list(completed_stages),
                    terminal_reason="Verification job cancelled or superseded by newer revision",
                    seed=req.seed,
                    runtime_version=runtime_ver[:64],
                )

            if _elapsed_ms() >= usable_wall_ms:
                return _report(
                    status=VerificationStatus.VERIFICATION_INCOMPLETE,
                    curated_cases_run=curated_cases_run,
                    curated_cases_total=curated_cases_total,
                    generated_cases_run=generated_cases_run,
                    generated_cases_target=req.generated_cases_target,
                    completed_stages=list(completed_stages),
                    terminal_reason=(
                        f"Wall budget exhausted before completing stage {stage_name!r} "
                        f"(elapsed={_elapsed_ms()}ms, usable={usable_wall_ms}ms, "
                        f"job_wall_ms={req.budget.job_wall_ms}ms, replay_reserve_ms={req.budget.replay_reserve_ms}ms)"
                    )[:256],
                    seed=req.seed,
                    runtime_version=runtime_ver[:64],
                )

            oracle_input_copy = exercise_registry.validate_input(
                exercise_id, spec_version, deepcopy(case_input)
            )
            expected_output = exercise_registry.evaluate(
                exercise_id, spec_version, deepcopy(oracle_input_copy)
            )
            c_hash = exercise_registry.case_key(
                exercise_id, spec_version, deepcopy(oracle_input_copy)
            )

            exec_req = ExecutionRequest(
                job_id=req.job_id,
                revision=req.revision,
                challenge_id=req.challenge_id,
                source_code=req.source_code,
                input_args=deepcopy(oracle_input_copy),
                case_hash=c_hash,
                budget=req.budget,
            )
            executed_hashes.add(c_hash)
            obs = runner.execute(exec_req)
            runtime_ver = getattr(runner, "runtime_version", None) or runtime_ver

            if obs.kind == ExecutionObservationKind.UNAVAILABLE:
                return _report(
                    status=VerificationStatus.EXECUTION_UNAVAILABLE,
                    curated_cases_run=curated_cases_run,
                    curated_cases_total=curated_cases_total,
                    generated_cases_run=generated_cases_run,
                    generated_cases_target=req.generated_cases_target,
                    completed_stages=list(completed_stages),
                    terminal_reason=(
                        obs.error_message or "Sandbox runtime reported UNAVAILABLE"
                    )[:256],
                    seed=req.seed,
                    runtime_version=runtime_ver[:64],
                    student_observation=obs,
                )

            if stage_name == "curated_suite":
                curated_cases_run += 1
            elif stage_name == "generated_suite":
                generated_cases_run += 1

            if _is_candidate_failure(obs, expected_output):
                if _is_cancelled():
                    return _report(
                        status=VerificationStatus.SUPERSEDED,
                        curated_cases_run=curated_cases_run,
                        curated_cases_total=curated_cases_total,
                        generated_cases_run=generated_cases_run,
                        generated_cases_target=req.generated_cases_target,
                        completed_stages=list(completed_stages),
                        terminal_reason="Verification job cancelled or superseded before replay",
                        seed=req.seed,
                        runtime_version=runtime_ver[:64],
                    )

                if _elapsed_ms() >= req.budget.job_wall_ms:
                    return _report(
                        status=VerificationStatus.VERIFICATION_INCOMPLETE,
                        curated_cases_run=curated_cases_run,
                        curated_cases_total=curated_cases_total,
                        generated_cases_run=generated_cases_run,
                        generated_cases_target=req.generated_cases_target,
                        completed_stages=list(completed_stages),
                        terminal_reason="Job wall budget exhausted before candidate failure replay",
                        seed=req.seed,
                        runtime_version=runtime_ver[:64],
                    )

                replay_oracle_copy = exercise_registry.validate_input(
                    exercise_id, spec_version, deepcopy(oracle_input_copy)
                )
                replay_expected = exercise_registry.evaluate(
                    exercise_id, spec_version, deepcopy(replay_oracle_copy)
                )
                # A fresh container shares the parent job identity so cancellation
                # reaches every invocation; container nonces ensure isolation.
                replay_req = ExecutionRequest(
                    job_id=req.job_id,
                    revision=req.revision,
                    challenge_id=req.challenge_id,
                    source_code=req.source_code,
                    input_args=deepcopy(replay_oracle_copy),
                    case_hash=c_hash,
                    budget=req.budget,
                )
                executed_hashes.add(c_hash)
                replay_obs = runner.execute(replay_req)

                if _is_cancelled():
                    return _report(
                        status=VerificationStatus.SUPERSEDED,
                        curated_cases_run=curated_cases_run,
                        curated_cases_total=curated_cases_total,
                        generated_cases_run=generated_cases_run,
                        generated_cases_target=req.generated_cases_target,
                        completed_stages=list(completed_stages),
                        terminal_reason="Verification job cancelled or superseded during replay",
                        seed=req.seed,
                        runtime_version=runtime_ver[:64],
                    )

                if replay_obs.kind == ExecutionObservationKind.UNAVAILABLE:
                    return _report(
                        status=VerificationStatus.EXECUTION_UNAVAILABLE,
                        curated_cases_run=curated_cases_run,
                        curated_cases_total=curated_cases_total,
                        generated_cases_run=generated_cases_run,
                        generated_cases_target=req.generated_cases_target,
                        completed_stages=list(completed_stages),
                        terminal_reason=(
                            replay_obs.error_message
                            or "Sandbox runtime unavailable during replay"
                        )[:256],
                        seed=req.seed,
                        runtime_version=runtime_ver[:64],
                        student_observation=replay_obs,
                    )

                if _elapsed_ms() >= req.budget.job_wall_ms:
                    return _report(
                        status=VerificationStatus.VERIFICATION_INCOMPLETE,
                        curated_cases_run=curated_cases_run, curated_cases_total=curated_cases_total,
                        generated_cases_run=generated_cases_run, generated_cases_target=req.generated_cases_target,
                        completed_stages=list(completed_stages), terminal_reason="Job deadline exceeded during candidate replay",
                        seed=req.seed, runtime_version=runtime_ver[:64],
                    )

                ver_status, reason = _classify_replayed_failure(
                    obs, replay_obs, replay_expected
                )
                if ver_status == VerificationStatus.REPLAY_UNCONFIRMED:
                    return _report(
                        status=VerificationStatus.REPLAY_UNCONFIRMED,
                        curated_cases_run=curated_cases_run,
                        curated_cases_total=curated_cases_total,
                        generated_cases_run=generated_cases_run,
                        generated_cases_target=req.generated_cases_target,
                        completed_stages=list(completed_stages),
                        terminal_reason=reason[:256],
                        seed=req.seed,
                        runtime_version=runtime_ver[:64],
                        counterexample_input=deepcopy(replay_oracle_copy),
                        counterexample_case_hash=c_hash,
                        student_observation=replay_obs,
                        reference_output=replay_expected,
                    )

                minimization_status = MinimizationStatus.NOT_ATTEMPTED
                if ver_status == VerificationStatus.COUNTEREXAMPLE_CONFIRMED and req.budget.shrink_wall_ms > 0:
                    try:
                        from backend.app.verification.minimizer import shrink_counterexample
                    except ImportError:  # pragma: no cover
                        from app.verification.minimizer import shrink_counterexample

                    reserved = {
                        exercise_registry.case_key(exercise_id, spec_version, c)
                        for c in exercise_registry.cases(exercise_id, spec_version, "holdout")
                    }
                    observations: dict[str, ExecutionObservation] = {c_hash: replay_obs}
                    probe_stop: VerificationStatus | None = None
                    remaining_shrink_ms = min(
                        req.budget.shrink_wall_ms,
                        max(0, req.budget.job_wall_ms - _elapsed_ms() - req.budget.replay_reserve_ms),
                    )

                    def reproduces(candidate: dict[str, Any]) -> bool:
                        nonlocal probe_stop
                        if _is_cancelled():
                            probe_stop = VerificationStatus.SUPERSEDED
                            raise _ShrinkStopped()
                        if _elapsed_ms() >= req.budget.job_wall_ms - req.budget.replay_reserve_ms:
                            probe_stop = VerificationStatus.VERIFICATION_INCOMPLETE
                            raise _ShrinkStopped()
                        candidate_hash = exercise_registry.case_key(exercise_id, spec_version, candidate)
                        if candidate_hash in reserved:
                            return False
                        expected = exercise_registry.evaluate(exercise_id, spec_version, deepcopy(candidate))
                        probe_request = ExecutionRequest(
                            job_id=req.job_id, revision=req.revision, challenge_id=req.challenge_id,
                            source_code=req.source_code, input_args=deepcopy(candidate),
                            case_hash=candidate_hash, budget=req.budget,
                        )
                        executed_hashes.add(candidate_hash)
                        probe = runner.execute(probe_request)
                        if probe.kind == ExecutionObservationKind.UNAVAILABLE:
                            probe_stop = VerificationStatus.EXECUTION_UNAVAILABLE
                            raise _ShrinkStopped()
                        if _is_candidate_failure(probe, expected):
                            observations[candidate_hash] = probe
                            return True
                        return False

                    class _ShrinkStopped(Exception):
                        pass

                    try:
                        minimized, minimization_status = shrink_counterexample(
                            exercise_id, spec_version, replay_oracle_copy, reproduces,
                            shrink_wall_ms=remaining_shrink_ms, max_probes=25, clock_fn=clock_fn,
                        )
                    except _ShrinkStopped:
                        minimized = replay_oracle_copy
                        minimization_status = MinimizationStatus.BUDGET_LIMITED

                    if probe_stop in (VerificationStatus.SUPERSEDED, VerificationStatus.EXECUTION_UNAVAILABLE):
                        return _report(
                            status=probe_stop, curated_cases_run=curated_cases_run,
                            curated_cases_total=curated_cases_total, generated_cases_run=generated_cases_run,
                            generated_cases_target=req.generated_cases_target, completed_stages=list(completed_stages),
                            terminal_reason="Counterexample shrinking stopped: " + probe_stop.value,
                            seed=req.seed, runtime_version=runtime_ver[:64],
                            minimization_status=minimization_status,
                        )
                    minimized_hash = exercise_registry.case_key(exercise_id, spec_version, minimized)
                    if minimized_hash != c_hash:
                        if _is_cancelled() or _elapsed_ms() >= req.budget.job_wall_ms:
                            return _report(
                                status=VerificationStatus.SUPERSEDED if _is_cancelled() else VerificationStatus.VERIFICATION_INCOMPLETE,
                                curated_cases_run=curated_cases_run, curated_cases_total=curated_cases_total,
                                generated_cases_run=generated_cases_run, generated_cases_target=req.generated_cases_target,
                                completed_stages=list(completed_stages), terminal_reason="Shrunk candidate could not be replayed",
                                seed=req.seed, runtime_version=runtime_ver[:64], minimization_status=minimization_status,
                            )
                        minimized_expected = exercise_registry.evaluate(exercise_id, spec_version, deepcopy(minimized))
                        executed_hashes.add(minimized_hash)
                        final_obs = runner.execute(ExecutionRequest(
                            job_id=req.job_id, revision=req.revision, challenge_id=req.challenge_id,
                            source_code=req.source_code, input_args=deepcopy(minimized),
                            case_hash=minimized_hash, budget=req.budget,
                        ))
                        if _is_cancelled():
                            ver_status, reason = VerificationStatus.SUPERSEDED, "Cancelled during shrunk candidate replay"
                        elif final_obs.kind == ExecutionObservationKind.UNAVAILABLE:
                            ver_status, reason = VerificationStatus.EXECUTION_UNAVAILABLE, "Shrunk candidate replay unavailable"
                        elif _elapsed_ms() >= req.budget.job_wall_ms:
                            ver_status, reason = VerificationStatus.VERIFICATION_INCOMPLETE, "Job deadline exceeded during shrunk candidate replay"
                        else:
                            ver_status, reason = _classify_replayed_failure(observations[minimized_hash], final_obs, minimized_expected)
                        replay_oracle_copy, c_hash, replay_expected, replay_obs = minimized, minimized_hash, minimized_expected, final_obs

                return _report(
                    status=ver_status,
                    minimization_status=minimization_status,
                    curated_cases_run=curated_cases_run,
                    curated_cases_total=curated_cases_total,
                    generated_cases_run=generated_cases_run,
                    generated_cases_target=req.generated_cases_target,
                    completed_stages=list(completed_stages),
                    terminal_reason=reason[:256],
                    seed=req.seed,
                    runtime_version=runtime_ver[:64],
                    counterexample_input=deepcopy(replay_oracle_copy),
                    counterexample_case_hash=c_hash,
                    student_observation=replay_obs,
                    reference_output=replay_expected,
                )

        if _elapsed_ms() > req.budget.job_wall_ms:
            return _report(
                status=VerificationStatus.VERIFICATION_INCOMPLETE,
                curated_cases_run=curated_cases_run,
                curated_cases_total=curated_cases_total,
                generated_cases_run=generated_cases_run,
                generated_cases_target=req.generated_cases_target,
                completed_stages=list(completed_stages),
                terminal_reason=f"Job wall budget exceeded after stage {stage_name!r}",
                seed=req.seed,
                runtime_version=runtime_ver[:64],
            )
        completed_stages.append(stage_name)

    if req.generated_cases_target > 0 and generated_cases_run < req.generated_cases_target:
        return _report(
            status=VerificationStatus.VERIFICATION_INCOMPLETE,
            curated_cases_run=curated_cases_run,
            curated_cases_total=curated_cases_total,
            generated_cases_run=generated_cases_run,
            generated_cases_target=req.generated_cases_target,
            completed_stages=list(completed_stages),
            terminal_reason=(
                f"Generated only {generated_cases_run}/{req.generated_cases_target} unique legal cases"
            )[:256],
            seed=req.seed,
            runtime_version=runtime_ver[:64],
        )

    return _report(
        status=VerificationStatus.NO_FAILURE_FOUND,
        curated_cases_run=curated_cases_run,
        curated_cases_total=curated_cases_total,
        generated_cases_run=generated_cases_run,
        generated_cases_target=req.generated_cases_target,
        completed_stages=list(completed_stages),
        terminal_reason="All scheduled verification stages passed without counterexamples",
        seed=req.seed,
        runtime_version=runtime_ver[:64],
        counterexample_input=None,
        counterexample_case_hash=None,
        student_observation=None,
        reference_output=None,
    )
