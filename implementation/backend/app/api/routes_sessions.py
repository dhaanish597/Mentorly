"""Session, Turn, Verification, Coaching, Export & Deletion Routes (`backend/app/api/routes_sessions.py`).

Implements Plan §6.2 & §7 (Phases P3, P4, P5, P7):
- `POST /api/v1/sessions`: Create a new session with starter code and capability token.
- `GET /api/v1/sessions/{session_id}`: Restore session snapshot (redacting any `HIDDEN` challenges/artifacts).
- `PUT /api/v1/sessions/{session_id}/code`: Atomic CAS code save (`expected_code_version_id`), AST keyterm extraction, and stale turn superseding.
- `POST /api/v1/sessions/{session_id}/spec`: Switch specification (`v2_negatives_allowed` enters `SPEC_ACK_REQUIRED`).
- `POST /api/v1/sessions/{session_id}/spec-ack`: Acknowledge specification domain change.
- `POST /api/v1/sessions/{session_id}/challenges`: Issue a deeply immutable `DIAGNOSTIC` or `TRANSFER` challenge (`reveal_state=HIDDEN`).
- `POST /api/v1/sessions/{session_id}/turns/text`: Submit or re-edit a typed turn (`claim_extractor` proposal, `requires_confirmation=True`).
- `POST /api/v1/sessions/{session_id}/turns/{turn_id}/confirm-claim`: Confirm claim, reveal challenge, run isolated verification + trace, and generate Socratic coaching.
- `POST /api/v1/sessions/{session_id}/hints`: Request graduated Socratic hint (`HintLevel` 1, 2, or 3).
- `POST /api/v1/sessions/{session_id}/playback-ack`: Record `COMPLETED`, `INTERRUPTED`, or `READ_TEXT_FALLBACK` playback acknowledgement.
- `POST /api/v1/sessions/{session_id}/cancel`: Cancel active turn, job, or TTS playback.
- `GET /api/v1/sessions/{session_id}/traces/{trace_id}`: Fetch post-line trace (409 if challenge is still `HIDDEN`).
- `GET /api/v1/sessions/{session_id}/export`: Export redacted session JSON bundle.
- `DELETE /api/v1/sessions/{session_id}`: Tombstone session, cancel active turns/jobs, evict session TTS cache, and return honest provider retention disclosure.
- `GET /api/v1/capacity`: Return single-concurrency speech queue depth and execution mode.
"""

from __future__ import annotations

import ast
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Request, UploadFile, File, Form, Response
from backend.app.exercises import registry as exercise_registry
from backend.app.orchestration.worker_client import WorkerClient
from backend.app.coaching.claim_extractor import ModelAssistedClaimExtractor
from backend.app.core.config import Settings
from backend.app.speech.gatekeeper import SpeechBusyError, SpeechQuotaExhaustedError
from backend.app.speech.gnani_adapter import GnaniTransportError

try:
    from backend.app.api.routes_meta import _EXERCISE_CATALOG
    from backend.app.coaching.claim_extractor import extract_claim_deterministic
    from backend.app.coaching.coach_engine import CoachEngine
    from backend.app.core.config import get_request_settings as get_settings
    from backend.app.core.errors import ApiAppException
    from backend.app.db.repository import (
        ChallengeNotRevealedError,
        RevisionConflictError,
        SessionDeletedError,
        SessionNotFoundError,
        SQLiteRepository,
    )
    from backend.app.models.api_schemas import (
        CancelRequest,
        CancelResponse,
        CapacityResponse,
        CodeUpdateRequest,
        CodeUpdateResponse,
        ConfirmClaimRequest,
        CreateChallengeRequest,
        CreateSessionRequest,
        CreateSessionResponse,
        DeleteSessionResponse,
        FreshCaseCheckRequest,
        HintRequest,
        PlaybackAckRequest,
        SessionExportResponse,
        SpecAckRequest,
        SpecUpdateRequest,
        TextTurnRequest,
        VoicePlaybackAckResponse,
    )
    from backend.app.models.domain import (
        Challenge,
        EvidenceArtifact,
        OutputPredictionClaim,
        RevisionRef,
    )
    from backend.app.models.enums import (
        ChallengePurpose,
        ClaimPolarity,
        ExerciseId,
        ExtractionMethod,
        LearningState,
        SessionState,
        SpecVersion,
        TurnState,
    )
    from backend.app.orchestration.state_machine import CoordinatorStateMachine
    from backend.app.speech.ast_keyterms import extract_bias_keyterms
except ImportError:  # pragma: no cover
    from app.api.routes_meta import _EXERCISE_CATALOG  # type: ignore[no-redef]
    from app.coaching.claim_extractor import extract_claim_deterministic  # type: ignore[no-redef]
    from app.coaching.coach_engine import CoachEngine  # type: ignore[no-redef]
    from app.core.config import get_request_settings as get_settings  # type: ignore[no-redef]
    from app.core.errors import ApiAppException  # type: ignore[no-redef]
    from app.db.repository import (  # type: ignore[no-redef]
        ChallengeNotRevealedError,
        RevisionConflictError,
        SessionDeletedError,
        SessionNotFoundError,
        SQLiteRepository,
    )
    from app.models.api_schemas import (  # type: ignore[no-redef]
        CancelRequest,
        CancelResponse,
        CapacityResponse,
        CodeUpdateRequest,
        CodeUpdateResponse,
        ConfirmClaimRequest,
        CreateChallengeRequest,
        CreateSessionRequest,
        CreateSessionResponse,
        DeleteSessionResponse,
        FreshCaseCheckRequest,
        HintRequest,
        PlaybackAckRequest,
        SessionExportResponse,
        SpecAckRequest,
        SpecUpdateRequest,
        TextTurnRequest,
        VoicePlaybackAckResponse,
    )
    from app.models.domain import (  # type: ignore[no-redef]
        Challenge,
        EvidenceArtifact,
        OutputPredictionClaim,
        RevisionRef,
    )
    from app.models.enums import (  # type: ignore[no-redef]
        ChallengePurpose,
        ClaimPolarity,
        ExerciseId,
        ExtractionMethod,
        LearningState,
        SessionState,
        SpecVersion,
        TurnState,
    )
    from app.orchestration.state_machine import CoordinatorStateMachine  # type: ignore[no-redef]
    from app.speech.ast_keyterms import extract_bias_keyterms  # type: ignore[no-redef]

router = APIRouter(tags=["sessions"])


def _get_starter_code(exercise_id: str) -> str:
    for item in exercise_registry.public_catalog():
        if item["exercise_id"] == exercise_id:
            return str(item["starter_code"])
    raise ValueError("No accepted problem package exists for this exercise.")


def _selected_model_configuration(settings: Settings | None = None) -> tuple[str, str]:
    settings = settings or get_settings()
    if settings.llm_provider != "groq" or not settings.groq_api_key or not settings.llm_model.strip():
        return "", ""
    return settings.groq_api_key.get_secret_value(), settings.llm_model.strip()


def _configured_coach() -> CoachEngine:
    key, model = _selected_model_configuration()
    return CoachEngine(llm_api_key=key, llm_model=model, llm_timeout_ms=get_settings().llm_timeout_ms)


def _configured_extractor(settings: Settings | None = None) -> ModelAssistedClaimExtractor:
    key, model = _selected_model_configuration(settings)
    return ModelAssistedClaimExtractor(api_key=key, model=model)


def _get_repo_and_machine() -> tuple[SQLiteRepository, CoordinatorStateMachine]:
    settings = get_settings()
    repo = SQLiteRepository(settings.database_target)
    repo.initialize()
    coach = _configured_coach()
    worker = None
    if settings.allow_public_custom_code and (settings.execution_runtime == 'vercel_sandbox' or settings.internal_worker_secret):
        import asyncio
        from backend.app.core.execution_readiness import probe_execution_readiness
        # Execution routes are synchronous threadpool routes. Async speech routes do
        # not dispatch learner jobs and must not block their event loop for this probe.
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            ready = asyncio.run(probe_execution_readiness(settings)) == 'READY'
        else:
            ready = False
        if ready:
            from backend.app.core.worker_factory import get_worker_client
            worker = get_worker_client(settings)
    machine = CoordinatorStateMachine(repo, worker_client=worker, coach_engine=coach)
    return repo, machine


def _translate_repo_error(exc: Exception) -> ApiAppException:
    if isinstance(exc, ApiAppException):
        return exc
    from backend.app.orchestration.lifecycle_errors import TransferUnavailableError
    if isinstance(exc, TransferUnavailableError):
        return ApiAppException(status_code=409,code='TRANSFER_UNAVAILABLE',message=str(exc))
    if isinstance(exc, SessionNotFoundError):
        return ApiAppException(status_code=404, code="SESSION_NOT_FOUND", message=str(exc))
    if isinstance(exc, SessionDeletedError):
        return ApiAppException(status_code=410, code="SESSION_DELETED", message=str(exc))
    if isinstance(exc, RevisionConflictError):
        return ApiAppException(status_code=409, code="REVISION_CONFLICT", message=str(exc))
    if isinstance(exc, ChallengeNotRevealedError):
        return ApiAppException(status_code=409, code="CHALLENGE_HIDDEN", message=str(exc))
    return ApiAppException(status_code=400, code="BAD_REQUEST", message=str(exc))


@router.post("/sessions", response_model=CreateSessionResponse)
def create_session_route(req: CreateSessionRequest) -> CreateSessionResponse:
    repo, machine = _get_repo_and_machine()
    try:
        exercise_registry.get_spec(req.exercise_id.value, req.spec_version.value)
    except ValueError as exc:
        raise ApiAppException(status_code=422, code="INVALID_EXERCISE_SPEC", message=str(exc)) from exc
    session_uuid = uuid4()
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    starter_code = _get_starter_code(req.exercise_id.value)
    starter_hash = hashlib.sha256(starter_code.encode("utf-8")).hexdigest()
    symbols = extract_bias_keyterms(starter_code, req.exercise_id)
    now = datetime.now(timezone.utc)
    exp = (now + timedelta(hours=24)).isoformat()

    spec_ack = req.spec_version != SpecVersion.EX1_V2_NEGATIVES_ALLOWED
    init_state = SessionState.READY if spec_ack else SessionState.SPEC_ACK_REQUIRED

    rec = repo.create_session(
        session_id=str(session_uuid),
        token_hash=token_hash,
        exercise_id=req.exercise_id.value,
        spec_version=req.spec_version.value,
        language_mode=req.language_mode.value,
        interaction_mode=req.interaction_mode.value,
        starter_code=starter_code,
        starter_code_hash=starter_hash,
        expires_at=exp,
        ast_symbols_json=json.dumps(symbols),
        spec_acknowledged=spec_ack,
        state=init_state.value,
        learning_state=LearningState.EXPLAINING.value,
    )
    with repo._connect() as conn:
        conn.execute('UPDATE sessions SET voice=?,spoken_language=? WHERE id=?', (req.voice, req.spoken_language, rec.id))
    rev = machine.build_revision_ref(rec.id)
    return CreateSessionResponse(
        voice=req.voice, spoken_language=req.spoken_language,
        session_id=session_uuid,
        session_token=raw_token,
        starter_code=starter_code,
        revision=rev,
        state=SessionState(rec.state),
        learning_state=LearningState(rec.learning_state),
        spec_acknowledged=rec.spec_acknowledged,
    )


@router.get("/sessions/{session_id}")
def get_session_snapshot_route(session_id: UUID) -> dict[str, Any]:
    repo, machine = _get_repo_and_machine()
    try:
        from backend.app.orchestration.restore import build_learning_snapshot
        return build_learning_snapshot(repo,machine,str(session_id))
    except Exception as exc:
        raise _translate_repo_error(exc) from exc


@router.put("/sessions/{session_id}/code", response_model=CodeUpdateResponse)
def update_code_route(session_id: UUID, req: CodeUpdateRequest) -> CodeUpdateResponse:
    repo, machine = _get_repo_and_machine()
    try:
        s_rec = repo.get_session(str(session_id))
        if s_rec is None:
            raise SessionNotFoundError(f"Session not found: {session_id}")
        code_hash = hashlib.sha256(req.code.encode("utf-8")).hexdigest()
        syntax_err: str | None = None
        try:
            ast.parse(req.code)
        except SyntaxError as syn:
            syntax_err = f"Line {syn.lineno}: {syn.msg}"
        symbols = extract_bias_keyterms(req.code, s_rec.exercise_id)
        save_res = repo.save_code_version(
            str(session_id),
            expected_code_version_id=req.expected_code_version_id,
            source_code=req.code,
            code_hash=code_hash,
            ast_symbols_json=json.dumps(symbols),
            client_edit_sequence=req.client_edit_sequence,
        )
        rev = machine.build_revision_ref(str(session_id))
        return CodeUpdateResponse(
            revision=rev,
            changed=save_res.changed,
            ast_symbols=symbols,
            syntax_error=syntax_err,
        )
    except Exception as exc:
        raise _translate_repo_error(exc) from exc


@router.post("/sessions/{session_id}/spec")
def update_spec_route(session_id: UUID, req: SpecUpdateRequest) -> dict[str, Any]:
    repo, machine = _get_repo_and_machine()
    try:
        machine.assert_revision_matches(str(session_id), req.expected_revision)
        exercise_registry.get_spec(req.expected_revision.exercise_id.value, req.target_spec_version.value)
        ack = req.target_spec_version != SpecVersion.EX1_V2_NEGATIVES_ALLOWED
        s_rec = repo.update_spec(
            str(session_id),
            spec_version=req.target_spec_version.value,
            expected_code_version_id=req.expected_revision.code_version_id,
            spec_acknowledged=ack,
            expected_revision=req.expected_revision,
        )
        return {
            "session_id": str(session_id),
            "state": s_rec.state,
            "learning_state": s_rec.learning_state,
            "spec_version": s_rec.spec_version,
            "spec_acknowledged": s_rec.spec_acknowledged,
            "revision": machine.build_revision_ref(str(session_id)).model_dump(mode="json"),
        }
    except Exception as exc:
        raise _translate_repo_error(exc) from exc


@router.post("/sessions/{session_id}/spec-ack")
def acknowledge_spec_route(session_id: UUID, req: SpecAckRequest) -> dict[str, Any]:
    repo, machine = _get_repo_and_machine()
    try:
        machine.assert_revision_matches(str(session_id), req.revision)
        s_rec = repo.acknowledge_spec(
            str(session_id), spec_version=req.spec_version.value
        )
        return {
            "session_id": str(session_id),
            "state": s_rec.state,
            "spec_version": s_rec.spec_version,
            "spec_acknowledged": s_rec.spec_acknowledged,
            "revision": machine.build_revision_ref(str(session_id)).model_dump(mode="json"),
        }
    except Exception as exc:
        raise _translate_repo_error(exc) from exc


@router.post("/sessions/{session_id}/challenges", response_model=Challenge)
def create_challenge_route(session_id: UUID, req: CreateChallengeRequest) -> Challenge:
    _repo, machine = _get_repo_and_machine()
    try:
        return machine.issue_challenge(
            str(session_id),
            purpose=req.purpose,
            expected_revision=req.revision,
            requested_input=req.requested_input,
        )
    except Exception as exc:
        raise _translate_repo_error(exc) from exc


@router.post("/sessions/{session_id}/turns/text")
def submit_text_turn_route(session_id: UUID, req: TextTurnRequest) -> dict[str, Any]:
    repo, machine = _get_repo_and_machine()
    try:
        rev = machine.assert_revision_matches(str(session_id), req.revision)
        if req.challenge_id is not None:
            challenge = repo.get_challenge(str(session_id), str(req.challenge_id))
            if challenge is None or challenge["turn_generation"] != rev.turn_generation or challenge["reveal_state"] != "HIDDEN":
                raise RevisionConflictError("A current hidden challenge is required")
        cv_rec = repo.get_code_version(str(session_id), rev.code_version_id)
        symbols = extract_bias_keyterms(cv_rec.source_code if cv_rec else "", rev.exercise_id)
        claim_proposal = _configured_extractor().extract(
            req.text,
            challenge_id=req.challenge_id,
            target_spec_version=rev.spec_version,
            known_identifiers=symbols,
        )
        turn_rec, capture_attempt_id = repo.create_or_reuse_turn(
            session_id=str(session_id),
            code_version_id=rev.code_version_id,
            challenge_id=str(req.challenge_id) if req.challenge_id else None,
            transport_mode="TEXT",
            state=TurnState.AWAITING_CLAIM_CONFIRMATION.value,
            raw_transcript=req.text,
            normalized_transcript=req.text,
            claim_json=claim_proposal.model_dump_json(),
        )
        return {
            "turn_id": turn_rec.id,
            "turn_generation": turn_rec.turn_generation,
            "capture_attempt_id": capture_attempt_id,
            "state": turn_rec.state,
            "requires_confirmation": True,
            "proposed_claim": claim_proposal.model_dump(mode="json"),
            "revision": machine.build_revision_ref(str(session_id)).model_dump(mode="json"),
        }
    except Exception as exc:
        raise _translate_repo_error(exc) from exc


@router.post("/sessions/{session_id}/turns/{turn_id}/confirm-claim")
def confirm_claim_route(
    session_id: UUID, turn_id: UUID, req: ConfirmClaimRequest
) -> dict[str, Any]:
    _repo, machine = _get_repo_and_machine()
    try:
        return machine.confirm_claim_and_execute(
            str(session_id),
            turn_id=str(turn_id),
            challenge_id=req.challenge_id,
            expected_revision=req.revision,
            claim=req.claim,
            capture_attempt_id=getattr(req,'capture_attempt_id',None),
        )
    except Exception as exc:
        raise _translate_repo_error(exc) from exc


from backend.app.models.api_schemas import VerifyRequest, RetryExecutionRequest


@router.post('/sessions/{session_id}/verify', response_model=None)
def verify_revision_route(session_id: UUID, req: VerifyRequest) -> dict[str, Any]:
    _repo, machine = _get_repo_and_machine()
    try:
        return machine.verify_revision(str(session_id),expected_revision=req.revision,
            prior_artifact_id=req.prior_artifact_id, run_curated_suite=getattr(req,'run_curated_suite',True),
            generated_cases_target=getattr(req,'generated_cases_target',20))
    except Exception as exc:
        raise _translate_repo_error(exc) from exc


@router.post('/sessions/{session_id}/turns/{turn_id}/retry-execution', response_model=None)
def retry_execution_route(session_id: UUID, turn_id: UUID, req: RetryExecutionRequest) -> dict[str, Any]:
    _repo, machine = _get_repo_and_machine()
    try:
        return machine.retry_execution(str(session_id),turn_id=str(turn_id),expected_revision=req.revision)
    except Exception as exc:
        raise _translate_repo_error(exc) from exc


@router.post("/sessions/{session_id}/fresh-case-check")
def fresh_case_check_route(
    session_id: UUID, req: FreshCaseCheckRequest
) -> dict[str, Any]:
    _repo, machine = _get_repo_and_machine()
    try:
        claim = OutputPredictionClaim(
            challenge_id=req.challenge_id,
            predicted_output=req.confirmed_prediction,
            reason_summary="Confirmed fresh transfer prediction",
            polarity=ClaimPolarity.AFFIRMATIVE,
            extraction_method=ExtractionMethod.USER_EDITED,
            confirmed_at=datetime.now(timezone.utc),
        )
        return machine.confirm_claim_and_execute(
            str(session_id),
            turn_id=None,
            challenge_id=req.challenge_id,
            expected_revision=req.revision,
            claim=claim,
        )
    except Exception as exc:
        raise _translate_repo_error(exc) from exc


@router.post("/sessions/{session_id}/hints")
def request_hint_route(session_id: UUID, req: HintRequest) -> dict[str, Any]:
    repo, machine = _get_repo_and_machine()
    try:
        rev = machine.assert_revision_matches(str(session_id), req.revision)
        art_dict = repo.get_artifact_view(str(session_id), str(req.artifact_id))
        if art_dict is None:
            raise ApiAppException(
                status_code=404, code="ARTIFACT_NOT_FOUND", message="Artifact not found"
            )
        if art_dict.get("reveal_state") == "HIDDEN":
            raise ChallengeNotRevealedError(
                "Hints are unavailable until prediction is confirmed for the active challenge."
            )
        artifact = EvidenceArtifact.model_validate(art_dict)
        if artifact.revision != rev:
            raise RevisionConflictError("Hint evidence belongs to a superseded revision")
        trace_rep = None
        if artifact.trace_id is not None:
            tr_dict = repo.get_trace_report(str(session_id), str(artifact.trace_id))
            if tr_dict is not None:
                from backend.app.models.domain import TraceExecutionReport

                trace_rep = TraceExecutionReport.model_validate(tr_dict)
        s_rec = repo.get_session(str(session_id))
        cv_rec = repo.get_code_version(str(session_id), rev.code_version_id)
        coach = _configured_coach()
        repo.advance_hint(str(session_id),str(req.artifact_id),rev,int(req.requested_level))
        return coach.build_coaching_turn_response(
            artifact=artifact,
            trace_report=trace_rep,
            learning_state=LearningState(s_rec.learning_state if s_rec else "REPAIR_REQUIRED"),
            hint_level=req.requested_level,
            source_code=cv_rec.source_code if cv_rec else "",
        )
    except ApiAppException:
        raise
    except Exception as exc:
        raise _translate_repo_error(exc) from exc


@router.post("/sessions/{session_id}/playback-ack", response_model=VoicePlaybackAckResponse)
def playback_ack_route(
    session_id: UUID, req: PlaybackAckRequest
) -> VoicePlaybackAckResponse:
    repo, _machine = _get_repo_and_machine()
    try:
        rev = _machine.assert_revision_matches(str(session_id), req.revision)
        with repo._connect() as conn:
            event = conn.execute("SELECT payload_json FROM session_events WHERE session_id=? AND event_type='TTS_READY' AND json_extract(payload_json,'$.playback_id')=? ORDER BY sequence_no DESC LIMIT 1", (str(session_id),str(req.playback_id))).fetchone()
        if event is None or json.loads(event[0]).get("revision") != rev.model_dump(mode="json"):
            raise RevisionConflictError("Playback acknowledgement has no current server-owned audio identity")
        repo.record_session_event(
            str(session_id),
            "PLAYBACK_ACK",
            {
                "playback_id": str(req.playback_id),
                "playback_status": req.playback_status.value,
                "played_duration_ms": req.played_duration_ms,
            },
        )
        return VoicePlaybackAckResponse(
            playback_id=str(req.playback_id),
            session_id=str(session_id),
            turn_id=str(req.playback_id),
            turn_generation=req.revision.turn_generation,
            playback_status=req.playback_status,
            acknowledged=True,
        )
    except Exception as exc:
        raise _translate_repo_error(exc) from exc


@router.post("/sessions/{session_id}/cancel", response_model=CancelResponse)
async def cancel_route(session_id: UUID, req: CancelRequest, request: Request) -> CancelResponse:
    repo, _machine = await asyncio.to_thread(_get_repo_and_machine)
    try:
        settings = request.app.state.settings
        if settings.execution_runtime == 'vercel_sandbox' or settings.internal_worker_secret:
            from backend.app.core.worker_factory import get_worker_client
            cancellation_worker = await asyncio.to_thread(get_worker_client, settings)
            _machine = CoordinatorStateMachine(repo, worker_client=cancellation_worker)
        rev = await asyncio.to_thread(_machine.build_revision_ref, str(session_id))
        if req.scope == "TURN":
            request.app.state.speech.cancel(str(session_id), rev.turn_generation)
        else:
            request.app.state.speech.interrupt(str(session_id), rev.turn_generation)
        active_turn = await asyncio.to_thread(repo.get_active_turn, str(session_id))
        cancellation = await asyncio.to_thread(_machine.cancel_active_work,str(session_id),req.job_id) if (req.job_id or req.turn_id or req.scope == 'TURN') else {"cancelled_job_ids":[],"unconfirmed_job_ids":[]}
        cancelled_turns: list[UUID] = [UUID(active_turn.id)] if active_turn and active_turn.state != 'COACH_PROMPT_DELIVERED' and req.scope == 'TURN' and req.turn_id is None else []
        if req.turn_id is not None and req.scope == "TURN":
            await asyncio.to_thread(repo.update_turn,
                str(session_id), str(req.turn_id), state=TurnState.CANCELLED.value
            )
            cancelled_turns.append(req.turn_id)
        return CancelResponse(
            cancelled_turn_ids=cancelled_turns,
            cancelled_job_ids=cancellation["cancelled_job_ids"],
            unconfirmed_job_ids=cancellation["unconfirmed_job_ids"],
            cancelled_playback_ids=[],
        )
    except Exception as exc:
        raise _translate_repo_error(exc) from exc


@router.get("/sessions/{session_id}/traces/{trace_id}")
def get_trace_route(session_id: UUID, trace_id: UUID) -> dict[str, Any]:
    repo, _machine = _get_repo_and_machine()
    try:
        tr = repo.get_trace_report(str(session_id), str(trace_id))
        if tr is None:
            raise ApiAppException(
                status_code=404, code="TRACE_NOT_FOUND", message="Trace not found"
            )
        return tr
    except ApiAppException:
        raise
    except Exception as exc:
        raise _translate_repo_error(exc) from exc


@router.get("/sessions/{session_id}/export", response_model=SessionExportResponse)
def export_session_route(session_id: UUID) -> SessionExportResponse:
    repo, _machine = _get_repo_and_machine()
    try:
        bundle = repo.export_session_bundle(str(session_id))
        return SessionExportResponse.model_validate(bundle)
    except Exception as exc:
        raise _translate_repo_error(exc) from exc


@router.delete("/sessions/{session_id}", response_model=DeleteSessionResponse)
async def delete_session_route(session_id: UUID, request: Request) -> DeleteSessionResponse:
    repo, _machine = _get_repo_and_machine()
    try:
        rev = _machine.build_revision_ref(str(session_id))
        settings = request.app.state.settings
        if settings.execution_runtime == 'vercel_sandbox' or settings.internal_worker_secret:
            from backend.app.core.worker_factory import get_worker_client
            cancellation_worker = get_worker_client(settings)
            _machine = CoordinatorStateMachine(repo, worker_client=cancellation_worker)
        cancellation = await asyncio.to_thread(_machine.cancel_active_work, str(session_id), tombstone=True)
        pending_audio = await request.app.state.speech.cancel_session(str(session_id), rev.turn_generation)
        if pending_audio:
            await asyncio.to_thread(request.app.state.retention.defer_cache_cleanup, str(session_id))
        else:
            await asyncio.to_thread(request.app.state.speech.cache.evict_session, str(session_id))
        pending_broker_count = await asyncio.to_thread(request.app.state.retention.record_cleanup, str(session_id),
            audio_pending=bool(pending_audio), confirmed_jobs=cancellation["cancelled_job_ids"])
        rec = repo.get_session(str(session_id), include_deleted=True)
        return DeleteSessionResponse(
            session_id=session_id,
            deleted_at=datetime.fromisoformat(rec.deleted_at)
            if rec.deleted_at
            else datetime.now(timezone.utc),
            limitations=(
                "Local SQLite session records, turns and traces have been tombstoned. "
                + ("Session audio cleanup remains pending. " if pending_audio else "Session-scoped TTS cache entries have been evicted. ")
                + "Existing backups require separate operator retention. Any audio previously transmitted to the external "
                "speech provider (Gnani Vachana) is subject to the provider's retention policy. "
                + ("Some broker cancellations remain unconfirmed." if pending_broker_count else "")
            ),
        )
    except Exception as exc:
        raise _translate_repo_error(exc) from exc


@router.get("/capacity", response_model=CapacityResponse)
async def get_capacity_route(request: Request) -> CapacityResponse:
    settings = get_settings()
    from backend.app.core.execution_readiness import probe_execution_readiness
    execution_status = await probe_execution_readiness(settings)
    return CapacityResponse(
        speech_queue_depth=request.app.state.speech.gatekeeper.get_capacity_status().queued_requests,
        custom_code_execution_enabled=execution_status == "READY",
        mode="LIVE" if settings.gnani_api_key else "DEMO",
    )


@router.post('/sessions/{session_id}/turns/audio')
async def submit_audio_turn_route(
    session_id: UUID, request: Request, audio: UploadFile = File(...),
    revision: str = Form(...), challenge_id: str | None = Form(None),
    language_mode: str = Form('en-IN'), capture_attempt_id: int = Form(1),
    transport: str = Form('REST_V3'),
) -> dict[str, Any]:
    repo, machine = _get_repo_and_machine()
    allocated_turn_id: str | None = None
    try:
        rev = RevisionRef.model_validate_json(revision)
        machine.assert_revision_matches(str(session_id), rev)
        cid: UUID | None = None
        if challenge_id and challenge_id.strip() and challenge_id.strip().lower() not in ("null", "none"):
            try:
                cid = UUID(challenge_id.strip())
            except ValueError:
                cid = None
        challenge = repo.get_challenge(str(session_id), str(cid)) if cid is not None else None
        if cid is not None and (challenge is None or challenge['turn_generation'] != rev.turn_generation or challenge['reveal_state'] != 'HIDDEN'):
            raise RevisionConflictError('A current hidden challenge is required.')
        turn, attempt = repo.create_or_reuse_turn(session_id=str(session_id), code_version_id=rev.code_version_id,
            challenge_id=str(cid) if cid is not None else None, transport_mode='VOICE', state=TurnState.TRANSCRIBING_AND_PARSING.value)
        allocated_turn_id = turn.id
        # The authoritative capture counter is allocated before any provider request.
        data = await audio.read(2_000_001)
        if len(data) > 2_000_000:
            raise ValueError('Audio exceeds the capture limit.')
        current_rev = machine.build_revision_ref(str(session_id))
        result = await request.app.state.speech.transcribe(str(session_id), data, language_mode, current_rev, attempt, transport)
        machine.assert_revision_matches(str(session_id), current_rev)
        current = repo.get_turn(str(session_id), turn.id)
        if current is None or current.latest_capture_attempt_id != attempt or current.state in ('CANCELLED','SUPERSEDED'):
            raise RevisionConflictError('This capture was superseded or cancelled.')
        from starlette.concurrency import run_in_threadpool
        proposal = await run_in_threadpool(_configured_extractor().extract, result.normalized_transcript, challenge_id=cid,
            target_spec_version=current_rev.spec_version)
        proposal = proposal.model_copy(update={'provider_confidence': result.provider_confidence})
        repo.update_turn(str(session_id), turn.id, state=TurnState.AWAITING_CLAIM_CONFIRMATION.value,
            raw_transcript=result.raw_transcript, normalized_transcript=result.normalized_transcript,
            claim_json=proposal.model_dump_json(), expected_capture_attempt_id=attempt)
        return {'turn_id':turn.id,'turn_generation':current_rev.turn_generation,'capture_attempt_id':attempt,
            'revision':current_rev.model_dump(mode='json'),'requires_confirmation':True,
            'proposed_claim':proposal.model_dump(mode='json'),'transcript':result.normalized_transcript,
            'speech':result.model_dump(mode='json')}
    except (RevisionConflictError, ValueError) as exc:
        raise _translate_repo_error(exc) from exc
    except SpeechBusyError as exc:
        raise ApiAppException(status_code=503, code='SPEECH_BUSY',
            message='Speech is busy; restore the current turn before retrying the recording.',
            retryable=True, turn_id=allocated_turn_id) from exc
    except SpeechQuotaExhaustedError as exc:
        raise ApiAppException(status_code=429, code='SPEECH_QUOTA_EXHAUSTED',
            message='Voice allowance reached. Continue with text.',
            turn_id=allocated_turn_id) from exc
    except Exception as exc:
        import logging, traceback
        logging.getLogger("vcc.audio").error("submit_audio_turn_route failed: %s\n%s", exc, traceback.format_exc())
        raise ApiAppException(status_code=503, code='SPEECH_UNAVAILABLE',
            message='Speech is unavailable; restore the current turn or use the typed fallback.',
            retryable=isinstance(exc, GnaniTransportError) and exc.retryable,
            turn_id=allocated_turn_id) from exc


from backend.app.models.api_schemas import TTSPlaybackRequest


@router.post('/sessions/{session_id}/speech/tts')
async def synthesize_coaching_route(session_id: UUID, req: TTSPlaybackRequest, request: Request) -> Response:
    repo, machine = _get_repo_and_machine()
    try:
        rev = machine.assert_revision_matches(str(session_id), req.revision)
        text = _grounded_speech_text(repo, machine, str(session_id), req)
    except Exception as exc:
        raise _translate_repo_error(exc) from exc
    if not text:
        raise ApiAppException(status_code=503, code='COACHING_UNAVAILABLE', message='No grounded coaching text is available.')
    playback_id = str(uuid4())
    try:
        result = await request.app.state.speech.synthesize(str(session_id), text, rev, playback_id=playback_id, language=req.language, voice=req.voice)
    except Exception as exc:
        raise ApiAppException(status_code=503, code='SPEECH_UNAVAILABLE', message='Speech is unavailable; read the coaching text.') from exc
    machine.assert_revision_matches(str(session_id), rev)
    repo.record_session_event(str(session_id),'TTS_READY',{'playback_id':playback_id,'revision':rev.model_dump(mode='json'),
        'normalized_text_hash':hashlib.sha256(text.encode()).hexdigest(),'request_id':result.request_id,'cache_hit':result.cache_hit})
    headers = {'X-Playback-ID': playback_id, 'Cache-Control': 'no-store'}
    provider_id = next((event.provider_request_id for event in reversed(getattr(result, 'events', ())) if event.provider_request_id), None)
    if provider_id:
        headers['X-Provider-Request-ID'] = provider_id
    return Response(result.wav_bytes, media_type='audio/wav', headers=headers)


def _grounded_speech_text(repo, machine, session_id: str, req: TTSPlaybackRequest) -> str:
    rev = machine.assert_revision_matches(session_id, req.revision)
    raw = repo.get_artifact_view(session_id, str(req.artifact_id))
    if not raw or raw.get('reveal_state') == 'HIDDEN':
        raise ApiAppException(status_code=409, code='CHALLENGE_HIDDEN', message='Confirm the prediction before requesting speech.')
    artifact = EvidenceArtifact.model_validate(raw)
    if artifact.revision != rev:
        raise RevisionConflictError('Coaching evidence is superseded.')
    repo.require_unlocked_hint(session_id,str(req.artifact_id),int(req.hint_level))
    trace_data = repo.get_trace_report(session_id,str(artifact.trace_id)) if artifact.trace_id else None
    from backend.app.models.domain import TraceExecutionReport
    session = repo.get_session(session_id)
    response = _configured_coach().build_coaching_turn_response(artifact=artifact,
        trace_report=TraceExecutionReport.model_validate(trace_data) if trace_data else None,
        learning_state=LearningState(session.learning_state), hint_level=req.hint_level)
    return response['speakable_text']


@router.post('/sessions/{session_id}/speech/tts-stream')
async def stream_coaching_route(session_id: UUID, req: TTSPlaybackRequest, request: Request):
    from fastapi.responses import StreamingResponse
    repo, machine = _get_repo_and_machine()
    try:
        text = _grounded_speech_text(repo, machine, str(session_id), req)
    except Exception as exc:
        raise _translate_repo_error(exc) from exc
    playback_id = str(uuid4())
    repo.record_session_event(str(session_id),'TTS_READY',{'playback_id':playback_id,
        'revision':req.revision.model_dump(mode='json'),'normalized_text_hash':hashlib.sha256(text.encode()).hexdigest()})
    async def stream():
        try:
            async for event in request.app.state.speech.stream_synthesize(str(session_id),text,req.revision,playback_id=playback_id,language=req.language,voice=req.voice):
                machine.assert_revision_matches(str(session_id),req.revision)
                if await request.is_disconnected():
                    request.app.state.speech.cancel(str(session_id),req.revision.turn_generation)
                    break
                yield 'data: '+event.model_dump_json()+'\n\n'
        except Exception:
            yield 'data: '+json.dumps({'event_type':'error','request_id':playback_id,'error_code':'SPEECH_UNAVAILABLE','error_message':'Speech stopped; read the coaching text.'})+'\n\n'
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})


from fastapi import WebSocket


@router.websocket('/sessions/{session_id}/speech/ws')
async def browser_speech_ws(websocket: WebSocket, session_id: UUID):
    import asyncio
    import hmac
    from datetime import timezone
    from backend.app.core.config import get_settings as default_settings
    settings = websocket.app.state.settings
    origin = websocket.headers.get('origin')
    if origin and origin not in settings.cors_origins_list:
        await websocket.close(code=4403)
        return
    await websocket.accept()
    repo = SQLiteRepository(settings.database_target)
    repo.initialize()
    machine = CoordinatorStateMachine(repo)
    rev = None
    try:
        first_text = await asyncio.wait_for(websocket.receive_text(),timeout=5)
        if len(first_text) > 8192:
            raise ValueError('Invalid opening frame')
        first = json.loads(first_text)
        token = str(first.get('token',''))
        session = repo.get_session(str(session_id),include_deleted=True)
        if not token or session is None or not hmac.compare_digest(session.token_hash,hashlib.sha256(token.encode()).hexdigest()):
            await websocket.close(code=4401)
            return
        if session.deleted_at or datetime.fromisoformat(session.expires_at) <= datetime.now(timezone.utc):
            await websocket.close(code=4410)
            return
        rev = RevisionRef.model_validate(first['revision'])
        machine.assert_revision_matches(str(session_id),rev)
        cid = UUID(first['challenge_id']) if first.get('challenge_id') is not None else None
        if cid is not None:
            challenge = repo.get_challenge(str(session_id),str(cid))
            if challenge is None or challenge['turn_generation'] != rev.turn_generation or challenge['reveal_state'] != 'HIDDEN':
                raise RevisionConflictError('A current hidden challenge is required.')
        turn, attempt = repo.create_or_reuse_turn(session_id=str(session_id),code_version_id=rev.code_version_id,
            challenge_id=str(cid) if cid is not None else None,transport_mode='VOICE',state=TurnState.TRANSCRIBING_AND_PARSING.value)
        capture_rev = machine.build_revision_ref(str(session_id))
        if (capture_rev.code_version_id != rev.code_version_id
                or capture_rev.spec_version != rev.spec_version
                or capture_rev.turn_generation != turn.turn_generation):
            raise RevisionConflictError('Capture revision was superseded.')
        rev = capture_rev
        async def frames():
            total = 0
            while True:
                message = await asyncio.wait_for(websocket.receive(),timeout=35)
                if message['type'] == 'websocket.disconnect':
                    raise asyncio.CancelledError()
                if message.get('bytes') is not None:
                    chunk = message['bytes']
                    total += len(chunk)
                    if len(chunk) > 1024 or len(chunk)%2 or total > 960000:
                        raise ValueError('PCM capture limit exceeded')
                    yield chunk
                elif message.get('text') is not None:
                    if len(message['text']) > 100 or json.loads(message['text']).get('type') != 'commit':
                        raise ValueError('Invalid control frame')
                    break
        result = await websocket.app.state.speech.transcribe_frames(str(session_id),frames(),
            first.get('language_mode','en-IN'),rev,attempt)
        machine.assert_revision_matches(str(session_id), rev)
        current = repo.get_turn(str(session_id),turn.id)
        if not current or current.latest_capture_attempt_id != attempt or current.state in ('CANCELLED','SUPERSEDED'):
            raise RevisionConflictError('Capture superseded')
        from starlette.concurrency import run_in_threadpool
        claim = await run_in_threadpool(_configured_extractor(settings).extract, result.normalized_transcript,challenge_id=cid,target_spec_version=rev.spec_version)
        claim = claim.model_copy(update={'provider_confidence':result.provider_confidence})
        machine.assert_revision_matches(str(session_id), rev)
        repo.update_turn(str(session_id),turn.id,state=TurnState.AWAITING_CLAIM_CONFIRMATION.value,
            raw_transcript=result.raw_transcript,normalized_transcript=result.normalized_transcript,claim_json=claim.model_dump_json(),expected_capture_attempt_id=attempt)
        await websocket.send_json({'turn_id':turn.id,'revision':rev.model_dump(mode='json'),
            'capture_attempt_id':attempt,'requires_confirmation':True,'proposed_claim':claim.model_dump(mode='json'),
            'transcript':result.normalized_transcript,'speech':result.model_dump(mode='json')})
    except asyncio.CancelledError:
        if rev:
            websocket.app.state.speech.cancel(str(session_id),rev.turn_generation)
    except Exception:
        try:
            await websocket.send_json({'type':'error','message':'Voice capture is unavailable; use typed input.'})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
