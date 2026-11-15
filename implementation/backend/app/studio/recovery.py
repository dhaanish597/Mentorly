"""Opt-in cross-browser recovery with credential rotation and no token replay."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import uuid
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.app.db.migrations import open_connection
from backend.app.studio.routes import auth_workspace_row, digest_token, mutation
from backend.app.studio.security import authenticate_workspace

router = APIRouter(prefix='/studio', tags=['workspace recovery'])
TOKEN = r'^[A-Za-z0-9_-]{43,128}$'


class RecoverySetup(BaseModel):
    model_config = ConfigDict(extra='forbid')
    recovery_token: str = Field(pattern=TOKEN, repr=False)


class RecoveryRestore(RecoverySetup):
    workspace_token: str = Field(pattern=TOKEN, repr=False)


class RecoveryInfo(BaseModel):
    enabled: bool
    expires_at: str | None = None
    generation: int | None = None


class RestoredWorkspace(BaseModel):
    workspace_id: str
    expires_at: str


class SessionCapability(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session_token: str = Field(min_length=32, max_length=256, repr=False)


class StudioSessionReference(BaseModel):
    id: str
    mode: str
    scenario_id: str
    scenario_version: str
    expires_at: str
    diagram_revision: int
    state: str


class DsaSessionReference(BaseModel):
    id: str
    exercise_id: str
    spec_version: str
    expires_at: str


class WorkspaceArchiveData(BaseModel):
    studio_sessions: list[StudioSessionReference]
    dsa_sessions: list[DsaSessionReference]
    learning_sessions: list[dict[str, Any]]
    learning_answers: list[dict[str, Any]]
    interviews: list[dict[str, Any]]
    interview_reports: list[dict[str, Any]]


class WorkspaceArchive(BaseModel):
    format: str = 'viva-workspace-archive'
    schema_version: int = 1
    workspace_id: str
    content_sha256: str
    data: WorkspaceArchiveData


def _hash(value: str) -> str:
    return hashlib.sha256(('viva-workspace-recovery-v1:' + value).encode()).hexdigest()


def _time() -> datetime:
    return datetime.now(timezone.utc)


def _target(request: Request):
    return request.app.state.settings.database_target


@router.get('/workspaces/{wid}/recovery', response_model=RecoveryInfo)
def recovery_info(wid: str, request: Request, authorization: str = Header(default='')):
    with closing(open_connection(_target(request))) as conn:
        auth_workspace_row(conn, wid, authorization)
        row = conn.execute('SELECT expires_at,generation FROM workspace_recovery WHERE workspace_id=?', (wid,)).fetchone()
        return {'enabled': bool(row and datetime.fromisoformat(row['expires_at']) > _time()),
                'expires_at': row['expires_at'] if row else None,
                'generation': row['generation'] if row else None}


@router.put('/workspaces/{wid}/recovery', response_model=RecoveryInfo)
def configure_recovery(wid: str, body: RecoverySetup, request: Request,
                       authorization: str = Header(default=''), x_idempotency_key: str = Header(default='')):
    authenticate_workspace(request, wid, authorization.removeprefix('Bearer '))
    digest = _hash(body.recovery_token)
    def write(conn):
        owner = auth_workspace_row(conn, wid, authorization)
        expiry = min(datetime.fromisoformat(owner['expires_at']), _time() + timedelta(days=30)).isoformat()
        conn.execute('INSERT INTO workspace_recovery(workspace_id,credential_hash,expires_at,updated_at) VALUES(?,?,?,?) '
                     'ON CONFLICT(workspace_id) DO UPDATE SET credential_hash=excluded.credential_hash,'
                     'expires_at=excluded.expires_at,updated_at=excluded.updated_at,generation=workspace_recovery.generation+1',
                     (wid, digest, expiry, _time().isoformat()))
        generation = conn.execute('SELECT generation FROM workspace_recovery WHERE workspace_id=?', (wid,)).fetchone()[0]
        return {'enabled': True, 'expires_at': expiry, 'generation': generation}
    # Replay stores only digest/metadata; the browser owns the once-shown secret.
    return mutation(request, wid, x_idempotency_key, {'recovery_hash': digest}, write)


@router.delete('/workspaces/{wid}/recovery', response_model=RecoveryInfo)
def revoke_recovery(wid: str, request: Request, authorization: str = Header(default=''),
                    x_idempotency_key: str = Header(default='')):
    authenticate_workspace(request, wid, authorization.removeprefix('Bearer '))
    def revoke(conn):
        auth_workspace_row(conn, wid, authorization)
        conn.execute('DELETE FROM workspace_recovery WHERE workspace_id=?', (wid,))
        return {'enabled': False, 'expires_at': None, 'generation': None}
    return mutation(request, wid, x_idempotency_key, {}, revoke)


@router.post('/workspaces/{wid}/recover', response_model=RestoredWorkspace)
def restore_workspace(wid: str, body: RecoveryRestore, request: Request):
    # All attempts consume durable quotas, including nonexistent workspace IDs.
    try:
        wid = str(uuid.UUID(wid))
    except ValueError:
        raise HTTPException(401, 'Recovery credential is invalid or expired') from None
    current = _time()
    cutoff = (current - timedelta(minutes=1)).isoformat()
    subject = hashlib.sha256((request.client.host if request.client else 'unknown').encode()).hexdigest()
    with closing(open_connection(_target(request))) as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('DELETE FROM workspace_recovery_attempts WHERE created_at<?', (cutoff,))
        total = conn.execute('SELECT count(*) FROM workspace_recovery_attempts').fetchone()[0]
        own = conn.execute('SELECT count(*) FROM workspace_recovery_attempts WHERE subject_hash=? OR workspace_id=?', (subject, wid)).fetchone()[0]
        if total >= 60 or own >= 8:
            conn.rollback()
            raise HTTPException(429, 'Recovery is temporarily rate limited', headers={'Retry-After': '60'})
        conn.execute('INSERT INTO workspace_recovery_attempts VALUES(?,?,?,?)', (str(uuid.uuid4()), subject, wid, current.isoformat()))
        row = conn.execute('SELECT r.credential_hash,r.expires_at,w.deleted_at,w.expires_at workspace_expiry '
                           'FROM workspace_recovery r JOIN studio_workspaces w ON w.id=r.workspace_id WHERE r.workspace_id=?', (wid,)).fetchone()
        matches = hmac.compare_digest(row['credential_hash'] if row else '0' * 64, _hash(body.recovery_token))
        if not row or not matches or row['deleted_at'] or min(datetime.fromisoformat(row['expires_at']), datetime.fromisoformat(row['workspace_expiry'])) <= current:
            conn.commit()  # Invalid attempts cannot roll back the rate ledger.
            raise HTTPException(401, 'Recovery credential is invalid or expired')
        replacement = digest_token(body.workspace_token)
        if hmac.compare_digest(replacement, digest_token(body.recovery_token)):
            conn.commit()
            raise HTTPException(422, 'Use a separate workspace capability')
        conn.execute('UPDATE studio_workspaces SET token_hash=? WHERE id=?', (replacement, wid))
        conn.commit()
        return {'workspace_id': wid, 'expires_at': row['workspace_expiry']}


@router.post('/workspaces/{wid}/dsa-sessions/{sid}/link')
def link_dsa(wid: str, sid: str, body: SessionCapability, request: Request,
             authorization: str = Header(default=''), x_idempotency_key: str = Header(default='')):
    authenticate_workspace(request, wid, authorization.removeprefix('Bearer '))
    def link(conn):
        auth_workspace_row(conn, wid, authorization)
        row = conn.execute('SELECT token_hash,expires_at,deleted_at FROM sessions WHERE id=?', (sid,)).fetchone()
        matches = hmac.compare_digest(row['token_hash'] if row else '0' * 64, digest_token(body.session_token))
        if not row or not matches or row['deleted_at'] or datetime.fromisoformat(row['expires_at']) <= _time():
            raise HTTPException(401, 'A valid session capability is required')
        prior = conn.execute('SELECT workspace_id FROM workspace_dsa_sessions WHERE session_id=?', (sid,)).fetchone()
        if prior and prior['workspace_id'] != wid:
            raise HTTPException(409, 'Session already belongs to another workspace')
        conn.execute('INSERT INTO workspace_dsa_sessions VALUES(?,?,?) ON CONFLICT(session_id) DO NOTHING', (sid, wid, _time().isoformat()))
        return {'linked': True}
    return mutation(request, wid, x_idempotency_key, {'sid': sid, 'token_hash': digest_token(body.session_token)}, link)


@router.post('/workspaces/{wid}/sessions/{sid}/capability')
def renew_session(wid: str, sid: str, body: SessionCapability, request: Request,
                  authorization: str = Header(default=''), x_idempotency_key: str = Header(default='')):
    authenticate_workspace(request, wid, authorization.removeprefix('Bearer '))
    def renew(conn):
        auth_workspace_row(conn, wid, authorization)
        studio = conn.execute('SELECT id FROM studio_sessions WHERE id=? AND workspace_id=? AND deleted_at IS NULL AND expires_at>?', (sid, wid, _time().isoformat())).fetchone()
        dsa = conn.execute('SELECT s.id FROM sessions s JOIN workspace_dsa_sessions w ON s.id=w.session_id WHERE s.id=? AND w.workspace_id=? AND s.deleted_at IS NULL AND s.expires_at>?', (sid, wid, _time().isoformat())).fetchone()
        if not studio and not dsa:
            raise HTTPException(404, 'Owned session not found')
        # Rotation never changes code, revision or authoritative learning records.
        table = 'studio_sessions' if studio else 'sessions'
        conn.execute(f'UPDATE {table} SET token_hash=? WHERE id=?', (digest_token(body.session_token), sid))
        return {'renewed': True, 'kind': 'studio' if studio else 'dsa'}
    return mutation(request, wid, x_idempotency_key, {'sid': sid, 'token_hash': digest_token(body.session_token)}, renew)


@router.get('/workspaces/{wid}/archive', response_model=WorkspaceArchive)
def export_workspace(wid: str, request: Request, authorization: str = Header(default='')):
    with closing(open_connection(_target(request))) as conn:
        conn.execute('BEGIN')
        auth_workspace_row(conn, wid, authorization)
        data = {}
        selections = {
            'studio_sessions': 'SELECT id,mode,scenario_id,scenario_version,expires_at,diagram_revision,state FROM studio_sessions WHERE workspace_id=? AND deleted_at IS NULL AND expires_at>?',
            'dsa_sessions': 'SELECT s.id,s.exercise_id,s.spec_version,s.expires_at FROM sessions s JOIN workspace_dsa_sessions w ON w.session_id=s.id WHERE w.workspace_id=? AND s.deleted_at IS NULL AND s.expires_at>?',
            'learning_sessions': 'SELECT id,lesson_id,content_hash,run,epoch,state FROM learning_sessions WHERE workspace_id=?',
            'learning_answers': 'SELECT a.id,a.session_id,a.question_id,a.answer,a.correct,a.evaluation_json FROM learning_answers a WHERE a.workspace_id=?',
            'interviews': 'SELECT id,state,type,difficulty,topics_json,language_mode FROM interview_sessions WHERE workspace_id=?',
            'interview_reports': 'SELECT r.session_id,r.report_json FROM interview_reports r JOIN interview_sessions s ON s.id=r.session_id WHERE s.workspace_id=?',
        }
        for name, query in selections.items():
            params = (wid, _time().isoformat()) if name in {'studio_sessions', 'dsa_sessions'} else (wid,)
            rows = conn.execute(query + ' LIMIT 10001', params).fetchall()
            if len(rows) > 10000:
                raise HTTPException(413, 'Workspace export exceeds the bounded archive; export individual sessions')
            data[name] = [dict(row) for row in rows]
        raw = json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        if len(raw.encode()) > 10_000_000:
            raise HTTPException(413, 'Workspace export exceeds the bounded archive; export individual sessions')
        return {'format': 'viva-workspace-archive', 'schema_version': 1, 'workspace_id': wid,
                'content_sha256': hashlib.sha256(raw.encode()).hexdigest(), 'data': data}
