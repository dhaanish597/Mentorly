"""Learning API. Mount this router under /api/v1; no app construction side effects."""

from __future__ import annotations

import json
from contextlib import closing
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from backend.app.assessments import review
from backend.app.db.migrations import database_target, open_connection
from backend.app.studio.routes import auth_workspace_row
from backend.app.studio.security import authenticate_workspace
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from .catalog import evaluate_answer, public_catalog
from .progress import progress_snapshot
from .schemas import LearningSessionView
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
    option_id: str | None = Field(default=None, min_length=1, max_length=128)
    explanation: str | None = Field(default=None, min_length=1, max_length=12000)
    allow_external: bool = False


@dataclass(frozen=True)
class WorkspaceScope:
    id: str
    token: str


def database(request: Request) -> str:
    # Pass a path across dependency worker threads, never a thread-bound connection.
    return database_target(request.app.state.settings)


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


@router.post("/sessions", response_model=LearningSessionView)
def new_session(
    body: NewSession, workspace: Workspace, db_path: Database
) -> dict[str, Any]:
    with (
        closing(open_connection(db_path)) as conn,
        transaction(conn, workspace.id, workspace.token),
    ):
        return create_session(conn, workspace.id, body.lesson_id, body.language_mode)


@router.get("/sessions/{session_id}", response_model=LearningSessionView)
def get_session(
    session_id: SessionId, workspace: Workspace, db_path: Database
) -> dict[str, Any]:
    with closing(open_connection(db_path)) as conn:
        auth_workspace_row(conn, workspace.id, "Bearer " + workspace.token)
        return snapshot(owned_session(conn, workspace.id, session_id))


@router.post("/sessions/{session_id}/answers", response_model=LearningSessionView)
async def answer(
    session_id: SessionId,
    body: AnswerRequest,
    workspace: Workspace,
    db_path: Database,
    request: Request,
) -> dict[str, Any]:
    semantic = None
    if body.explanation:
        from .service import require_epoch, require_prerequisites

        settings = request.app.state.settings
        status = review.readiness(settings, body.allow_external)
        reservation = None
        with (
            closing(open_connection(db_path)) as conn,
            transaction(conn, workspace.id, workspace.token),
        ):
            current = owned_session(conn, workspace.id, session_id)
            require_epoch(current, body.expected_epoch)
            lesson = json.loads(current["lesson_json"])
            require_prerequisites(conn, workspace.id, lesson)
            if lesson["question"]["id"] != body.question_id:
                raise HTTPException(409, "Question does not match the pinned lesson")
            context = {
                "question": lesson["question"]["prompt"],
                "answer": body.explanation,
            }
            objective = evaluate_answer(lesson["question"], body.answer, body.option_id)
            if objective["correct"]:
                context["lesson_rationale"] = lesson["question"]["rationale"]
            if status == "MODEL_ASSISTED":
                try:
                    reservation = review.reserve(
                        conn,
                        workspace.id,
                        "learning",
                        session_id,
                        body.expected_epoch,
                        context,
                        settings,
                    )
                except HTTPException as exc:
                    if exc.status_code != 429:
                        raise
                    status = "MODEL_BUDGET_EXHAUSTED"
        semantic = (
            await review.interpret(settings, context, body.expected_epoch, reservation)
            if reservation
            else review.initial_review(context, body.expected_epoch, status)
        )
    with (
        closing(open_connection(db_path)) as conn,
        transaction(conn, workspace.id, workspace.token),
    ):
        return answer_session(
            conn,
            workspace.id,
            session_id,
            body.expected_epoch,
            body.question_id,
            body.answer,
            body.explanation,
            semantic,
            body.option_id,
        )


@router.post("/sessions/{session_id}/hints", response_model=LearningSessionView)
def hint(
    session_id: SessionId, body: EpochRequest, workspace: Workspace, db_path: Database
) -> dict[str, Any]:
    with (
        closing(open_connection(db_path)) as conn,
        transaction(conn, workspace.id, workspace.token),
    ):
        return hint_session(conn, workspace.id, session_id, body.expected_epoch)


@router.post("/sessions/{session_id}/restart", response_model=LearningSessionView)
def restart(
    session_id: SessionId, body: EpochRequest, workspace: Workspace, db_path: Database
) -> dict[str, Any]:
    with (
        closing(open_connection(db_path)) as conn,
        transaction(conn, workspace.id, workspace.token),
    ):
        return restart_session(conn, workspace.id, session_id, body.expected_epoch)
