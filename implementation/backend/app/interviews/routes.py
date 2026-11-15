"""Exported /interviews router; coordinator includes it under /api/v1."""

from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from sqlite3 import Connection
from typing import Annotated

from backend.app.db.migrations import open_connection
from backend.app.studio.routes import auth_workspace_row
from backend.app.studio.security import authenticate_workspace
from fastapi import APIRouter, Depends, Header, HTTPException, Request

from . import catalog, service
from .schemas import Answer, Catalog, Config, Finish, NewSession, Report, SessionView

router = APIRouter(prefix="/interviews", tags=["interviews"])


@dataclass(frozen=True)
class Workspace:
    id: str
    token: str = field(repr=False)


def workspace(
    request: Request,
    x_workspace_id: Annotated[str, Header(max_length=64)] = "",
    x_workspace_token: Annotated[str, Header(max_length=256)] = "",
) -> Workspace:
    if not x_workspace_id or not x_workspace_token:
        raise HTTPException(401, "Workspace capability required")
    authenticate_workspace(request, x_workspace_id, x_workspace_token)
    return Workspace(x_workspace_id, x_workspace_token)


Owner = Annotated[Workspace, Depends(workspace)]


@contextmanager
def authorized_transaction(request: Request, owner: Workspace) -> Iterator[Connection]:
    with service.transaction(request.app.state.settings.database_path) as conn:
        # Recheck capability after the write lock: pre-admission is not ownership proof.
        auth_workspace_row(conn, owner.id, "Bearer " + owner.token)
        yield conn


@router.get("/config", response_model=Config)
def config(request: Request, owner: Owner) -> dict:
    with authorized_transaction(request, owner):
        return catalog.get_config()


@router.get("/catalog", response_model=Catalog)
def question_catalog(request: Request, owner: Owner) -> dict:
    with authorized_transaction(request, owner):
        return catalog.get_catalog()


@router.post("/sessions", response_model=SessionView, response_model_exclude_none=False)
def create_session(body: NewSession, request: Request, owner: Owner) -> dict:
    with authorized_transaction(request, owner) as conn:
        return service.create(conn, owner.id, body)


@router.get("/reports/{session_id}", response_model=Report)
def get_report(session_id: str, request: Request, owner: Owner) -> Report:
    """Read an already persisted report without advancing the interview lifecycle."""
    with closing(open_connection(request.app.state.settings.database_path)) as conn:
        conn.execute("BEGIN")
        auth_workspace_row(conn, owner.id, "Bearer " + owner.token)
        session = service.owned(conn, session_id, owner.id)
        if session["state"] != "completed":
            raise HTTPException(404, "Interview report not found")
        stored = conn.execute(
            "SELECT report_json FROM interview_reports WHERE session_id=?", (session_id,)
        ).fetchone()
        if stored is None:
            raise HTTPException(404, "Interview report not found")
        return Report.model_validate_json(stored["report_json"])


@router.get("/sessions/{session_id}", response_model=SessionView)
def get_session(session_id: str, request: Request, owner: Owner) -> dict:
    hook = getattr(request.app.state, "interview_completion_hook", None)
    with authorized_transaction(request, owner) as conn:
        session = service.expire(conn, service.owned(conn, session_id, owner.id), hook)
        return service.view(conn, session)


@router.post("/sessions/{session_id}/answers", response_model=SessionView)
def answer(session_id: str, body: Answer, request: Request, owner: Owner) -> dict:
    hook = getattr(request.app.state, "interview_completion_hook", None)
    with authorized_transaction(request, owner) as conn:
        return service.submit(conn, session_id, owner.id, body, hook)


@router.post("/sessions/{session_id}/finish", response_model=Report)
def finish(session_id: str, body: Finish, request: Request, owner: Owner) -> dict:
    hook = getattr(request.app.state, "interview_completion_hook", None)
    with authorized_transaction(request, owner) as conn:
        return service.finish(conn, session_id, owner.id, body.expected_epoch, hook)
