"""Durable model-call admission; deletion retains only anonymous daily totals."""
from contextlib import closing
from datetime import datetime, timezone
import uuid

from fastapi import HTTPException

from backend.app.db.migrations import open_connection


def reserve(conn, session_id, epoch, idempotency_key, settings):
    """Called inside the same IMMEDIATE transaction as mutation reservation."""
    if not conn.in_transaction:
        raise RuntimeError("Model admission requires a transaction")
    timestamp = datetime.now(timezone.utc).isoformat()
    session_count = conn.execute('SELECT count(*) FROM studio_model_usage WHERE session_id=?', (session_id,)).fetchone()[0]
    global_count = conn.execute('SELECT count(*) FROM studio_model_usage WHERE date(created_at)=date(?)', (timestamp,)).fetchone()[0]
    global_count += conn.execute('SELECT COALESCE(SUM(request_count),0) FROM studio_model_deleted_daily WHERE day=date(?)', (timestamp,)).fetchone()[0]
    global_count += conn.execute('SELECT count(*) FROM dsa_model_usage WHERE date(created_at)=date(?)', (timestamp,)).fetchone()[0]
    global_count += conn.execute('SELECT COALESCE(SUM(request_count),0) FROM dsa_model_deleted_daily WHERE day=date(?)', (timestamp,)).fetchone()[0]
    active = conn.execute('SELECT count(*) FROM model_dispatch_leases').fetchone()[0]
    if session_count >= settings.model_session_call_limit or global_count >= settings.model_daily_call_limit:
        raise HTTPException(429, 'Model feedback budget exhausted; authored coaching and text remain available')
    if active >= settings.model_max_concurrency:
        raise HTTPException(429, 'Model feedback is busy; retry after the current request finishes')
    reservation_id = str(uuid.uuid4())
    conn.execute('INSERT INTO studio_model_usage VALUES(?,?,?,?,?,?)',
                 (reservation_id, session_id, epoch, idempotency_key, 'RESERVED', timestamp))
    conn.execute('INSERT INTO model_dispatch_leases(id,status,created_at) VALUES(?,?,?)', (reservation_id, 'RESERVED', timestamp))
    return reservation_id


def settle(database_path, reservation_id, status):
    if status not in ('COMMITTED', 'UNCERTAIN'):
        raise ValueError('Invalid model accounting status')
    with closing(open_connection(database_path)) as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute("UPDATE studio_model_usage SET status=? WHERE id=? AND status='RESERVED'", (status, reservation_id))
        if status == 'COMMITTED':
            conn.execute('DELETE FROM model_dispatch_leases WHERE id=?', (reservation_id,))
        else:
            conn.execute("UPDATE model_dispatch_leases SET status='UNCERTAIN' WHERE id=?", (reservation_id,))
        conn.commit()


def purge_session(conn, session_id):
    """Caller transaction removes private linkage without resetting daily spend."""
    rows = conn.execute('SELECT date(created_at) AS day,count(*) AS calls FROM studio_model_usage WHERE session_id=? GROUP BY date(created_at)', (session_id,)).fetchall()
    for row in rows:
        conn.execute('INSERT INTO studio_model_deleted_daily(day,request_count) VALUES(?,?) ON CONFLICT(day) DO UPDATE SET request_count=request_count+excluded.request_count', (row['day'], row['calls']))
    conn.execute('DELETE FROM studio_model_usage WHERE session_id=?', (session_id,))


def recover(conn, *, stale_before=None):
    """A crashed request is uncertain and is never silently redispatched."""
    clause = ' AND created_at<?' if stale_before is not None else ''
    parameters = (stale_before,) if stale_before is not None else ()
    conn.execute("UPDATE studio_model_usage SET status='UNCERTAIN' WHERE status='RESERVED'" + clause, parameters)
    conn.execute("UPDATE model_dispatch_leases SET status='UNCERTAIN' WHERE status='RESERVED'" + clause, parameters)
