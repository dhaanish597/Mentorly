"""Codebase calls join the shared durable ledgers and provider admission slots.

Unknown completions retain credit and leases. No provider operation is retried.
"""
from __future__ import annotations

import asyncio
from contextlib import closing, asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException

from backend.app.coaching.model_budget import daily_count
from backend.app.db.migrations import open_connection
from backend.app.speech.gatekeeper import accounted_speech_totals
from backend.app.speech.routes import _await_connected_voice
from backend.app.studio.security import authenticate_workspace
from backend.app.studio.speech import speech_slot


def idempotency_key(request):
    canonical = request.headers.get('X-Idempotency-Key')
    alternate = request.headers.get('Idempotency-Key')
    if canonical and alternate and canonical != alternate:
        raise HTTPException(422, 'Conflicting idempotency keys')
    return canonical or alternate


def owned(db, request, workspace_id, session_id):
    authenticate_workspace(request, workspace_id, request.headers.get('X-Workspace-Token', ''))
    row = db.execute('SELECT id FROM codebase_learning_sessions WHERE id=? AND workspace_id=? AND deleted_at IS NULL', (session_id, workspace_id)).fetchone()
    if not row:
        raise HTTPException(404, 'Session not found')


def begin(target, request, workspace_id, session_id):
    key = idempotency_key(request) or str(uuid4())
    if len(key) > 128:
        raise HTTPException(422, 'Idempotency key too long')
    key = session_id + ':' + key
    with closing(open_connection(target)) as db:
        db.execute('BEGIN IMMEDIATE')
        owned(db, request, workspace_id, session_id)
        if any(db.execute(f"SELECT 1 FROM {table} WHERE session_id=? AND status='UNCERTAIN'", (session_id,)).fetchone() for table in ('codebase_model_usage', 'codebase_speech_usage')):
            raise HTTPException(409, 'Uncertain provider work requires reconciliation before further dispatch')
        if db.execute("SELECT 1 FROM codebase_provider_requests WHERE id=? OR (session_id=? AND status='ACTIVE')", (key, session_id)).fetchone():
            raise HTTPException(409, 'Request already admitted; do not retry uncertain provider work')
        db.execute('INSERT INTO codebase_provider_requests VALUES(?,?,?,?,?)', (key, session_id, workspace_id, 'ACTIVE', datetime.now(timezone.utc).isoformat()))
        db.execute('INSERT INTO codebase_request_fences VALUES(?,?,?)', (key, str(uuid4()), 'ACTIVE'))
        db.commit()
    return key


def finish(target, key):
    with closing(open_connection(target)) as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute("UPDATE codebase_request_fences SET status='DONE' WHERE request_id=? AND status='ACTIVE'", (key,))
        db.execute("UPDATE codebase_provider_requests SET status='DONE' WHERE id=? AND status='ACTIVE'", (key,))
        db.commit()


def check_fence(db, key, token):
    if db.execute("UPDATE codebase_request_fences SET status=status WHERE request_id=? AND token=? AND status='ACTIVE'", (key, token)).rowcount != 1:
        raise HTTPException(409, 'Provider request fenced')


def fence_token(target, key):
    with closing(open_connection(target)) as db:
        row = db.execute("SELECT token FROM codebase_request_fences WHERE request_id=? AND status='ACTIVE'", (key,)).fetchone()
        if not row:
            raise HTTPException(409, 'Provider request fenced')
        return row[0]


def recover_fenced_request(target, key):
    """Fence an interrupted request and retain all potentially dispatched costs.

    PREPARED workers cannot pass the marker once fenced. A worker already past
    the marker can still start HTTP after this returns. Its usage remains
    UNCERTAIN and blocks subsequent provider work; external confirmation that
    the worker has stopped and provider reconciliation are required to resolve it.
    Legacy requests without a fence require manual investigation.
    """
    with closing(open_connection(target)) as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT token FROM codebase_request_fences WHERE request_id=? AND status='ACTIVE'", (key,)).fetchone()
        if not row:
            raise ValueError('Active fenced request not found; legacy requests need manual reconciliation')
        if db.execute("UPDATE codebase_request_fences SET status='FENCED' WHERE request_id=? AND token=? AND status='ACTIVE'", (key, row[0])).rowcount != 1:
            raise ValueError('Request was already fenced')
        usages = db.execute("SELECT usage_id, operation, status FROM codebase_dispatch_fences WHERE request_id=? AND token=? AND status IN ('PREPARED','DISPATCHING','SETTLED')", (key, row[0])).fetchall()
        for rid, operation, status in usages:
            table = 'codebase_model_usage' if operation == 'MODEL' else 'codebase_speech_usage'
            if status == 'PREPARED':
                db.execute(f'DELETE FROM {table} WHERE id=?', (rid,))
                if operation == 'MODEL':
                    db.execute('DELETE FROM model_dispatch_leases WHERE id=?', (rid,))
            else:
                db.execute(f"UPDATE {table} SET status='UNCERTAIN' WHERE id=?", (rid,))
                if operation == 'MODEL':
                    db.execute("UPDATE model_dispatch_leases SET status='UNCERTAIN' WHERE id=?", (rid,))
                    db.execute("INSERT INTO model_dispatch_leases SELECT id, 'UNCERTAIN', created_at FROM codebase_model_usage WHERE id=? AND NOT EXISTS (SELECT 1 FROM model_dispatch_leases WHERE id=?)", (rid, rid))
            db.execute("UPDATE codebase_dispatch_fences SET status='FENCED' WHERE usage_id=?", (rid,))
        db.execute("UPDATE codebase_provider_requests SET status='DONE' WHERE id=? AND status='ACTIVE'", (key,))
        db.commit()



def reserve(target, request, workspace_id, session_id, operation, seconds, chars, calls=1, *, request_key=None, token=None):
    settings = request.app.state.settings
    now = datetime.now(timezone.utc).isoformat()
    rid = str(uuid4())
    with closing(open_connection(target)) as db:
        db.execute('BEGIN IMMEDIATE')
        owned(db, request, workspace_id, session_id)
        if request_key is not None:
            check_fence(db, request_key, token)
        if operation == 'MODEL':
            count = db.execute('SELECT count(*) FROM codebase_model_usage WHERE session_id=?', (session_id,)).fetchone()[0]
            active = db.execute('SELECT count(*) FROM model_dispatch_leases').fetchone()[0]
            if count >= settings.model_session_call_limit or daily_count(db, now) >= settings.model_daily_call_limit or active >= settings.model_max_concurrency:
                raise HTTPException(429, 'Model quota or concurrency exhausted')
            db.execute('INSERT INTO codebase_model_usage VALUES(?,?,?,?,?)', (rid, session_id, operation, 'RESERVED', now))
            db.execute('INSERT INTO model_dispatch_leases VALUES(?,?,?)', (rid, 'RESERVED', now))
        else:
            gate = request.app.state.speech.gatekeeper
            total_seconds, total_chars = accounted_speech_totals(db)
            usage = db.execute('SELECT COALESCE(SUM(stt_seconds),0), COALESCE(SUM(tts_chars),0) FROM codebase_speech_usage WHERE session_id=?', (session_id,)).fetchone()
            daily_calls = 0
            for table in ('usage_reservations','studio_speech_usage','module_speech_usage','codebase_speech_usage'):
                daily_calls += db.execute(f"SELECT COALESCE(SUM(request_count),0) FROM {table} WHERE status IN ('RESERVED','COMMITTED','UNCERTAIN') AND date(created_at)=date(?)", (now,)).fetchone()[0]
            daily_calls += db.execute('SELECT COALESCE(SUM(request_count),0) FROM studio_speech_deleted_daily WHERE day=date(?)', (now,)).fetchone()[0]
            if usage[0]+seconds > settings.max_stt_seconds_per_session or usage[1]+chars > settings.max_tts_chars_per_session or total_seconds+seconds > gate.max_stt_seconds_budget or total_chars+chars > gate.max_tts_chars_budget or daily_calls+calls > settings.global_daily_call_limit:
                raise HTTPException(429, 'Speech quota exhausted')
            db.execute('INSERT INTO codebase_speech_usage VALUES(?,?,?,?,?,?,?,?)', (rid, session_id, operation, seconds, chars, calls, 'RESERVED', now))
        if request_key is not None:
            db.execute('INSERT INTO codebase_dispatch_fences VALUES(?,?,?,?,?)', (rid, request_key, token, operation, 'PREPARED'))
        db.commit()
    return rid


def settle(target, rid, operation, status):
    table = 'codebase_model_usage' if operation == 'MODEL' else 'codebase_speech_usage'
    with closing(open_connection(target)) as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('UPDATE codebase_dispatch_fences SET status=status WHERE usage_id=?', (rid,))
        fence = db.execute('SELECT status FROM codebase_dispatch_fences WHERE usage_id=?', (rid,)).fetchone()
        if fence and fence[0] == 'FENCED':
            db.commit()
            return
        if status == 'UNDISPATCHED':
            db.execute(f'DELETE FROM {table} WHERE id=?', (rid,))
        else:
            db.execute(f'UPDATE {table} SET status=? WHERE id=?', (status, rid))
        if operation == 'MODEL':
            if status == 'UNCERTAIN':
                db.execute("UPDATE model_dispatch_leases SET status='UNCERTAIN' WHERE id=?", (rid,))
            else:
                db.execute('DELETE FROM model_dispatch_leases WHERE id=?', (rid,))
        if fence:
            db.execute("UPDATE codebase_dispatch_fences SET status='SETTLED' WHERE usage_id=?", (rid,))
        db.commit()


def mark_dispatching(target, rid, request_key, token):
    with closing(open_connection(target)) as db:
        db.execute('BEGIN IMMEDIATE')
        check_fence(db, request_key, token)
        result = db.execute("UPDATE codebase_dispatch_fences SET status='DISPATCHING' WHERE usage_id=? AND request_id=? AND token=? AND status='PREPARED'", (rid, request_key, token))
        if result.rowcount != 1:
            raise HTTPException(409, 'Provider dispatch fenced')
        db.commit()


@asynccontextmanager
async def model_slot():
    yield


async def run(target, request, workspace_id, session_id, operation, dispatch, *, seconds=0, chars=0, calls=1, request_key=None, token=None):
    if request is None or not request_key or not token:
        raise HTTPException(503, 'Fenced authorized request context required for cloud providers')
    rid = reserve(target, request, workspace_id, session_id, operation, seconds, chars, calls, request_key=request_key, token=token)
    status = 'UNDISPATCHED'
    try:
        async with (model_slot() if operation == 'MODEL' else speech_slot(request)):
            with closing(open_connection(target)) as db:
                owned(db, request, workspace_id, session_id)
            if request_key is not None:
                mark_dispatching(target, rid, request_key, token)
            status = 'UNCERTAIN'
            if operation != 'MODEL':
                request.app.state.speech.gatekeeper.mark_provider_dispatch()
            result = await asyncio.wait_for(_await_connected_voice(request, dispatch()), timeout=60)
            if operation != 'MODEL':
                request.app.state.speech.gatekeeper.mark_provider_complete()
            status = 'COMMITTED'
            with closing(open_connection(target)) as db:
                owned(db, request, workspace_id, session_id)
            return result
    finally:
        settle(target, rid, operation, status)
