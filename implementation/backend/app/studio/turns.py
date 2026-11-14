"""Append-only transcript corrections and current evidence selection."""
import json
import uuid
from contextlib import closing

from fastapi import APIRouter, Header, Request
from pydantic import Field

from backend.app.studio.routes import Strict, auth, connection, err, event, iso, mutation
from backend.app.studio.speech import cancel_tasks

router = APIRouter(prefix='/studio/sessions', tags=['studio'])


class TurnCorrection(Strict):
    epoch: int = Field(ge=1)
    base_revision: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=10000)
    kind: str | None = Field(default=None, min_length=1, max_length=80)


@router.post('/{sid}/turns/{tid}/correction')
def correct_turn(req: Request, sid: str, tid: str, data: TurnCorrection,
                 authorization: str = Header(default=''), x_idempotency_key: str = Header(default='')):
    with closing(connection(req)) as conn:
        auth(conn, sid, authorization)

    def append(conn):
        session = auth(conn, sid, authorization)
        if session['epoch'] != data.epoch:
            err(409, 'Turn epoch conflict')
        previous = conn.execute('SELECT * FROM studio_turns WHERE id=? AND session_id=?', (tid,sid)).fetchone()
        if not previous:
            err(404, 'Turn unavailable')
        if previous['superseded_by'] or previous['transcript_revision'] != data.base_revision:
            err(409, 'Transcript revision conflict')
        next_id, epoch, revision = str(uuid.uuid4()), data.epoch+1, data.base_revision+1
        conn.execute('INSERT INTO studio_turns(id,session_id,epoch,diagram_revision,kind,content,created_at,transcript_revision) VALUES(?,?,?,?,?,?,?,?)',
                     (next_id,sid,epoch,session['diagram_revision'],data.kind or previous['kind'],data.text,iso(),revision))
        conn.execute('UPDATE studio_turns SET superseded_by=? WHERE id=?', (next_id,tid))
        conn.execute('UPDATE studio_sessions SET epoch=? WHERE id=?', (epoch,sid))
        # Cards tied to withdrawn evidence must not silently teach the old explanation.
        conn.execute("DELETE FROM studio_review_cards WHERE session_id=? AND EXISTS (SELECT 1 FROM json_each(evidence_json) WHERE json_extract(value,'$.turn_id')=?)", (sid,tid))
        result = {'turn_id':next_id,'supersedes_turn_id':tid,'transcript_revision':revision,
                  'epoch':epoch,'feedback_status':'abstained_insufficient_signal'}
        event(conn, sid, 'turn.corrected', result)
        return result

    return mutation(req,sid,x_idempotency_key,data.model_dump(),append,
                    on_commit=lambda out: cancel_tasks(sid,before_epoch=out['epoch']))


def current_recorded_turns(conn, sid, history):
    """Resolve corrections without moving an answer's original coaching phase."""
    rows={row['id']:row for row in conn.execute('SELECT id,superseded_by,transcript_revision FROM studio_turns WHERE session_id=?',(sid,))}
    def resolve(tid):
        seen=set()
        while tid in rows and tid not in seen:
            row=rows[tid]
            following=row['superseded_by']
            if following is None:
                return tid
            if following not in rows or rows[following]['transcript_revision']<=row['transcript_revision']:
                return None
            seen=seen|{tid}
            tid=following
        return None
    return [(seq,tid) for seq,kind,payload in history if kind=='turn.recorded'
            and (tid := resolve(payload.get('turn_id'))) is not None]


def feedback_is_current(conn, session, payload):
    """Epoch invalidates in-flight work, not previously committed valid evidence."""
    if payload.get('diagram_revision') != session['diagram_revision']:
        return False
    if payload.get('constraint_index') != session['constraint_index']:
        return False
    active = {r['id'] for r in conn.execute('SELECT id FROM studio_turns WHERE session_id=? AND superseded_by IS NULL', (session['id'],))}
    target = payload.get('turn_id')
    if not target or target not in active:
        return False
    repo = set()
    if session['repo_snapshot_id']:
        repo = {r['id'] for r in conn.execute("SELECT c.id FROM repo_chunks c JOIN repo_snapshots s ON s.id=c.snapshot_id WHERE s.id=? AND s.workspace_id=? AND s.status='READY'", (session['repo_snapshot_id'],session['workspace_id']))}
    ids = payload.get('evidence_turn_ids',[])
    if any(value not in active for value in ids):
        return False
    return all(value in active | repo for item in payload.get('criteria',[]) for value in item.get('evidence_ids',[]))


def latest_feedback(conn, session):
    rows = conn.execute("SELECT payload_json FROM studio_events WHERE session_id=? AND event_type='feedback.ready' ORDER BY sequence DESC", (session['id'],))
    return next((payload for row in rows if feedback_is_current(conn,session,payload := json.loads(row['payload_json']))), {})
