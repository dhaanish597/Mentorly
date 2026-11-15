"""Learning API. Mount this router under /api/v1; no app construction side effects."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from backend.app.db.migrations import open_connection
from backend.app.studio.routes import auth_workspace_row
from backend.app.studio.security import authenticate_workspace
from fastapi import APIRouter, Depends, Header, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from .catalog import public_catalog
from .progress import progress_snapshot
from .service import (
    answer_session,
    create_session,
    hint_session,
    owned_session,
    restart_session,
    snapshot,
    transaction,
)

router = APIRouter(prefix="/learning", tags=["learning"])


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NewSession(StrictRequest):
    lesson_id: str = Field(min_length=1, max_length=128, strict=True)
    mode: Literal["practice"]
    language_mode: str = Field(min_length=1, max_length=80, strict=True)


class EpochRequest(StrictRequest):
    expected_epoch: int = Field(ge=1, le=2**53 - 1, strict=True)


class AnswerRequest(EpochRequest):
    question_id: str = Field(min_length=1, max_length=128, strict=True)
    answer: str = Field(min_length=1, max_length=2000, strict=True)


@dataclass(frozen=True)
class WorkspaceScope:
    id: str
    token: str


def database(request: Request) -> str:
    # Pass a path across dependency worker threads, never a thread-bound connection.
    return str(request.app.state.settings.database_path)


Database = Annotated[str, Depends(database)]


def workspace_headers(
    request: Request,
    workspace_id: str = Header(..., alias="X-Workspace-Id", max_length=128),
    workspace_token: str = Header(..., alias="X-Workspace-Token", max_length=256),
) -> WorkspaceScope:
    authenticate_workspace(request, workspace_id, workspace_token)
    return WorkspaceScope(workspace_id, workspace_token)


Workspace = Annotated[WorkspaceScope, Depends(workspace_headers)]
SessionId = Annotated[str, Path(min_length=1, max_length=128)]


@router.get("/catalog", response_model=dict[str, Any])
def get_catalog() -> dict[str, Any]:
    return public_catalog()


@router.get("/progress", response_model=dict[str, Any])
def get_progress(workspace: Workspace, db_path: Database) -> dict[str, Any]:
    with closing(open_connection(db_path)) as conn:
        conn.execute("BEGIN")
        try:
            auth_workspace_row(conn, workspace.id, "Bearer " + workspace.token)
            value = progress_snapshot(conn, workspace.id)
            conn.commit()
            return value
        except BaseException:
            conn.rollback()
            raise


@router.post("/sessions", response_model=dict[str, Any])
def new_session(
    body: NewSession, workspace: Workspace, db_path: Database
) -> dict[str, Any]:
    with closing(open_connection(db_path)) as conn, transaction(
        conn, workspace.id, workspace.token
    ):
        return create_session(conn, workspace.id, body.lesson_id, body.language_mode)


@router.get("/sessions/{session_id}", response_model=dict[str, Any])
def get_session(
    session_id: SessionId, workspace: Workspace, db_path: Database
) -> dict[str, Any]:
    with closing(open_connection(db_path)) as conn:
        auth_workspace_row(conn, workspace.id, "Bearer " + workspace.token)
        return snapshot(owned_session(conn, workspace.id, session_id))


@router.post("/sessions/{session_id}/answers", response_model=dict[str, Any])
def answer(
    session_id: SessionId, body: AnswerRequest, workspace: Workspace, db_path: Database
) -> dict[str, Any]:
    with closing(open_connection(db_path)) as conn, transaction(
        conn, workspace.id, workspace.token
    ):
        return answer_session(
            conn,
            workspace.id,
            session_id,
            body.expected_epoch,
            body.question_id,
            body.answer,
        )


@router.post("/sessions/{session_id}/hints", response_model=dict[str, Any])
def hint(
    session_id: SessionId, body: EpochRequest, workspace: Workspace, db_path: Database
) -> dict[str, Any]:
    with closing(open_connection(db_path)) as conn, transaction(
        conn, workspace.id, workspace.token
    ):
        return hint_session(conn, workspace.id, session_id, body.expected_epoch)


@router.post("/sessions/{session_id}/restart", response_model=dict[str, Any])
def restart(
    session_id: SessionId, body: EpochRequest, workspace: Workspace, db_path: Database
) -> dict[str, Any]:
    with closing(open_connection(db_path)) as conn, transaction(
        conn, workspace.id, workspace.token
    ):
        return restart_session(conn, workspace.id, session_id, body.expected_epoch)
