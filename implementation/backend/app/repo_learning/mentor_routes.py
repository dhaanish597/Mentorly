"""FastAPI routes for Codebase Learning AI Mentor sessions, voice turns, and history."""

from __future__ import annotations

import base64
from contextlib import closing
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from backend.app.core.config import get_request_settings as get_settings
from backend.app.db.migrations import database_target, open_connection
from backend.app.repo_learning.mentor_service import CodebaseMentorService
from backend.app.repo_learning.audio_storage import get_audio
from backend.app.studio.security import authenticate_workspace

WorkspaceId = Annotated[str, Header(alias="X-Workspace-Id", min_length=1, max_length=128)]
WorkspaceToken = Annotated[str, Header(alias="X-Workspace-Token", min_length=1, max_length=128)]


def _authorize(request: Request, workspace: WorkspaceId, token: WorkspaceToken) -> None:
    authenticate_workspace(request, workspace, token)


router = APIRouter(prefix="/codebase-learning", tags=["codebase-learning"], dependencies=[Depends(_authorize)])


def _get_service(request: Request) -> CodebaseMentorService:
    settings = get_settings()
    return CodebaseMentorService(
        db_path=database_target(settings),
        tts_cache_dir=settings.tts_cache_dir,
        request=request,
    )


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_id: str = Field(min_length=1, max_length=128)
    repo_url: str = Field(min_length=1, max_length=512)
    repo_name: str = Field(min_length=1, max_length=128)
    branch: str = Field(default="main", max_length=128)
    commit_sha: str | None = Field(default=None, max_length=128)
    title: str | None = Field(default=None, max_length=160)


class RenameSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=160)


class TextTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)


class VoiceTurnJsonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audio_base64: str = Field(min_length=1, max_length=2_000_000)
    speech_locale: str = Field(default="en-IN", max_length=16)


@router.get("/sessions")
async def list_sessions(
    request: Request,
    x_workspace_id: WorkspaceId,
    q: str | None = None,
):
    service = _get_service(request)
    try:
        sessions = await service.list_sessions(x_workspace_id, query=q)
        return {"sessions": sessions}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, "Failed to list learning sessions.") from exc


@router.post("/sessions", status_code=201)
async def create_session(
    request: Request,
    payload: CreateSessionRequest,
    x_workspace_id: WorkspaceId,
):
    service = _get_service(request)
    settings = get_settings()
    try:
        session = await service.create_session(
            workspace_id=x_workspace_id,
            snapshot_id=payload.snapshot_id,
            repo_url=payload.repo_url,
            repo_name=payload.repo_name,
            branch=payload.branch,
            commit_sha=payload.commit_sha,
            title=payload.title,
            settings=settings,
        )
        return session
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, "Failed to create learning session.") from exc


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    request: Request,
    x_workspace_id: WorkspaceId,
):
    service = _get_service(request)
    try:
        return await service.get_session(x_workspace_id, session_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, "Failed to retrieve learning session.") from exc


@router.patch("/sessions/{session_id}")
async def rename_session(
    session_id: str,
    payload: RenameSessionRequest,
    request: Request,
    x_workspace_id: WorkspaceId,
):
    service = _get_service(request)
    try:
        return await service.rename_session(x_workspace_id, session_id, payload.title)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    request: Request,
    x_workspace_id: WorkspaceId,
):
    service = _get_service(request)
    deleted = await service.delete_session(x_workspace_id, session_id)
    if not deleted:
        raise HTTPException(404, "Session not found or already deleted.")
    return Response(status_code=204)


@router.post("/sessions/{session_id}/turns")
async def submit_text_turn(
    session_id: str,
    payload: TextTurnRequest,
    request: Request,
    x_workspace_id: WorkspaceId,
):
    """Text-fallback turn submitting a typed message to the mentor."""
    service = _get_service(request)
    settings = get_settings()
    try:
        return await service.process_turn(
            workspace_id=x_workspace_id,
            session_id=session_id,
            learner_text=payload.text,
            audio_wav_bytes=None,
            settings=settings,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, "Turn reasoning failed.") from exc


@router.post("/sessions/{session_id}/voice-turn")
async def submit_voice_turn(
    session_id: str,
    request: Request,
    x_workspace_id: WorkspaceId,
    payload: VoiceTurnJsonRequest | None = None,
    file: UploadFile | None = None,
):
    """Voice turn: recognizes learner speech via Gnani STT and returns mentor response + TTS audio."""
    service = _get_service(request)
    settings = get_settings()

    audio_bytes: bytes | None = None
    if file:
        audio_bytes = await file.read()
    elif payload and payload.audio_base64:
        try:
            audio_bytes = base64.b64decode(payload.audio_base64)
        except Exception as exc:
            raise HTTPException(422, "Invalid base64 audio") from exc

    if not audio_bytes:
        raise HTTPException(422, "No audio payload supplied")

    try:
        return await service.process_turn(
            workspace_id=x_workspace_id,
            session_id=session_id,
            learner_text=None,
            audio_wav_bytes=audio_bytes,
            speech_locale=payload.speech_locale if payload else "en-IN",
            settings=settings,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, "Voice turn failed.") from exc


@router.get("/audio/{filename}", operation_id="get_codebase_learning_audio")
@router.head("/audio/{filename}", operation_id="head_codebase_learning_audio")
async def serve_audio(filename: str, request: Request, x_workspace_id: WorkspaceId):
    """Serve synthesized mentor audio WAV file."""
    settings = get_settings()
    if Path(filename).name != filename:
        raise HTTPException(404, "Audio file not found")
    with closing(open_connection(database_target(settings))) as conn:
        audio = get_audio(conn, x_workspace_id, filename)
    if audio is None:
        raise HTTPException(404, "Audio file not found")
    return Response(
        content=b"" if request.method == "HEAD" else audio,
        media_type="audio/wav",
        headers={"Cache-Control": "private, no-store", "Content-Length": str(len(audio))},
    )
