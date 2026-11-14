"""Unit tests for frozen Phase 0, Phase 1, and Phase 2 Pydantic contracts and strict validation."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError
import pytest

from backend.app.exercises import registry
from backend.app.models.api_schemas import (
    AudioEvent,
    CodeUpdateRequest,
    ConfirmClaimRequest,
    FreshCaseCheckRequest,
    SpeechCapacityStatus,
    STTRequest,
    STTResult,
    TTSRequest,
    VoicePlaybackAckRequest,
)
from backend.app.models.domain import (
    Challenge,
    ClaimInterpretation,
    EvidenceArtifact,
    ExecutionBudgetConfig,
    ExecutionObservation,
    ExecutionRequest,
    HiddenEvidenceArtifactView,
    JobHandle,
    OutputPredictionClaim,
    RevisionRef,
    TraceExecutionReport,
    TraceRequest,
    TraceStep,
    VerificationReport,
    VerifyJobRequest,
)
from backend.app.models.enums import (
    ChallengePurpose,
    ClaimPolarity,
    ExecutionObservationKind,
    ExerciseId,
    ExtractionMethod,
    JobStatus,
    LanguageMode,
    PlaybackStatus,
    PredictionStatus,
    RevealState,
    SpecVersion,
    SpeechDegradationStatus,
    TraceAttributionStatus,
    TraceEventKind,
    TraceExecutionStatus,
    VerificationStatus,
)

_NOW = datetime.now(timezone.utc)
_HASH = "a" * 64


def _sample_revision() -> RevisionRef:
    return RevisionRef(
        session_id=uuid4(),
        exercise_id=ExerciseId.EX1_SHORTEST_SUBARRAY,
        spec_version=SpecVersion.EX1_V2_NEGATIVES_ALLOWED,
        code_version_id=2,
        code_hash=_HASH,
        turn_generation=1,
    )


def test_claim_discriminated_union_accepts_valid_and_rejects_bool_predicted_output() -> None:
    adapter = TypeAdapter(ClaimInterpretation)
    cid = uuid4()
    valid = adapter.validate_python(
        {
            "claim_type": "OUTPUT_PREDICTION_AND_REASON",
            "challenge_id": str(cid),
            "predicted_output": 1,
            "reason_summary": "Window shrinks to [5]",
            "polarity": "AFFIRMATIVE",
            "critical_tokens": ["nums=[1,-1,5]", "target=5", "1"],
            "provider_confidence": None,
            "extraction_method": "DETERMINISTIC",
            "confirmed_at": _NOW.isoformat(),
        }
    )
    assert isinstance(valid, OutputPredictionClaim)
    assert valid.predicted_output == 1
    assert valid.provider_confidence is None

    with pytest.raises(ValidationError):
        adapter.validate_python(
            {
                "claim_type": "OUTPUT_PREDICTION_AND_REASON",
                "challenge_id": str(cid),
                "predicted_output": 1.5,
                "extraction_method": "DETERMINISTIC",
            }
        )


def test_execution_observation_enforces_return_vs_timeout_invariants() -> None:
    obs_ok = ExecutionObservation(
        kind=ExecutionObservationKind.RETURN,
        return_value=3,
        duration_ms=12,
    )
    assert obs_ok.return_value == 3

    obs_timeout = ExecutionObservation(
        kind=ExecutionObservationKind.TIMEOUT,
        return_value=None,
        error_type="TimeoutError",
        error_message="Exceeded 2000ms wall limit",
        duration_ms=2000,
    )
    assert obs_timeout.return_value is None

    with pytest.raises(ValidationError):
        ExecutionObservation(
            kind=ExecutionObservationKind.RETURN,
            return_value=None,
            duration_ms=5,
        )

    with pytest.raises(ValidationError):
        ExecutionObservation(
            kind=ExecutionObservationKind.TIMEOUT,
            return_value=0,
            duration_ms=2000,
        )


def test_evidence_artifact_and_hidden_view_separation() -> None:
    rev = _sample_revision()
    cid = uuid4()
    report = VerificationReport(
        status=VerificationStatus.VERIFICATION_INCOMPLETE,
        curated_cases_run=5,
        curated_cases_total=5,
        generated_cases_run=40,
        generated_cases_target=100,
        completed_stages=["curated"],
        terminal_reason="Job wall budget reached",
        seed=42,
        runtime_version="3.11",
    )
    artifact = EvidenceArtifact(
        artifact_id=uuid4(),
        revision=rev,
        challenge_id=cid,
        canonical_input={"nums": [1, -1, 5], "target": 5},
        case_hash=_HASH,
        confirmed_prediction=1,
        actual_observation=ExecutionObservation(
            kind=ExecutionObservationKind.RETURN,
            return_value=3,
            duration_ms=8,
        ),
        reference_output=1,
        prediction_status=PredictionStatus.MATCH,
        verification_report=report,
    )
    assert artifact.prediction_status == PredictionStatus.MATCH
    assert artifact.verification_report.status == VerificationStatus.VERIFICATION_INCOMPLETE

    hidden = HiddenEvidenceArtifactView(
        artifact_id=artifact.artifact_id,
        revision=rev,
        challenge_id=cid,
        canonical_input=artifact.canonical_input,
        case_hash=_HASH,
        confirmed_prediction=1,
    )
    dumped = hidden.model_dump()
    assert dumped["reveal_state"] == RevealState.HIDDEN
    assert "actual_observation" not in dumped
    assert "reference_output" not in dumped


def test_challenge_deep_immutability_and_hash_verification() -> None:
    rev = _sample_revision()
    raw_args = {"nums": [1, -1, 5], "target": 5}
    c_hash = registry.case_key(
        str(rev.exercise_id), str(rev.spec_version), raw_args
    )
    chal = Challenge(
        challenge_id=uuid4(),
        revision=rev,
        input_args=raw_args,
        case_hash=c_hash,
        purpose=ChallengePurpose.DIAGNOSTIC,
        created_at=_NOW,
        expires_at=_NOW + timedelta(hours=1),
    )
    raw_args["nums"].append(999)
    raw_args["target"] = 42
    assert list(chal.input_args["nums"]) == [1, -1, 5]
    assert chal.input_args["target"] == 5

    with pytest.raises(TypeError):
        chal.input_args["target"] = 99
    with pytest.raises(TypeError):
        chal.input_args["nums"][0] = 77
    with pytest.raises(TypeError):
        chal.input_args["nums"].append(88)

    assert chal.verify_case_hash() is True


def test_request_dtos_reject_extra_fields_and_booleans() -> None:
    rev = _sample_revision()
    with pytest.raises(ValidationError):
        CodeUpdateRequest(
            code="def f(): pass",
            expected_code_version_id=True,  # type: ignore[arg-type]
            client_edit_sequence=1,
        )
    with pytest.raises(ValidationError):
        FreshCaseCheckRequest(
            challenge_id=uuid4(),
            revision=rev,
            confirmed_prediction=1,
            unexpected_field="nope",  # type: ignore[call-arg]
        )
    claim = OutputPredictionClaim(
        challenge_id=uuid4(),
        predicted_output=9,
        polarity=ClaimPolarity.AFFIRMATIVE,
        extraction_method=ExtractionMethod.USER_EDITED,
    )
    confirm = ConfirmClaimRequest(
        challenge_id=claim.challenge_id,
        revision=rev,
        claim=claim,
    )
    assert confirm.claim.claim_type == "OUTPUT_PREDICTION_AND_REASON"


def test_phase1_and_phase2_contracts_validate_strictly() -> None:
    rev = _sample_revision()
    exec_req = ExecutionRequest(
        job_id=uuid4(),
        revision=rev,
        source_code="def shortest_subarray_ge_target(nums, target):\n    return 1\n",
        input_args={"nums": [1, -1, 5], "target": 5},
        case_hash=_HASH,
        budget=ExecutionBudgetConfig(),
    )
    verify_req = VerifyJobRequest(
        job_id=uuid4(),
        revision=rev,
        source_code=exec_req.source_code,
        generated_cases_target=50,
    )
    trace_req = TraceRequest(
        job_id=uuid4(),
        trace_id=uuid4(),
        revision=rev,
        source_code=exec_req.source_code,
        input_args={"nums": [1, -1, 5], "target": 5},
        case_hash=_HASH,
    )
    step = TraceStep(
        event_id=0,
        frame_id="f1",
        parent_frame_id=None,
        call_depth=1,
        source_hash=_HASH,
        source_line=2,
        event_kind=TraceEventKind.LINE,
        attribution_status=TraceAttributionStatus.ATTRIBUTED,
        locals_snapshot={"target": 5},
        truncated_values=[],
    )
    t_report = TraceExecutionReport(
        trace_id=trace_req.trace_id,
        revision=rev,
        case_hash=_HASH,
        status=TraceExecutionStatus.COMPLETED,
        steps=[step],
        total_observed=1,
        trace_truncated=False,
        termination_reason="Completed",
        runtime_version="runsc-1.0",
    )
    handle = JobHandle(
        job_id=verify_req.job_id,
        revision=rev,
        status=JobStatus.COMPLETE,
        trace_report=t_report,
    )
    assert handle.status == JobStatus.COMPLETE

    stt_req = STTRequest(
        session_id=str(rev.session_id),
        turn_generation=rev.turn_generation,
        capture_attempt_id=1,
        revision=rev,
        exercise_id=rev.exercise_id,
        spec_version=rev.spec_version,
        language_mode=LanguageMode.TA_EN_CODEMIX,
        source_code=exec_req.source_code,
    )
    assert stt_req.language_mode == LanguageMode.TA_IN_EN_IN

    stt_res = STTResult(
        request_id="prov_123",
        client_request_id="cli_456",
        provider_request_id="prov_123",
        language_mode=LanguageMode.TA_EN_CODEMIX,
        observed_format="codemix",
        raw_transcript="moonu illa onnu",
        normalized_transcript="1",
        contains_self_correction=True,
        audio_duration_sec=1.25,
        latency_ms=340,
    )
    assert stt_res.client_request_id == "cli_456"
    assert stt_res.provider_request_id == "prov_123"

    tts_req = TTSRequest(
        session_id=str(rev.session_id),
        turn_generation=rev.turn_generation,
        playback_id="play_1",
        revision=rev,
        text="Check nums[i] >= target.",
    )
    ev = AudioEvent(
        event_type="chunk",
        request_id="tts_1",
        client_request_id="tts_1",
        playback_id=tts_req.playback_id,
        chunk_index=1,
        audio_b64="AAAA",
    )
    assert ev.chunk_index == 1

    cap = SpeechCapacityStatus(
        active_requests=0,
        queued_requests=0,
        max_waiting=10,
        degradation_status=SpeechDegradationStatus.HEALTHY,
        stt_seconds_used=1.25,
        tts_chars_used=24,
        stt_requests_count=1,
        tts_requests_count=1,
    )
    assert cap.deployment_topology == "SINGLE_PROCESS_LOCAL_SEMAPHORE"

    ack = VoicePlaybackAckRequest(
        playback_id="play_1",
        session_id=str(rev.session_id),
        turn_id="turn_1",
        turn_generation=1,
        revision=rev,
        playback_status=PlaybackStatus.COMPLETED,
        played_duration_ms=420,
    )
    assert ack.playback_status == PlaybackStatus.COMPLETED
