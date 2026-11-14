"""Deterministic 3-Level Socratic Coaching Templates (`backend/app/coaching/templates.py`).

Implements Plan §4 / §10 / P5 (T-06):
- Graduated 3-level Socratic hints:
  - Level 1 (`HintLevel.DIAGNOSTIC_QUESTION = 1`): Socratic question grounded in the concrete counterexample input and observed vs reference output.
  - Level 2 (`HintLevel.TRACE_STEP_POINTER = 2`): Dynamically points to the exact `TraceStep` (`event_id`, `source_line`, `locals_snapshot`) where state diverges or exits prematurely.
  - Level 3 (`HintLevel.REPAIR_PRINCIPLE = 3`): Conceptual invariant repair principle without dumping full copy-paste solution code.
- Supports all 3 canonical exercises (`ex1_shortest_subarray`, `ex2_binary_search`, `ex3_max_product`) and all learning states.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from backend.app.models.domain import (
        EvidenceArtifact,
        TraceExecutionReport,
        TraceStep,
    )
    from backend.app.models.enums import (
        ExerciseId,
        HintLevel,
        LearningState,
        PredictionStatus,
        SpecVersion,
        TraceAttributionStatus,
        VerificationStatus,
    )
except ImportError:  # pragma: no cover
    from app.models.domain import EvidenceArtifact, TraceExecutionReport, TraceStep  # type: ignore[no-redef]
    from app.models.enums import (  # type: ignore[no-redef]
        ExerciseId,
        HintLevel,
        LearningState,
        PredictionStatus,
        SpecVersion,
        TraceAttributionStatus,
        VerificationStatus,
    )


@dataclass(frozen=True)
class CoachingHintPrompt:
    hint_level: HintLevel
    display_text: str
    pointed_event_id: int | None
    pointed_line: int | None
    source_mode: str = "DETERMINISTIC_TEMPLATE"


def find_divergence_trace_step(
    trace_report: TraceExecutionReport | None,
) -> TraceStep | None:
    """Select the most informative attributed post-line `TraceStep` from a trace report."""
    if trace_report is None or not trace_report.steps:
        return None
    attributed = [
        s
        for s in trace_report.steps
        if s.attribution_status == TraceAttributionStatus.ATTRIBUTED
    ]
    if not attributed:
        return None
    pool = attributed
    # Prefer the step right before RETURN or at the deepest loop update
    non_call = [s for s in pool if str(s.event_kind) in ("LINE", "RETURN", "EXCEPTION")]
    if len(non_call) >= 2:
        return non_call[-2]
    return pool[-1]


def render_deterministic_hint(
    artifact: EvidenceArtifact,
    *,
    hint_level: HintLevel = HintLevel.DIAGNOSTIC_QUESTION,
    trace_report: TraceExecutionReport | None = None,
    learning_state: LearningState = LearningState.REPAIR_REQUIRED,
) -> CoachingHintPrompt:
    """Render a 100% deterministic, evidence-grounded coaching prompt without external LLM dependency."""
    ex_id = artifact.revision.exercise_id
    spec_ver = artifact.revision.spec_version
    inp = artifact.canonical_input
    obs = artifact.actual_observation
    ref_out = artifact.reference_output

    if artifact.prediction_status == PredictionStatus.NOT_EVALUATED and obs.kind.value == "UNAVAILABLE":
        return CoachingHintPrompt(
            hint_level=hint_level,
            display_text=(
                "Execution could not be completed, so your prediction has not been evaluated. "
                f"Verification status: {artifact.verification_report.status.value}. "
                "Keep your current code and prediction; retry when isolated execution is available."
            ),
            pointed_event_id=None,
            pointed_line=None,
        )

    if obs.kind.value not in ("RETURN", "UNAVAILABLE"):
        questions = {
            HintLevel.DIAGNOSTIC_QUESTION: "Which operation could cause this observed outcome on the revealed input?",
            HintLevel.TRACE_STEP_POINTER: "Inspect the reported exception and any available attributed trace step; a precise cause is not established by this record alone.",
            HintLevel.REPAIR_PRINCIPLE: "Propose one bounded change addressing the observed failure, then verify it; a timeout alone does not prove a particular bug.",
        }
        return CoachingHintPrompt(
            hint_level=hint_level,
            display_text=f"Execution reported {obs.kind.value} ({obs.error_type or 'no exception type reported'}). Your numerical prediction remains unevaluated. {questions[hint_level]}",
            pointed_event_id=None,
            pointed_line=None,
        )

    if learning_state == LearningState.PRACTICE_CHECKPOINT_COMPLETED:
        return CoachingHintPrompt(
            hint_level=hint_level,
            display_text=(
                f"Practice checkpoint completed for {ex_id.value} ({spec_ver.value}). "
                f"Your prediction and implementation both matched {ref_out} on the held-out transfer input {inp}."
            ),
            pointed_event_id=None,
            pointed_line=None,
        )

    if learning_state == LearningState.FRESH_CASE_CHECK:
        return CoachingHintPrompt(
            hint_level=hint_level,
            display_text=(
                f"Your code passed bounded verification ({artifact.verification_report.curated_cases_run} curated "
                f"and {artifact.verification_report.generated_cases_run} generated cases) and your prediction matched {ref_out}. "
                f"Now predict the output on a fresh held-out transfer case to complete this practice checkpoint."
            ),
            pointed_event_id=None,
            pointed_line=None,
        )

    if learning_state == LearningState.PREDICTION_REVIEW:
        return CoachingHintPrompt(
            hint_level=hint_level,
            display_text=(
                f"Your code returned the expected value {ref_out} on {inp}, "
                f"but you predicted {artifact.confirmed_prediction}. "
                f"Walk through how the loop state updates on {inp} and explain why the return value is {ref_out}."
            ),
            pointed_event_id=None,
            pointed_line=None,
        )

    observed_desc = (
        f"returned {obs.return_value}"
        if obs.return_value is not None
        else f"terminated with {obs.error_type or obs.kind.value}"
    )
    step = find_divergence_trace_step(trace_report)

    if hint_level == HintLevel.DIAGNOSTIC_QUESTION:
        if ex_id == ExerciseId.EX1_SHORTEST_SUBARRAY:
            if spec_ver == SpecVersion.EX1_V2_NEGATIVES_ALLOWED:
                q = (
                    f"On input {inp}, your code {observed_desc}, whereas the shortest subarray with sum >= "
                    f"{inp.get('target')} has length {ref_out}. When nums contains a negative number, "
                    f"is curr_sum still guaranteed to increase monotonically as right advances?"
                )
            else:
                q = (
                    f"On input {inp}, your code {observed_desc}, but the expected shortest length is {ref_out}. "
                    f"When curr_sum reaches {inp.get('target')}, how does your inner loop update best and shrink left?"
                )
        elif ex_id == ExerciseId.EX2_BINARY_SEARCH:
            q = (
                f"On input {inp}, your code {observed_desc}, while the first index with value >= "
                f"{inp.get('target')} is {ref_out}. When nums[mid] equals or exceeds target, "
                f"which half of the search range could still contain an earlier matching index?"
            )
        elif ex_id == ExerciseId.EX3_MAX_PRODUCT:
            q = (
                f"On input {inp}, your code {observed_desc}, while the maximum contiguous subarray product is {ref_out}. "
                f"When a negative number multiplies the previous minimum product, how should your running max and min update?"
            )
        else:
            from backend.app.exercises.registry import hints
            q = f'On input {inp}, your code {observed_desc}; the expected result is {ref_out}. ' + hints(ex_id.value)['1']
        return CoachingHintPrompt(
            hint_level=HintLevel.DIAGNOSTIC_QUESTION,
            display_text=q,
            pointed_event_id=None,
            pointed_line=None,
        )

    if hint_level == HintLevel.TRACE_STEP_POINTER:
        if step is not None:
            locals_preview = ", ".join(
                f"{k}={v}" for k, v in list(step.locals_snapshot.items())[:5]
            )
            text = (
                f"Inspect trace step #{step.event_id} after line {step.source_line} on input {inp}, "
                f"where locals are {{{locals_preview}}}. Compare that state against what is needed to reach {ref_out}."
            )
            return CoachingHintPrompt(
                hint_level=HintLevel.TRACE_STEP_POINTER,
                display_text=text,
                pointed_event_id=step.event_id,
                pointed_line=step.source_line,
            )
        return CoachingHintPrompt(
            hint_level=HintLevel.TRACE_STEP_POINTER,
            display_text=(
                f"Trace capture is unavailable or partial for {inp} ({observed_desc} vs expected {ref_out}). "
                f"Check the loop condition and accumulator update right before the return statement."
            ),
            pointed_event_id=None,
            pointed_line=None,
        )

    # Level 3: REPAIR_PRINCIPLE
    if ex_id == ExerciseId.EX1_SHORTEST_SUBARRAY:
        if spec_ver == SpecVersion.EX1_V2_NEGATIVES_ALLOWED:
            principle = (
                f"Repair Principle: Because negative values in {inp} break sliding-window monotonicity, "
                f"maintain prefix sums P[i] and a monotonic increasing deque of candidate start indices "
                f"so you can pop any front index where P[right] - P[front] >= target and pop any back index with P[back] >= P[right]."
            )
        else:
            principle = (
                f"Repair Principle: For positive integers on {inp}, advance right to add nums[right] to curr_sum, "
                f"and while curr_sum >= target, record min(best, right - left + 1) before subtracting nums[left] and incrementing left."
            )
    elif ex_id == ExerciseId.EX2_BINARY_SEARCH:
        principle = (
            f"Repair Principle: Initialize ans = -1, left = 0, right = len(nums) - 1. "
            f"Whenever nums[mid] >= target on {inp}, record ans = mid and set right = mid - 1 to keep searching left for an earlier duplicate; "
            f"otherwise set left = mid + 1."
        )
    elif ex_id == ExerciseId.EX3_MAX_PRODUCT:
        principle = (
            f"Repair Principle: On {inp}, update both running extrema simultaneously in a tuple assignment — "
            f"hi, lo = max(x, hi * x, lo * x), min(x, hi * x, lo * x) — so multiplying by a negative x uses the unmutated prior hi."
        )

    else:
        from backend.app.exercises.registry import hints
        principle = 'Repair Principle: ' + hints(ex_id.value)['3']
    return CoachingHintPrompt(
        hint_level=HintLevel.REPAIR_PRINCIPLE,
        display_text=principle,
        pointed_event_id=step.event_id if step else None,
        pointed_line=step.source_line if step else None,
    )
