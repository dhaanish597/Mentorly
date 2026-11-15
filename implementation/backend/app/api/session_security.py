"""Capability authentication, bounded requests, and durable mutation replay."""
from __future__ import annotations
from backend.app.db.migrations import database_target
import asyncio
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
from weakref import WeakValueDictionary
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from backend.app.db.repository import (
    SQLiteRepository, IdempotencyConflictError, RevisionConflictError,
    SessionNotFoundError, SessionDeletedError,
)
from backend.app.core.logging import get_request_id as request_id

_SESSION_PATH = re.compile(r'^/api/v1/sessions/([^/]+)(?:/|$)')

def install_session_security(app, settings):
    locks: WeakValueDictionary[tuple[str, str], asyncio.Lock] = WeakValueDictionary()

    def error(status, code, message):
        return JSONResponse({'code': code, 'message': message, 'retryable': False, 'request_id': request_id(), 'turn_id': None, 'job_id': None}, status_code=status)

    @app.middleware('http')
    async def session_security(request: Request, call_next):
        match = _SESSION_PATH.match(request.url.path)
        if not match or request.method == 'OPTIONS':
            return await call_next(request)
        sid = match.group(1)
        repo = SQLiteRepository(database_target(settings))
        repo.initialize()
        row = repo.get_session(sid, include_deleted=True)
        header = request.headers.get('authorization', '')
        token = header[7:] if header.startswith('Bearer ') else ''
        digest = hashlib.sha256(token.encode()).hexdigest()
        if row is None or not token or not hmac.compare_digest(row.token_hash, digest):
            return error(401, 'SESSION_AUTH_REQUIRED', 'A valid session capability is required.')
        if row.deleted_at:
            return error(410, 'SESSION_DELETED', 'This session has been deleted.')
        if datetime.fromisoformat(row.expires_at) <= datetime.now(timezone.utc):
            return error(410, 'SESSION_EXPIRED', 'This session has expired.')
        if request.method in ('GET', 'HEAD'):
            return await call_next(request)
        key = request.headers.get('x-idempotency-key', '')
        if not 8 <= len(key) <= 128:
            return error(400, 'IDEMPOTENCY_KEY_REQUIRED', 'Mutations require X-Idempotency-Key (8–128 characters).')
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 2_100_000:
                return error(413, 'REQUEST_TOO_LARGE', 'The request exceeds the capture limit.')
        request._body = bytes(body)
        request_digest = hashlib.sha256(body).hexdigest()
        # A per-key lock serializes duplicate deliveries; SQLite retains replay across restart.
        lock_key = (sid, key)
        lock = locks.setdefault(lock_key, asyncio.Lock())
        async with lock:
            try:
                cached = repo.check_idempotency(sid, method=request.method, route=request.url.path,
                                               idempotency_key=key, request_digest=request_digest)
            except IdempotencyConflictError:
                return error(409, 'IDEMPOTENCY_CONFLICT', 'The key was already used with another request.')
            if cached.outcome == 'HIT' and cached.record and cached.record.response_json:
                saved = json.loads(cached.record.response_json)
                if saved.get('stream_completed'):
                    return error(409, 'STREAM_ALREADY_DELIVERED', 'This stream was already delivered; replay the displayed coaching text.')
                if '/speech/' in request.url.path and 200 <= saved['status'] < 300:
                    # A delivered audio replay remains authorized only for the current revision.
                    from backend.app.models.domain import RevisionRef
                    from backend.app.orchestration.state_machine import CoordinatorStateMachine
                    try:
                        payload = json.loads(request._body)
                        if not isinstance(payload, dict) or 'revision' not in payload:
                            raise ValueError('Speech replay requires a revision')
                        revision = RevisionRef.model_validate(payload['revision'])
                        CoordinatorStateMachine(repo).assert_revision_matches(sid, revision)
                    except (ValueError, RevisionConflictError, SessionNotFoundError, SessionDeletedError):
                        return error(409, 'REVISION_CONFLICT', 'This voice response is superseded; restore the current problem.')
                return Response(base64.b64decode(saved['body']), status_code=saved['status'], headers=saved['headers'])
            if cached.outcome == 'HIT':
                return error(409, 'ACTION_IN_PROGRESS_OR_UNCERTAIN', 'The earlier action is pending or its completion is uncertain; restore the session before retrying.')
            expires = (datetime.now(timezone.utc)+timedelta(hours=24)).isoformat()
            repo.save_idempotency(sid, method=request.method, route=request.url.path, idempotency_key=key,
                request_digest=request_digest, status='IN_PROGRESS', response_json=None, expires_at=expires)
            response = await call_next(request)
            if response.headers.get('content-type','').startswith('text/event-stream'):
                original = response.body_iterator
                async def track_stream():
                    completed = False
                    try:
                        async for chunk in original:
                            yield chunk
                        completed = True
                    finally:
                        try:
                            repo.save_idempotency(sid, method=request.method, route=request.url.path, idempotency_key=key,
                                request_digest=request_digest, status='COMPLETE' if completed else 'UNCERTAIN',
                                response_json=json.dumps({'stream_completed':True}) if completed else None, expires_at=expires)
                        except Exception:
                            pass  # Tombstoned sessions retain no private replay payload.
                response.body_iterator = track_stream()
                return response
            payload = b''.join([part async for part in response.body_iterator])
            headers = {k:v for k,v in response.headers.items() if k.lower() not in ('content-length','transfer-encoding')}
            # Deletion has tombstoned the row and is already repeat-safe (410 on retries).
            if request.method != 'DELETE' and response.status_code < 500:
                repo.save_idempotency(sid, method=request.method, route=request.url.path, idempotency_key=key,
                    request_digest=request_digest, status='COMPLETE',
                    response_json=json.dumps({'status':response.status_code,'headers':headers,'body':base64.b64encode(payload).decode()}),
                    expires_at=(datetime.now(timezone.utc)+timedelta(hours=24)).isoformat())
            return Response(payload, status_code=response.status_code, headers=headers)
