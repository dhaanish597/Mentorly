"""Bounded studio retention sweep for the documented single coordinator."""
import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timezone
from contextlib import closing
from backend.app.db.migrations import open_connection
from backend.app.studio.security import purge_speech_usage


def sweep(db_path):
    now=datetime.now(timezone.utc).isoformat()
    with closing(open_connection(db_path)) as conn:
        conn.execute('BEGIN IMMEDIATE')
        expired_workspaces=[r['id'] for r in conn.execute('SELECT id FROM studio_workspaces WHERE deleted_at IS NULL AND expires_at<=? LIMIT 100',(now,))]
        for wid in expired_workspaces:
            from backend.app.db.repository import tombstone_session_in_connection
            linked=[r['session_id'] for r in conn.execute('SELECT session_id FROM workspace_dsa_sessions WHERE workspace_id=?',(wid,))]
            for linked_id in linked:
                tombstone_session_in_connection(conn,linked_id,now)
            conn.execute('UPDATE studio_workspaces SET deleted_at=? WHERE id=?',(now,wid))
            conn.execute('UPDATE studio_sessions SET deleted_at=?,epoch=epoch+1 WHERE workspace_id=? AND deleted_at IS NULL',(now,wid))
            conn.execute('DELETE FROM repo_snapshots WHERE workspace_id=?',(wid,))
            conn.execute('DELETE FROM studio_idempotency WHERE owner_id=?',(wid,))
        sessions=[r['id'] for r in conn.execute('SELECT id FROM studio_sessions WHERE cleaned_at IS NULL AND (deleted_at IS NOT NULL OR expires_at<=?) LIMIT 100',(now,))]
        for sid in sessions:
            from backend.app.studio.speech import cancel_tasks
            cancel_tasks(sid)
            purge_speech_usage(conn,sid)
            from backend.app.studio.model_budget import purge_session
            purge_session(conn,sid)
            conn.execute('DELETE FROM repo_defense_sessions WHERE studio_session_id=?',(sid,))
            conn.execute('UPDATE studio_sessions SET deleted_at=COALESCE(deleted_at,?),epoch=epoch+CASE WHEN deleted_at IS NULL THEN 1 ELSE 0 END WHERE id=?',(now,sid))
            for table in ('studio_review_cards','studio_diagrams','studio_events','studio_turns','studio_proposals'):
                conn.execute(f'DELETE FROM {table} WHERE session_id=?',(sid,))
            conn.execute('DELETE FROM studio_idempotency WHERE owner_id=?',(sid,))
            conn.execute('UPDATE studio_sessions SET cleaned_at=? WHERE id=?',(now,sid))
        conn.execute("DELETE FROM studio_speech_deleted_daily WHERE day<date(?)",(now,))
        conn.execute("DELETE FROM studio_model_deleted_daily WHERE day<date(?)",(now,))
        conn.commit()
    from backend.app.repo_learning.lifecycle import cancel_workspace
    for wid in expired_workspaces:
        cancel_workspace(db_path,wid)


class StudioRetention:
    def __init__(self, db_path, interval): self.db_path,self.interval,self.task=db_path,interval,None
    def start(self): self.task=asyncio.create_task(self._run())
    async def _run(self):
        while True:
            try:
                await asyncio.to_thread(sweep,self.db_path)
            except Exception:
                logging.getLogger(__name__).exception("Studio retention sweep failed; retrying")
            await asyncio.sleep(self.interval)
    async def aclose(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError): await self.task
