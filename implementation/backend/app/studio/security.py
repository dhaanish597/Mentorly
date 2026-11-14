"""Capability checks for the isolated studio aggregate."""
import hashlib
import hmac
from datetime import datetime, timezone
from fastapi import HTTPException, Request
from contextlib import closing
from backend.app.db.migrations import open_connection


def digest_token(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def authenticate_workspace(request: Request, workspace_id: str, token: str) -> None:
    with closing(open_connection(request.app.state.settings.database_path)) as conn:
        row = conn.execute('SELECT token_hash,expires_at,deleted_at FROM studio_workspaces WHERE id=?', (workspace_id,)).fetchone()
    expected = row['token_hash'] if row else '0' * 64
    valid = hmac.compare_digest(expected, digest_token(token))
    if not row or not token or not valid or row['deleted_at'] or datetime.fromisoformat(row['expires_at']) <= datetime.now(timezone.utc):
        raise HTTPException(401, 'Invalid workspace capability')


def purge_speech_usage(conn, session_id: str) -> None:
    """Retain anonymous daily accounting while removing session-bound usage."""
    rows=conn.execute("SELECT date(created_at) day,SUM(request_count) n FROM studio_speech_usage WHERE session_id=? AND status IN ('RESERVED','COMMITTED','UNCERTAIN') GROUP BY date(created_at)",(session_id,)).fetchall()
    for row in rows:
        conn.execute('INSERT INTO studio_speech_deleted_daily VALUES(?,?) ON CONFLICT(day) DO UPDATE SET request_count=request_count+excluded.request_count',(row['day'],row['n']))
    conn.execute('DELETE FROM studio_speech_usage WHERE session_id=?',(session_id,))
