"""Exported /interviews router; coordinator includes it under /api/v1."""
from dataclasses import dataclass
from typing import Annotated
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from backend.app.studio.security import authenticate_workspace
from . import catalog, service
from .schemas import Answer, Catalog, Config, Finish, NewSession, Report, SessionView

router = APIRouter(prefix='/interviews', tags=['interviews'])


@dataclass(frozen=True)
class Workspace:
    id: str


def workspace(request: Request,
              x_workspace_id: Annotated[str, Header(max_length=64)] = '',
              x_workspace_token: Annotated[str, Header(max_length=256)] = '') -> Workspace:
    if not x_workspace_id or not x_workspace_token:
        raise HTTPException(401, 'Workspace capability required')
    authenticate_workspace(request, x_workspace_id, x_workspace_token)
    return Workspace(x_workspace_id)


Owner = Annotated[Workspace, Depends(workspace)]


@router.get('/config', response_model=Config)
def config(owner: Owner) -> dict:
    return catalog.get_config()


@router.get('/catalog', response_model=Catalog)
def question_catalog(owner: Owner) -> dict:
    return catalog.get_catalog()


@router.post('/sessions', response_model=SessionView, response_model_exclude_none=False)
def create_session(body: NewSession, request: Request, owner: Owner) -> dict:
    with service.transaction(request.app.state.settings.database_path) as conn:
        return service.create(conn, owner.id, body)


@router.get('/sessions/{session_id}', response_model=SessionView)
def get_session(session_id: str, request: Request, owner: Owner) -> dict:
    hook = getattr(request.app.state, 'interview_completion_hook', None)
    with service.transaction(request.app.state.settings.database_path) as conn:
        session = service.expire(conn, service.owned(conn, session_id, owner.id), hook)
        return service.view(conn, session)


@router.post('/sessions/{session_id}/answers', response_model=SessionView)
def answer(session_id: str, body: Answer, request: Request, owner: Owner) -> dict:
    hook = getattr(request.app.state, 'interview_completion_hook', None)
    with service.transaction(request.app.state.settings.database_path) as conn:
        return service.submit(conn, session_id, owner.id, body, hook)


@router.post('/sessions/{session_id}/finish', response_model=Report)
def finish(session_id: str, body: Finish, request: Request, owner: Owner) -> dict:
    hook = getattr(request.app.state, 'interview_completion_hook', None)
    with service.transaction(request.app.state.settings.database_path) as conn:
        return service.finish(conn, session_id, owner.id, body.expected_epoch, hook)
