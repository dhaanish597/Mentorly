"""Canonical API request, response, and Phase 2 speech DTOs from IMPLEMENTATION_PLAN.md §6.2 & §8."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from .domain import BoundedValue, Challenge, ClaimInterpretation, EvidenceArtifact, RevisionRef
from .enums import (
    ChallengePurpose,
    ExerciseId,
    HintLevel,
    InteractionMode,
    JobStatus,
    LanguageMode,
    LearningState,
    PlaybackStatus,
    SessionState,
    SpecVersion,
    SpeechDegradationStatus,
)


class _StrictDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(_StrictDTO):
    status: Literal["ok"]
    service: str
    phase: str
    version: str
    custom_code_execution_enabled: bool
    execution_status: Literal["DISABLED", "BLOCKED_EXTERNAL", "READY"] = "DISABLED"
    product_name: str
    product_name_status: str


class BrandingResponse(_StrictDTO):
    productName: str
    productNameStatus: str
    shortName: str
    tagline: str


class ValueSchema(_StrictDTO):
    kind: Literal['integer', 'boolean', 'string', 'list']
    minimum: StrictInt | None = None
    maximum: StrictInt | None = None
    min_length: StrictInt | None = None
    max_length: StrictInt | None = None
    items: ValueSchema | None = None
    sorted_required: bool = False


class ExerciseExample(_StrictDTO):
    input_args: dict[str, Any]
    output: BoundedValue
    explanation: str


class CatalogProvenance(_StrictDTO):
    source: Literal['original'] = 'original'
    status: Literal['ORIGINAL_AUTHORED'] = 'ORIGINAL_AUTHORED'
    license: str | None = None


class ExerciseSpecMetadata(_StrictDTO):
    spec_version: str
    label: str
    min_length: StrictInt
    max_length: StrictInt
    min_value: StrictInt
    max_value: StrictInt
    target_bounds: tuple[StrictInt, StrictInt] | None = None
    sorted_required: bool
    constraints_summary: list[str]
    input_schema: dict[str, ValueSchema] = Field(default_factory=dict)
    output_schema: ValueSchema | None = None
    recommended_generated_cases: StrictInt = 20
    available_fresh_cases: StrictInt = 2


class ExerciseMetadata(_StrictDTO):
    exercise_id: str
    title: str
    function_name: str
    difficulty: Literal["beginner", "intermediate", "advanced"]
    core_concepts: list[str]
    description: str
    starter_code: str
    default_spec_version: str
    spec_versions: list[ExerciseSpecMetadata]
    input_schema: dict[str, ValueSchema] = Field(default_factory=dict)
    output_schema: ValueSchema | None = None
    examples: list[ExerciseExample] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    collection: str = 'Original Coaching Collection'
    comparator: Literal['strict_structural'] = 'strict_structural'
    catalog_status: Literal['READY'] = 'READY'
    provenance: CatalogProvenance = Field(default_factory=CatalogProvenance)


class DemoPresetMetadata(_StrictDTO):
    preset_id: str
    title: str
    exercise_id: str
    spec_version: str
    language_mode: Literal["en-IN", "ta-IN,en-IN"]
    provenance_label: Literal["RECORDED_DEMO", "LIVE_SESSION"]
    description: str
    starter_code: str


class CreateSessionRequest(_StrictDTO):
    exercise_id: ExerciseId
    spec_version: SpecVersion
    language_mode: LanguageMode = LanguageMode.EN_IN
    interaction_mode: InteractionMode = InteractionMode.VOICE


class CreateSessionResponse(_StrictDTO):
    session_id: UUID
    session_token: str = Field(min_length=32)
    starter_code: str
    revision: RevisionRef
    state: SessionState
    learning_state: LearningState
    spec_acknowledged: bool


class CodeUpdateRequest(_StrictDTO):
    code: str = Field(max_length=65536)
    expected_code_version_id: StrictInt = Field(ge=1)
    client_edit_sequence: StrictInt = Field(ge=1)


class CodeUpdateResponse(_StrictDTO):
    revision: RevisionRef
    changed: bool
    ast_symbols: list[str] = Field(default_factory=list)
    syntax_error: str | None = None


class SpecUpdateRequest(_StrictDTO):
    target_spec_version: SpecVersion
    expected_revision: RevisionRef


class SpecAckRequest(_StrictDTO):
    spec_version: SpecVersion
    revision: RevisionRef


class CreateChallengeRequest(_StrictDTO):
    purpose: ChallengePurpose
    revision: RevisionRef
    requested_input: dict[str, Any] | None = None


class TextTurnRequest(_StrictDTO):
    text: str = Field(min_length=1, max_length=8192)
    revision: RevisionRef
    challenge_id: UUID | None = None


class ConfirmClaimRequest(_StrictDTO):
    challenge_id: UUID | None = None
    revision: RevisionRef
    capture_attempt_id: StrictInt | None = Field(default=None, ge=1)
    claim: ClaimInterpretation


class VerifyRequest(_StrictDTO):
    revision: RevisionRef
    prior_artifact_id: UUID | None = None
    run_curated_suite: bool = True
    generated_cases_target: StrictInt = Field(default=20, ge=0, le=100)


class RetryExecutionRequest(_StrictDTO):
    revision: RevisionRef


class FreshCaseCheckRequest(_StrictDTO):
    challenge_id: UUID
    revision: RevisionRef
    confirmed_prediction: BoundedValue


class HintRequest(_StrictDTO):
    artifact_id: UUID
    requested_level: HintLevel
    revision: RevisionRef


class PlaybackAckRequest(_StrictDTO):
    playback_id: UUID
    revision: RevisionRef
    playback_status: PlaybackStatus
    played_duration_ms: StrictInt = Field(ge=0)


class CancelRequest(_StrictDTO):
    scope: Literal["INTERRUPT", "TURN"] = "INTERRUPT"
    turn_id: UUID | None = None
    job_id: UUID | None = None
    playback_id: UUID | None = None
    reason: str = Field(min_length=1, max_length=256)


class CancelResponse(_StrictDTO):
    unconfirmed_job_ids: list[UUID] = Field(default_factory=list)
    cancelled_turn_ids: list[UUID] = Field(default_factory=list)
    cancelled_job_ids: list[UUID] = Field(default_factory=list)
    cancelled_playback_ids: list[UUID] = Field(default_factory=list)


class JobAcceptedResponse(_StrictDTO):
    job_id: UUID
    turn_id: UUID | None = None
    status: JobStatus = JobStatus.QUEUED


class JobStatusResponse(_StrictDTO):
    job_id: UUID
    status: JobStatus
    result: dict[str, Any] | None = None
    error_code: str | None = None


class OperationsReadinessResponse(_StrictDTO):
    status: Literal["READY", "BLOCKED_EXTERNAL"]
    checked_at: datetime
    database_ready: bool
    execution_ready: bool
    canary_status: Literal["NOT_RUN", "PASSED", "FAILED"]
    canary_duration_ms: StrictInt | None = Field(default=None, ge=0)
    speech_status: Literal["UNAVAILABLE", "CONFIGURED_UNVERIFIED"]


class CapacityResponse(_StrictDTO):
    speech_queue_depth: StrictInt = Field(ge=0)
    custom_code_execution_enabled: bool
    mode: Literal["LIVE", "CACHED", "DEMO"]


class SessionExportResponse(_StrictDTO):
    export_version: str = "1.0.0"
    exported_at: datetime
    session_id: UUID
    revision: RevisionRef
    challenges: list[Challenge] = Field(default_factory=list)
    evidence_artifacts: list[EvidenceArtifact] = Field(default_factory=list)


class DeleteSessionResponse(_StrictDTO):
    session_id: UUID
    deleted_at: datetime
    limitations: str


# ---------------------------------------------------------------------------
# Phase 2 (T-03): Voice Foundation Speech DTOs (§8.1 - §8.6)
# ---------------------------------------------------------------------------


class STTRequest(_StrictDTO):
    """Outbound Gnani REST/WS STT request contract bound to session/turn/capture."""

    session_id: str = Field(min_length=1, max_length=128)
    turn_generation: StrictInt = Field(default=1, ge=0)
    capture_attempt_id: StrictInt = Field(default=1, ge=1)
    revision: RevisionRef | None = None
    exercise_id: ExerciseId = ExerciseId.EX1_SHORTEST_SUBARRAY
    spec_version: SpecVersion = SpecVersion.EX1_V1_POSITIVE_ONLY
    language_mode: LanguageMode = LanguageMode.EN_IN
    source_code: str = Field(default="", max_length=65536)
    previous_audio_transcript: str | None = Field(default=None, max_length=600)
    topic_override: str | None = Field(default=None, max_length=1600)
    request_id: str = Field(default="", max_length=128)

    @property
    def topic_Override(self) -> str | None:
        return self.topic_override


class STTResult(_StrictDTO):
    """Validated Gnani STT response separating client correlation ID from provider ID."""

    request_id: str = Field(min_length=1, max_length=128)
    client_request_id: str = Field(min_length=1, max_length=128)
    provider_request_id: str | None = Field(default=None, max_length=128)
    configured_model: str = "prisma-v3.0"
    provider_model: str | None = None
    truncated: bool = False
    transport: Literal["REST_V3", "WS_V3"] = "REST_V3"
    language_mode: LanguageMode
    observed_format: Literal["transcribe", "codemix"]
    raw_transcript: str = Field(max_length=4000)
    normalized_transcript: str = Field(max_length=4000)
    normalization_notes: list[str] = Field(default_factory=list)
    contains_self_correction: bool = False
    requires_confirmation: bool = True
    provider_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    detected_language_code: str | None = Field(default=None, max_length=32)
    audio_duration_sec: float = Field(ge=0.0, le=30.0)
    low_energy_warning: bool = False
    latency_ms: StrictInt = Field(ge=0)


class TTSAudioConfig(_StrictDTO):
    """Canonical Gnani SSE TTS nested audio_config payload (§8.4)."""

    encoding: Literal["linear_pcm"] = "linear_pcm"
    container: Literal["raw", "wav"] = "raw"
    sample_rate: StrictInt = Field(default=22050, ge=8000, le=48000)
    num_channels: StrictInt = Field(default=1, ge=1, le=1)
    sample_width: StrictInt = Field(default=2, ge=2, le=2)


class TTSRequest(_StrictDTO):
    """Outbound Gnani SSE TTS synthesis request contract bound to session/turn/playback."""

    session_id: str = Field(min_length=1, max_length=128)
    turn_generation: StrictInt = Field(default=1, ge=0)
    turn_id: str | None = Field(default=None, max_length=128)
    playback_id: str | None = Field(default=None, max_length=128)
    revision: RevisionRef | None = None
    text: str = Field(min_length=1, max_length=8000)
    model: str = Field(default="timbre-v3.0", min_length=1, max_length=64)
    voice: str = Field(default="Avinash", min_length=1, max_length=64)
    language: str = Field(default="en-IN", min_length=2, max_length=32)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    audio_config: TTSAudioConfig = Field(default_factory=TTSAudioConfig)
    cache_scope: Literal["PUBLIC_GENERIC", "SESSION_SCOPED"] = "SESSION_SCOPED"
    request_id: str = Field(default="", max_length=128)


class AudioEvent(_StrictDTO):
    """Incremental or complete Gnani SSE TTS event."""

    event_type: Literal["start", "chunk", "complete", "error"]
    request_id: str = Field(min_length=1, max_length=128)
    client_request_id: str | None = Field(default=None, max_length=128)
    provider_request_id: str | None = Field(default=None, max_length=128)
    playback_id: str | None = Field(default=None, max_length=128)
    segment_index: StrictInt = Field(default=0, ge=0)
    chunk_index: StrictInt | None = Field(default=None, ge=0)
    audio_b64: str | None = None
    wav_bytes_b64: str | None = None
    sample_rate: StrictInt = Field(default=22050, ge=8000, le=48000)
    duration_ms: StrictInt | None = Field(default=None, ge=0)
    cache_hit: bool = False
    error_code: str | None = Field(default=None, max_length=64)
    error_message: str | None = Field(default=None, max_length=512)


class SpeechCapacityStatus(_StrictDTO):
    """Single-dispatcher speech capacity and durable usage ledger snapshot (§8.6)."""

    deployment_topology: Literal["SINGLE_PROCESS_LOCAL_SEMAPHORE"] = (
        "SINGLE_PROCESS_LOCAL_SEMAPHORE"
    )
    max_concurrency: StrictInt = Field(default=1, ge=1, le=1)
    active_requests: StrictInt = Field(ge=0)
    queued_requests: StrictInt = Field(ge=0)
    max_waiting: StrictInt = Field(ge=1)
    degradation_status: SpeechDegradationStatus = SpeechDegradationStatus.HEALTHY
    stt_seconds_used: float = Field(ge=0.0)
    stt_seconds_reserved: float = Field(default=0.0, ge=0.0)
    stt_seconds_uncertain: float = Field(default=0.0, ge=0.0)
    tts_chars_used: StrictInt = Field(ge=0)
    tts_chars_reserved: StrictInt = Field(default=0, ge=0)
    tts_chars_uncertain: StrictInt = Field(default=0, ge=0)
    stt_requests_count: StrictInt = Field(ge=0)
    tts_requests_count: StrictInt = Field(ge=0)
    uncertain_requests_count: StrictInt = Field(default=0, ge=0)
    credit_remaining_status: str = "UNKNOWN_UNVERIFIED_TARIFF"


class VoicePlaybackAckRequest(_StrictDTO):
    """Browser audio playback completion/interruption/fallback acknowledgement."""

    playback_id: str = Field(default="", max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    turn_id: str = Field(min_length=1, max_length=128)
    turn_generation: StrictInt = Field(ge=0)
    revision: RevisionRef | None = None
    playback_status: PlaybackStatus
    played_duration_ms: StrictInt = Field(ge=0)


class VoicePlaybackAckResponse(_StrictDTO):
    playback_id: str = Field(default="", max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    turn_id: str = Field(min_length=1, max_length=128)
    turn_generation: StrictInt = Field(ge=0)
    playback_status: PlaybackStatus
    acknowledged: bool = True


class TTSPlaybackRequest(_StrictDTO):
    revision: RevisionRef
    artifact_id: UUID
    hint_level: HintLevel = HintLevel.DIAGNOSTIC_QUESTION
