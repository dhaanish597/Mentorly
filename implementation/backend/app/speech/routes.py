"""Public introductions, voice checks and non-executing learner conversation.

Mount under /api/v1 using the existing session capability, admission and durable
idempotency middleware. There is deliberately no caller-provided speech text.
"""
from __future__ import annotations

import asyncio
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict

from backend.app.core.errors import ApiAppException
from backend.app.db.repository import RevisionConflictError, SQLiteRepository, TurnRecord
from backend.app.models.domain import RevisionRef
from backend.app.models.enums import TurnState, SpeechLocale, TTSVoice
from backend.app.speech.capabilities import speech_capabilities
from backend.app.speech.gatekeeper import SpeechBusyError, SpeechQuotaExhaustedError
from backend.app.speech.gnani_adapter import GnaniTransportError

router = APIRouter(tags=["speech"])


class FixedVoiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: RevisionRef
    language: SpeechLocale | None = None
    voice: TTSVoice | None = None


@router.get('/speech/capabilities')
async def speech_capability_info(request: Request) -> dict[str, object]:
    return speech_capabilities(request.app.state.settings)


_TEST_VOICE_TEXT = "Voice is ready. You can change the volume or continue with text."


def fixed_introduction(revision: RevisionRef) -> str:
    from backend.app.exercises import registry
    catalog = registry.public_catalog()
    public = next((entry for entry in catalog if str(entry["exercise_id"]) == revision.exercise_id.value), None)
    if public is None:
        raise ValueError("The current problem has no public introduction.")
    title = str(public.get("title") or public.get("name") or "this coding problem").strip()[:160]
    return f"Let's explore {title}. Before coding, how would you approach this problem? Read its contract, make a prediction, and explain your reasoning before seeing the result."


@router.get("/sessions/{session_id}/speech/status")
async def speech_status(session_id: UUID, request: Request) -> dict[str, object]:
    """Configuration only: never probe credentials, credit, or provider readiness."""
    configured = request.app.state.settings.gnani_api_key is not None
    return {"status": "CONFIGURED_UNVERIFIED" if configured else "TEXT_ONLY",
            "configured": configured, "provider_verified": False,
            "credit_remaining_status": "UNKNOWN_UNVERIFIED_TARIFF"}


async def _await_connected_voice(request: Request, operation):
    """Disconnect cancels the tracked dispatcher task, retaining uncertain usage."""
    task = asyncio.create_task(operation)
    try:
        while not task.done():
            done, _ = await asyncio.wait({task}, timeout=0.1)
            if not done and await request.is_disconnected():
                raise asyncio.CancelledError("Voice client disconnected.")
        return await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def _fixed_voice(session_id: UUID, req: FixedVoiceRequest, request: Request, purpose: str) -> Response:
    from backend.app.api.routes_sessions import _get_repo_and_machine
    _, machine = _get_repo_and_machine()
    try:
        revision = machine.assert_revision_matches(str(session_id), req.revision)
    except (RevisionConflictError, ValueError) as exc:
        raise ApiAppException(status_code=409, code="REVISION_CONFLICT", message="This voice request is superseded; restore the current problem.") from exc
    playback_id = str(uuid4())
    selection = {key: value for key, value in {'language':req.language, 'voice':req.voice}.items() if value is not None}
    try:
        result = await _await_connected_voice(request, request.app.state.speech.synthesize_fixed(str(session_id), revision, purpose=purpose, playback_id=playback_id, **selection))
        machine.assert_revision_matches(str(session_id), revision)
    except RevisionConflictError as exc:
        raise ApiAppException(status_code=409, code="REVISION_CONFLICT", message="This voice request is superseded; restore the current problem.") from exc
    except SpeechQuotaExhaustedError as exc:
        raise ApiAppException(status_code=429, code="SPEECH_QUOTA_EXHAUSTED", message="Voice allowance reached. Continue with text.") from exc
    except SpeechBusyError as exc:
        raise ApiAppException(status_code=409, code="SPEECH_BUSY", message="Voice is busy or superseded. Continue with text.") from exc
    except GnaniTransportError as exc:
        raise ApiAppException(status_code=503, code="SPEECH_UNAVAILABLE", message="Voice is unavailable. Continue with text.") from exc
    headers = {"Cache-Control": "no-store", "X-Playback-ID": playback_id, "X-Voice-Purpose": purpose}
    provider_id = next((event.provider_request_id for event in reversed(result.events) if event.provider_request_id), None)
    if provider_id:
        headers["X-Provider-Request-ID"] = provider_id
    return Response(result.wav_bytes, media_type="audio/wav", headers=headers)


@router.post("/sessions/{session_id}/speech/introduction")
async def introduction_voice(session_id: UUID, req: FixedVoiceRequest, request: Request) -> Response:
    return await _fixed_voice(session_id, req, request, "INTRODUCTION")


@router.post("/sessions/{session_id}/speech/test-voice")
async def test_voice(session_id: UUID, req: FixedVoiceRequest, request: Request) -> Response:
    return await _fixed_voice(session_id, req, request, "TEST_VOICE")


class ConversationVoiceRequest(FixedVoiceRequest):
    turn_id: UUID


_CAPTURED_STATES = frozenset({
    TurnState.AWAITING_CLAIM_CONFIRMATION.value, TurnState.CLAIM_FALLBACK_EDIT.value,
    TurnState.VERIFYING_AND_COACHING.value, TurnState.AUDIO_READY.value,
    TurnState.AWAITING_PLAYBACK_ACK.value, TurnState.COACH_PROMPT_DELIVERED.value,
})


def _conversation_turn(repo: SQLiteRepository, session_id: str,
                       turn_id: UUID, revision: RevisionRef) -> TurnRecord:
    turn = repo.get_turn(session_id, str(turn_id))
    if turn is None:
        raise ApiAppException(status_code=404, code="TURN_NOT_FOUND",
                              message="No learner turn is available for this conversation.")
    if (turn.session_id != session_id or turn.code_version_id != revision.code_version_id
            or turn.turn_generation != revision.turn_generation
            or turn.state not in _CAPTURED_STATES):
        raise RevisionConflictError("This learner capture is incomplete or superseded.")
    if not isinstance(turn.normalized_transcript, str) or not turn.normalized_transcript.strip():
        raise ApiAppException(status_code=409, code="TRANSCRIPT_UNAVAILABLE",
                              message="Finish or re-enter your explanation before requesting voice.")
    return turn


def _public_conversation_problem(revision: RevisionRef) -> dict:
    from backend.app.exercises import registry
    public = next((entry for entry in registry.public_catalog()
                   if str(entry["exercise_id"]) == revision.exercise_id.value), None)
    if public is None:
        raise ApiAppException(status_code=503, code="PUBLIC_CONTRACT_UNAVAILABLE",
                              message="Read the problem contract and continue with text.")
    return public


def _conversation_text(revision: RevisionRef, turn: TurnRecord) -> str:
    from backend.app.coaching.conversation import authored_reply
    return authored_reply(_public_conversation_problem(revision), revision.spec_version.value,
                          turn.normalized_transcript, [])


async def _saved_conversation_reply(request: Request, sid: str, revision: RevisionRef, turn: TurnRecord):
    from backend.app.coaching.conversation import conversation_reply
    return await _await_connected_voice(request, conversation_reply(
        request.app.state.settings, sid, revision, turn, _public_conversation_problem(revision)))


@router.post('/sessions/{session_id}/conversation/text')
async def conversation_text(session_id: UUID, req: ConversationVoiceRequest, request: Request) -> dict[str, object]:
    """Transcript-aware saved reply, independent of TTS availability."""
    from backend.app.api.routes_sessions import _get_repo_and_machine
    repo, machine = _get_repo_and_machine()
    sid = str(session_id)
    try:
        revision = machine.assert_revision_matches(sid, req.revision)
        turn = _conversation_turn(repo, sid, req.turn_id, revision)
        reply = await _saved_conversation_reply(request, sid, revision, turn)
        text = reply['text']
        machine.assert_revision_matches(sid, revision)
        if _conversation_turn(repo, sid, req.turn_id, revision) != turn:
            raise RevisionConflictError('The learner capture changed.')
    except RevisionConflictError as exc:
        raise ApiAppException(status_code=409, code='REVISION_CONFLICT', message='Restore the current learner turn.') from exc
    return {'text': text, 'turn_id': turn.id, 'revision': revision.model_dump(mode='json'),
            'source': reply['source']}


@router.post("/sessions/{session_id}/speech/conversation")
async def conversation_voice(session_id: UUID, req: ConversationVoiceRequest,
                             request: Request) -> Response:
    """Speak about a stored capture without confirming it or changing the turn."""
    from backend.app.api.routes_sessions import _get_repo_and_machine
    repo, machine = _get_repo_and_machine()
    sid = str(session_id)
    playback_id = str(uuid4())
    try:
        revision = machine.assert_revision_matches(sid, req.revision)
        turn = _conversation_turn(repo, sid, req.turn_id, revision)
        reply = await _saved_conversation_reply(request, sid, revision, turn)
        text = reply['text']
        selection = {key: value for key, value in {'language':req.language, 'voice':req.voice}.items() if value is not None}
        result = await _await_connected_voice(request, request.app.state.speech.synthesize(
            sid, text, revision, turn_id=turn.id, playback_id=playback_id, **selection))
        machine.assert_revision_matches(sid, revision)
        # A re-record can replace the transcript without changing the revision/generation.
        if _conversation_turn(repo, sid, req.turn_id, revision) != turn:
            raise RevisionConflictError("The learner capture changed during synthesis.")
    except RevisionConflictError as exc:
        raise ApiAppException(status_code=409, code="REVISION_CONFLICT",
                              message="This voice request is superseded; restore the current turn.") from exc
    except SpeechQuotaExhaustedError as exc:
        raise ApiAppException(status_code=429, code="SPEECH_QUOTA_EXHAUSTED",
                              message="Voice allowance reached. Continue with text.") from exc
    except SpeechBusyError as exc:
        raise ApiAppException(status_code=409, code="SPEECH_BUSY",
                              message="Voice is busy or superseded. Continue with text.") from exc
    except GnaniTransportError as exc:
        raise ApiAppException(status_code=503, code="SPEECH_UNAVAILABLE",
                              message="Voice is unavailable. Continue with text.") from exc
    return Response(result.wav_bytes, media_type="audio/wav", headers={
        "Cache-Control": "no-store", "X-Playback-ID": playback_id,
        "X-Voice-Purpose": "CONVERSATION", "X-Coach-Text": quote(text, safe="", encoding="utf-8"),
    })
