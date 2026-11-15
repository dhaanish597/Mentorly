"""Canonical frozen domain contracts from IMPLEMENTATION_PLAN.md §5, §6, and §9."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Union
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictBool,
    StrictStr,
    BeforeValidator,
    field_serializer,
    model_validator,
)

from .enums import (
    ChallengePurpose,
    ClaimPolarity,
    ClaimType,
    ExecutionObservationKind,
    ExerciseId,
    ExtractionMethod,
    JobStatus,
    MinimizationStatus,
    PredictionStatus,
    RevealState,
    SpecVersion,
    SpeechMode,
    TraceAttributionStatus,
    TraceEventKind,
    TraceExecutionStatus,
    VerificationStatus,
)


def _raise_immutable(*_args: Any, **_kwargs: Any) -> Any:
    raise TypeError("Challenge.input_args is deeply immutable")


class _FrozenList(list[Any]):
    """List subclass that forbids all in-place mutation while remaining JSON/dict compatible."""

    __setitem__ = _raise_immutable  # type: ignore[assignment]
    __delitem__ = _raise_immutable  # type: ignore[assignment]
    append = _raise_immutable  # type: ignore[assignment]
    extend = _raise_immutable  # type: ignore[assignment]
    insert = _raise_immutable  # type: ignore[assignment]
    pop = _raise_immutable  # type: ignore[assignment]
    remove = _raise_immutable  # type: ignore[assignment]
    clear = _raise_immutable  # type: ignore[assignment]
    sort = _raise_immutable  # type: ignore[assignment]
    reverse = _raise_immutable  # type: ignore[assignment]
    __iadd__ = _raise_immutable  # type: ignore[assignment]
    __imul__ = _raise_immutable  # type: ignore[assignment]


class _FrozenDict(dict[str, Any]):
    """Dict subclass that forbids all in-place mutation while remaining JSON/Pydantic compatible."""

    __setitem__ = _raise_immutable  # type: ignore[assignment]
    __delitem__ = _raise_immutable  # type: ignore[assignment]
    pop = _raise_immutable  # type: ignore[assignment]
    popitem = _raise_immutable  # type: ignore[assignment]
    clear = _raise_immutable  # type: ignore[assignment]
    update = _raise_immutable  # type: ignore[assignment]
    setdefault = _raise_immutable  # type: ignore[assignment]
    __ior__ = _raise_immutable  # type: ignore[assignment]


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return _FrozenDict({str(k): _deep_freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return _FrozenList(_deep_freeze(item) for item in value)
    return value


def _deep_unfreeze(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _deep_unfreeze(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_deep_unfreeze(item) for item in value]
    return value


def _bounded_value(value: Any) -> Any:
    from backend.app.exercises.values import validate_value
    return validate_value(value)


BoundedInteger = Annotated[StrictInt, Field(ge=-(2**53-1), le=2**53-1)]
BoundedString = Annotated[StrictStr, Field(max_length=256)]
BoundedScalar = BoundedInteger | StrictBool | BoundedString
BoundedValue = Annotated[
    BoundedScalar | Annotated[list[BoundedScalar], Field(max_length=128)],
    BeforeValidator(_bounded_value),
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode='after')
    def _freeze_typed_outputs(self) -> '_StrictModel':
        from backend.app.exercises.values import FrozenValueList
        for field in ('predicted_output', 'confirmed_prediction', 'return_value', 'reference_output'):
            value = getattr(self, field, None)
            if type(value) is list:
                object.__setattr__(self, field, FrozenValueList(value))
        return self


class RevisionRef(_StrictModel):
    session_id: UUID
    exercise_id: ExerciseId
    spec_version: SpecVersion
    code_version_id: StrictInt = Field(ge=1)
    code_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    turn_generation: StrictInt = Field(ge=0)


class Challenge(_StrictModel):
    challenge_id: UUID
    revision: RevisionRef
    input_args: dict[str, Any]
    case_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    purpose: ChallengePurpose
    reveal_state: RevealState = RevealState.HIDDEN
    created_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def _freeze_input_args(self) -> "Challenge":
        object.__setattr__(self, "input_args", _deep_freeze(self.input_args))
        return self

    @field_serializer("input_args")
    def _serialize_input_args(self, value: dict[str, Any]) -> dict[str, Any]:
        return _deep_unfreeze(value)

    def canonical_input_copy(self) -> dict[str, Any]:
        """Return an independent deep mutable copy of input_args."""
        return _deep_unfreeze(self.input_args)

    def verify_case_hash(
        self,
        exercise_id: str | ExerciseId | None = None,
        spec_version: str | SpecVersion | None = None,
    ) -> bool:
        """Verify that input_args hashes to case_hash for the bound (or specified) exercise/spec."""
        try:
            from backend.app.exercises import registry
        except ImportError:  # pragma: no cover
            from app.exercises import registry  # type: ignore[no-redef]

        ex_id = str(exercise_id or self.revision.exercise_id)
        spec_ver = str(spec_version or self.revision.spec_version)
        try:
            computed = registry.case_key(ex_id, spec_ver, _deep_unfreeze(self.input_args))
        except Exception:
            return False
        return computed == self.case_hash


ModelAssistedClaimStatus = Literal[
    "MODEL_DISABLED",
    "MODEL_NOT_CONFIGURED",
    "MODEL_TIMEOUT",
    "MODEL_RATE_LIMITED",
    "MODEL_INVALID_RESPONSE",
    "MODEL_UNAVAILABLE",
    "MODEL_ASSISTED",
    "DETERMINISTIC_FALLBACK",
]


class _ClaimBase(_StrictModel):
    challenge_id: UUID | None = None
    critical_tokens: list[str] = Field(default_factory=list, max_length=64)
    provider_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    extraction_method: ExtractionMethod
    model_status: ModelAssistedClaimStatus | None = None
    confirmed_at: datetime | None = None


class OutputPredictionClaim(_ClaimBase):
    claim_type: Literal[ClaimType.OUTPUT_PREDICTION_AND_REASON] = (
        ClaimType.OUTPUT_PREDICTION_AND_REASON
    )
    challenge_id: UUID
    predicted_output: BoundedValue
    reason_summary: str | None = Field(default=None, max_length=1024)
    polarity: ClaimPolarity = ClaimPolarity.AFFIRMATIVE


class InvariantOrMechanismClaim(_ClaimBase):
    claim_type: Literal[ClaimType.INVARIANT_OR_MECHANISM_CLAIM] = (
        ClaimType.INVARIANT_OR_MECHANISM_CLAIM
    )
    mechanism_summary: str = Field(min_length=1, max_length=1024)
    polarity: ClaimPolarity = ClaimPolarity.AFFIRMATIVE


class DomainValidityClaim(_ClaimBase):
    claim_type: Literal[ClaimType.DOMAIN_VALIDITY_CLAIM] = ClaimType.DOMAIN_VALIDITY_CLAIM
    target_spec_version: SpecVersion
    polarity: ClaimPolarity


class ClarificationOrHintClaim(_ClaimBase):
    claim_type: Literal[ClaimType.CLARIFICATION_OR_HINT_REQUEST] = (
        ClaimType.CLARIFICATION_OR_HINT_REQUEST
    )
    question_text: str = Field(min_length=1, max_length=1024)


class UnsupportedClaim(_ClaimBase):
    claim_type: Literal[ClaimType.UNSUPPORTED_CLAIM] = ClaimType.UNSUPPORTED_CLAIM
    raw_summary: str = Field(min_length=1, max_length=1024)


ClaimInterpretation = Annotated[
    Union[
        OutputPredictionClaim,
        InvariantOrMechanismClaim,
        DomainValidityClaim,
        ClarificationOrHintClaim,
        UnsupportedClaim,
    ],
    Field(discriminator="claim_type"),
]


class ExecutionObservation(_StrictModel):
    kind: ExecutionObservationKind
    return_value: BoundedValue | None = None
    error_type: str | None = Field(default=None, max_length=128)
    error_message: str | None = Field(default=None, max_length=1024)
    stdout_excerpt: str = Field(default="", max_length=4096)
    stderr_excerpt: str = Field(default="", max_length=4096)
    duration_ms: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def _validate_return_vs_error(self) -> "ExecutionObservation":
        if self.kind == ExecutionObservationKind.RETURN:
            if self.return_value is None:
                raise ValueError("RETURN observation requires a bounded typed return_value")
        elif self.return_value is not None:
            raise ValueError("Non-RETURN observation must have return_value=None")
        return self


class HypothesisStatistics(_StrictModel):
    """Safe collector provenance; accepted candidates include boundary priority."""
    engine: Literal["hypothesis"] = "hypothesis"
    version: str = Field(min_length=1, max_length=64)
    seed: StrictInt
    requested_cases: StrictInt = Field(ge=0, le=200)
    accepted_cases: StrictInt = Field(ge=0, le=200)
    attempts: StrictInt = Field(ge=0, le=3000)
    invalid: StrictInt = Field(ge=0, le=3000)
    duplicates: StrictInt = Field(ge=0, le=3000)
    excluded: StrictInt = Field(ge=0, le=3000)
    executed_cases: StrictInt = Field(ge=0, le=200)
    max_attempts: StrictInt = Field(ge=0, le=3000)
    generation_wall_ms: StrictInt = Field(ge=0, le=300000)
    stop_reason: Literal["empty_request", "hypothesis_exhausted", "cancelled", "wall_time_limit", "attempt_limit", "target_reached"]

    @model_validator(mode="after")
    def validate_counts(self) -> "HypothesisStatistics":
        if not self.executed_cases <= self.accepted_cases <= self.requested_cases or self.attempts < self.accepted_cases:
            raise ValueError("Generation counts must reflect accepted and executed candidates")
        return self


class VerificationReport(_StrictModel):
    hypothesis_stats: HypothesisStatistics | None = None
    status: VerificationStatus
    curated_cases_run: StrictInt = Field(ge=0)
    curated_cases_total: StrictInt = Field(ge=0)
    generated_cases_run: StrictInt = Field(ge=0)
    generated_cases_target: StrictInt = Field(ge=0)
    requested_generated_cases_target: StrictInt | None = Field(default=None, ge=0)
    completed_stages: list[str] = Field(default_factory=list)
    terminal_reason: str = Field(min_length=1, max_length=256)
    seed: StrictInt | None = None
    runtime_version: str = Field(min_length=1, max_length=64)
    minimization_status: MinimizationStatus = MinimizationStatus.NOT_ATTEMPTED
    executed_case_hashes: list[str] = Field(default_factory=list, max_length=1000)
    counterexample_input: dict[str, Any] | None = None
    counterexample_case_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    student_observation: ExecutionObservation | None = None
    reference_output: BoundedValue | None = None


class TraceStep(_StrictModel):
    event_id: StrictInt = Field(ge=0)
    frame_id: str = Field(min_length=1, max_length=64)
    parent_frame_id: str | None = Field(default=None, max_length=64)
    call_depth: StrictInt = Field(ge=0)
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_line: StrictInt = Field(ge=1)
    event_kind: TraceEventKind
    attribution_status: TraceAttributionStatus
    locals_snapshot: dict[str, Any] = Field(default_factory=dict)
    truncated_values: list[str] = Field(default_factory=list)


class TraceExecutionReport(_StrictModel):
    trace_id: UUID
    revision: RevisionRef
    case_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: TraceExecutionStatus
    steps: list[TraceStep] = Field(default_factory=list, max_length=250)
    total_observed: StrictInt = Field(ge=0)
    trace_truncated: bool = False
    termination_reason: str = Field(min_length=1, max_length=256)
    observation: ExecutionObservation | None = None
    runtime_version: str = Field(min_length=1, max_length=64)


class ExecutionBudgetConfig(_StrictModel):
    """Enforced per-invocation and job budgets (§9.3)."""

    startup_deadline_ms: StrictInt = Field(default=5000, ge=500, le=30000)
    invocation_wall_ms: StrictInt = Field(default=2000, ge=100, le=10000)
    invocation_cpu_seconds: StrictInt = Field(default=2, ge=1, le=10)
    memory_limit_mb: StrictInt = Field(default=256, ge=64, le=1024)
    pids_limit: StrictInt = Field(default=16, ge=4, le=64)
    tmpfs_size_mb: StrictInt = Field(default=8, ge=1, le=64)
    max_stdout_bytes: StrictInt = Field(default=65536, ge=1024, le=262144)
    max_stderr_bytes: StrictInt = Field(default=65536, ge=1024, le=262144)
    max_result_bytes: StrictInt = Field(default=65536, ge=1024, le=262144)
    max_trace_bytes: StrictInt = Field(default=262144, ge=4096, le=1048576)
    max_trace_steps: StrictInt = Field(default=250, ge=10, le=500)
    max_trace_snapshots_work: StrictInt = Field(default=2000, ge=50, le=10000)
    job_wall_ms: StrictInt = Field(default=180000, ge=2000, le=300000)
    shrink_wall_ms: StrictInt = Field(default=20000, ge=0, le=60000)
    replay_reserve_ms: StrictInt = Field(default=10000, ge=1000, le=60000)


class ExecutionRequest(_StrictModel):
    """Single-case isolated execution request sent to the trusted broker."""

    job_id: UUID
    revision: RevisionRef
    challenge_id: UUID | None = None
    source_code: str = Field(min_length=1, max_length=65536)
    input_args: dict[str, Any]
    case_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    budget: ExecutionBudgetConfig = Field(default_factory=ExecutionBudgetConfig)


class VerifyJobRequest(_StrictModel):
    """Bounded verification request sent to the trusted broker (§5.2, §9.3)."""

    job_id: UUID
    revision: RevisionRef
    challenge_id: UUID | None = None
    source_code: str = Field(min_length=1, max_length=65536)
    prior_failing_input: dict[str, Any] | None = None
    target_input: dict[str, Any] | None = None
    run_curated_suite: bool = True
    generated_cases_target: StrictInt = Field(default=0, ge=0, le=200)
    seed: StrictInt | None = None
    budget: ExecutionBudgetConfig = Field(default_factory=ExecutionBudgetConfig)


class TraceRequest(_StrictModel):
    """Separate sandbox trace request sent to the trusted broker (§5.2, §9.4)."""

    job_id: UUID
    trace_id: UUID
    revision: RevisionRef
    challenge_id: UUID | None = None
    source_code: str = Field(min_length=1, max_length=65536)
    input_args: dict[str, Any]
    case_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    budget: ExecutionBudgetConfig = Field(default_factory=ExecutionBudgetConfig)


class JobHandle(_StrictModel):
    """Handle returned by WorkerClient/broker for job tracking and cancellation."""

    job_id: UUID
    revision: RevisionRef
    status: JobStatus
    observation: ExecutionObservation | None = None
    verification_report: VerificationReport | None = None
    trace_report: TraceExecutionReport | None = None


class EvidenceArtifact(_StrictModel):
    schema_version: str = "1.0.0"
    artifact_id: UUID
    revision: RevisionRef
    challenge_id: UUID
    canonical_input: dict[str, Any]
    case_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed_prediction: BoundedValue | None = None
    actual_observation: ExecutionObservation
    reference_output: BoundedValue
    prediction_status: PredictionStatus
    verification_report: VerificationReport
    trace_id: UUID | None = None
    minimization_status: MinimizationStatus = MinimizationStatus.NOT_ATTEMPTED
    timings_ms: dict[str, StrictInt] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _freeze_canonical_input(self) -> "EvidenceArtifact":
        object.__setattr__(self, "canonical_input", _deep_freeze(self.canonical_input))
        return self

    @field_serializer("canonical_input")
    def _serialize_canonical_input(self, value: dict[str, Any]) -> dict[str, Any]:
        return _deep_unfreeze(value)


class HiddenEvidenceArtifactView(_StrictModel):
    """Server-enforced redacted view while Challenge.reveal_state == HIDDEN."""

    schema_version: str = "1.0.0"
    artifact_id: UUID
    revision: RevisionRef
    challenge_id: UUID
    canonical_input: dict[str, Any]
    case_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    reveal_state: Literal[RevealState.HIDDEN] = RevealState.HIDDEN
    confirmed_prediction: BoundedValue | None = None
    prediction_status: PredictionStatus = PredictionStatus.NOT_EVALUATED

    @model_validator(mode="after")
    def _freeze_canonical_input(self) -> "HiddenEvidenceArtifactView":
        object.__setattr__(self, "canonical_input", _deep_freeze(self.canonical_input))
        return self

    @field_serializer("canonical_input")
    def _serialize_canonical_input(self, value: dict[str, Any]) -> dict[str, Any]:
        return _deep_unfreeze(value)


class SpeechJob(_StrictModel):
    speech_job_id: UUID
    playback_id: UUID
    revision: RevisionRef
    turn_id: UUID
    coaching_message_id: UUID
    normalized_text_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: str = Field(min_length=1, max_length=32)
    mode: SpeechMode
    audio_url: str | None = None
    expires_at: datetime


class ApiError(_StrictModel):
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=1024)
    request_id: str = Field(min_length=1, max_length=128)
    retryable: bool = False
    turn_id: UUID | None = None
    job_id: UUID | None = None
