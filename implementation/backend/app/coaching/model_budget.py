"""Shared admission for legacy interpretation/phrasing; never retry uncertain work."""
from contextlib import closing
from datetime import datetime, timezone
from uuid import uuid4

from backend.app.db.migrations import open_connection
from backend.app.db.repository import RevisionConflictError


def daily_count(db, timestamp):
    total = 0
    for scope in ('studio', 'dsa', 'assessment', 'legacy'):
        usage, deleted = f'{scope}_model_usage', f'{scope}_model_deleted_daily'
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (usage,)).fetchone():
            total += db.execute(f'SELECT count(*) FROM {usage} WHERE date(created_at)=date(?)',(timestamp,)).fetchone()[0]
            total += db.execute(f'SELECT COALESCE(SUM(request_count),0) FROM {deleted} WHERE day=date(?)',(timestamp,)).fetchone()[0]
    return total


def assert_current(settings, session_id, revision):
    with closing(open_connection(settings.database_target)) as db:
        row = db.execute('SELECT deleted_at,expires_at,active_code_version_id,active_turn_generation FROM sessions WHERE id=?',(session_id,)).fetchone()
        if not row or row['deleted_at'] or datetime.fromisoformat(row['expires_at']) <= datetime.now(timezone.utc):
            raise RevisionConflictError('Model owner is unavailable')
        if revision and (row['active_code_version_id'] != revision.code_version_id or row['active_turn_generation'] != revision.turn_generation):
            raise RevisionConflictError('Model evidence revision is superseded')


def reserve(settings, session_id, operation, revision=None):
    assert_current(settings, session_id, revision)
    timestamp = datetime.now(timezone.utc).isoformat()
    with closing(open_connection(settings.database_target)) as db:
        db.execute('BEGIN IMMEDIATE')
        # Repeat ownership/revision checks inside admission transaction.
        row = db.execute('SELECT deleted_at,expires_at,active_code_version_id,active_turn_generation FROM sessions WHERE id=?',(session_id,)).fetchone()
        if not row or row['deleted_at'] or datetime.fromisoformat(row['expires_at']) <= datetime.now(timezone.utc):
            raise RevisionConflictError('Model owner is unavailable')
        if revision and (row['active_code_version_id'] != revision.code_version_id or row['active_turn_generation'] != revision.turn_generation):
            raise RevisionConflictError('Model evidence revision is superseded')
        session_count = db.execute('SELECT count(*) FROM legacy_model_usage WHERE session_id=?',(session_id,)).fetchone()[0]
        session_count += db.execute('SELECT count(*) FROM dsa_model_usage WHERE session_id=?',(session_id,)).fetchone()[0]
        active = db.execute('SELECT count(*) FROM model_dispatch_leases').fetchone()[0]
        if session_count >= settings.model_session_call_limit or daily_count(db,timestamp) >= settings.model_daily_call_limit or active >= settings.model_max_concurrency:
            return None
        rid = str(uuid4())
        db.execute('INSERT INTO legacy_model_usage VALUES(?,?,?,?,?)',(rid,session_id,operation,'RESERVED',timestamp))
        db.execute('INSERT INTO model_dispatch_leases VALUES(?,?,?)',(rid,'RESERVED',timestamp))
        db.commit()
        return rid


def settle(settings, reservation_id, status):
    if status not in ('COMMITTED','UNCERTAIN','UNDISPATCHED'):
        raise ValueError('Invalid model accounting status')
    with closing(open_connection(settings.database_target)) as db:
        db.execute('BEGIN IMMEDIATE')
        if status == 'UNDISPATCHED':
            db.execute("DELETE FROM legacy_model_usage WHERE id=? AND status='RESERVED'",(reservation_id,))
        else:
            db.execute("UPDATE legacy_model_usage SET status=? WHERE id=? AND status='RESERVED'",(status,reservation_id))
        if status in ('COMMITTED','UNDISPATCHED'):
            db.execute('DELETE FROM model_dispatch_leases WHERE id=?',(reservation_id,))
        else:
            db.execute("UPDATE model_dispatch_leases SET status='UNCERTAIN' WHERE id=?",(reservation_id,))
        db.commit()
