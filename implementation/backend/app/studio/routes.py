"""Studio capability API; mutations are serialized with SQLite transactions."""
from backend.app.db.migrations import database_target
import asyncio
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from math import ceil, isfinite
from contextlib import closing
from backend.app.db.migrations import open_connection
from backend.app.studio.catalog import SCENARIOS
from backend.app.studio.scenario_content import get_content
from backend.app.studio.scenario_rules import evaluate_scenario, rule_input_fields
from backend.app.studio.security import authenticate_workspace, digest_token, purge_speech_usage
from backend.app.studio.validation import evaluate

router = APIRouter(prefix='/studio', tags=['studio'])

def now(): return datetime.now(timezone.utc)
def iso(): return now().isoformat()
def encode(v): return json.dumps(v, sort_keys=True, separators=(',', ':'), allow_nan=False)
def err(status, text): raise HTTPException(status, text)

def secret(value):
    if not 32 <= len(value) <= 256: err(422, 'Capability must contain 32–256 characters')
    return digest_token(value)

def ident(value):
    try: return str(uuid.UUID(value))
    except ValueError: err(422, 'Expected UUID')

def token(header): return header[7:] if header.startswith('Bearer ') else ''
def connection(req): return open_connection(database_target(req.app.state.settings))

def auth(conn, sid, header):
    row = conn.execute('SELECT * FROM studio_sessions WHERE id=?', (sid,)).fetchone()
    supplied = token(header)
    valid = hmac.compare_digest(row['token_hash'] if row else '0'*64, digest_token(supplied))
    if not row or not supplied or not valid: err(401, 'Invalid session capability')
    owner=conn.execute('SELECT deleted_at,expires_at FROM studio_workspaces WHERE id=?',(row['workspace_id'],)).fetchone()
    if row['deleted_at'] or datetime.fromisoformat(row['expires_at']) <= now() or not owner or owner['deleted_at'] or datetime.fromisoformat(owner['expires_at']) <= now(): err(410, 'Session expired or deleted')
    if row['mode']=='architecture_mock_interview' and row['posture']=='assessment' and row['state']=='active' and row['deadline_at'] and datetime.fromisoformat(row['deadline_at'])<=now():
        owns_transaction=not conn.in_transaction
        if owns_transaction: conn.execute('BEGIN IMMEDIATE')
        changed=conn.execute("UPDATE studio_sessions SET state='completed',remaining_seconds=0,epoch=epoch+1 WHERE id=? AND state='active' AND deadline_at<=?",(sid,iso())).rowcount
        if changed: event(conn,sid,'timer.expired',{'phase':'completed','remaining_seconds':0,'epoch':row['epoch']+1})
        if owns_transaction: conn.commit()
        if changed and owns_transaction:
            from backend.app.studio.speech import cancel_tasks
            cancel_tasks(sid,before_epoch=row['epoch']+1)
        row=conn.execute('SELECT * FROM studio_sessions WHERE id=?',(sid,)).fetchone()
    return row

def auth_workspace_row(conn, wid, bearer):
    row=conn.execute('SELECT token_hash,expires_at,deleted_at FROM studio_workspaces WHERE id=?',(wid,)).fetchone()
    supplied=token(bearer)
    matches=hmac.compare_digest(row['token_hash'] if row else '0'*64,digest_token(supplied))
    if not row or not supplied or not matches or row['deleted_at'] or datetime.fromisoformat(row['expires_at'])<=now():
        err(401,'Invalid workspace capability')
    return row

def event(conn,sid,kind,payload):
    seq = conn.execute('SELECT COALESCE(MAX(sequence),0)+1 FROM studio_events WHERE session_id=?',(sid,)).fetchone()[0]
    conn.execute('INSERT INTO studio_events VALUES(?,?,?,?,?)',(sid,seq,kind,encode(payload),iso()))
    conn.execute('DELETE FROM studio_events WHERE session_id=? AND sequence<=?',(sid,seq-5000))
    return seq

def in_transfer(conn,sid):
    rows=conn.execute("SELECT payload_json FROM studio_events WHERE session_id=? AND event_type='coach.action' ORDER BY sequence DESC",(sid,)).fetchall()
    for row in rows:
        action=json.loads(row['payload_json']).get('action')
        if action in ('transfer','rewind'): return action=='transfer'
    return False

def repo_stage_verified(conn, session, constraint_index):
    """Revalidate each required defense-phase citation against the owned snapshot."""
    if session['mode'] not in ('repo_exploration','project_defense') or not session['repo_snapshot_id']:
        return False
    defense=conn.execute("SELECT d.id FROM repo_defense_sessions d JOIN repo_snapshots r ON r.id=d.snapshot_id AND r.workspace_id=d.workspace_id WHERE d.studio_session_id=? AND d.workspace_id=? AND d.snapshot_id=? AND r.status='READY'",(session['id'],session['workspace_id'],session['repo_snapshot_id'])).fetchone()
    if not defense: return False
    answers=conn.execute('SELECT phase,citations_json FROM repo_defense_answers WHERE defense_id=? ORDER BY sequence',(defense['id'],)).fetchall()
    phases=('map','derive','defend','reflect')
    for expected in phases[:constraint_index+1]:
        matching=next((a for a in answers if a['phase']==expected),None)
        if not matching: return False
        try: citations=json.loads(matching['citations_json'])
        except (TypeError,ValueError): return False
        if not isinstance(citations,list) or not citations: return False
        for c in citations:
            if not isinstance(c,dict) or not all(k in c for k in ('path','symbol','start_line','end_line','chunk_hash')): return False
            if not conn.execute('SELECT 1 FROM repo_chunks WHERE snapshot_id=? AND path=? AND symbol=? AND start_line=? AND end_line=? AND chunk_hash=?',(session['repo_snapshot_id'],c['path'],c['symbol'],c['start_line'],c['end_line'],c['chunk_hash'])).fetchone(): return False
    return True

def mutation(req, owner, key, body, fn, *, on_commit=None):
    if not 8 <= len(key) <= 128: err(400,'X-Idempotency-Key required')
    digest = hashlib.sha256(encode(body).encode()).hexdigest()
    conn = connection(req)
    try:
        conn.execute('BEGIN IMMEDIATE')
        prior = conn.execute('SELECT digest,response_json FROM studio_idempotency WHERE owner_id=? AND method=? AND path=? AND key=?',(owner,req.method,req.url.path,key)).fetchone()
        if prior:
            if prior['digest'] != digest: err(409,'Idempotency key conflict')
            out = json.loads(prior['response_json'])
        else:
            out = fn(conn)
            conn.execute('INSERT INTO studio_idempotency VALUES(?,?,?,?,?,?,?,?)',(owner,req.method,req.url.path,key,digest,200,encode(out),iso()))
        conn.commit()
        if prior is None and on_commit is not None: on_commit(out)
        return out
    except BaseException:
        conn.rollback(); raise
    finally: conn.close()

class Strict(BaseModel): model_config = ConfigDict(extra='forbid')
class Workspace(Strict): workspace_id: str; workspace_token: str
class NewSession(Strict):
    workspace_id: str; session_id: str; session_token: str
    mode: str; posture: str; scenario_id: str; scenario_version: str = '1.0.0'; repo_snapshot_id: str | None = None
    duration_seconds: int | None = Field(default=None,ge=60,le=14400)
def bounded_json(value, depth=0):
    if depth > 4: raise ValueError('Nested data exceeds depth limit')
    if isinstance(value, dict):
        if len(value)>40: raise ValueError('Too many properties')
        for k,v in value.items():
            if not isinstance(k,str) or not 1<=len(k)<=80: raise ValueError('Invalid property name')
            bounded_json(v,depth+1)
    elif isinstance(value, list):
        if len(value)>40: raise ValueError('Too many values')
        for v in value: bounded_json(v,depth+1)
    elif isinstance(value,str):
        if len(value)>1000: raise ValueError('Property text too long')
    elif isinstance(value,float):
        if not isfinite(value): raise ValueError('Non-finite value')
    elif value is not None and not isinstance(value,(int,bool)):
        raise ValueError('Invalid property value')
    return value

class Node(Strict):
    node_id: str = Field(min_length=1,max_length=100); kind: str = Field(min_length=1,max_length=80); label: str = Field(max_length=200); replica_count: int = Field(default=1,ge=1,le=100000)
    statefulness: str = Field(default='',max_length=80); partition_key: str = Field(default='',max_length=120); consistency_mode: str = Field(default='',max_length=80); notes: str = Field(default='',max_length=2000)
    properties: dict = Field(default_factory=dict)
    @field_validator('properties')
    @classmethod
    def validate_properties(cls,v): return bounded_json(v)
class Edge(Strict):
    edge_id: str = Field(min_length=1,max_length=100); source_node_id: str = Field(min_length=1,max_length=100); target_node_id: str = Field(min_length=1,max_length=100); protocol: str = Field(default='',max_length=80)
    directionality: str = Field(default='directed',max_length=80); rate_estimate_rps: float | None = Field(default=None,ge=0,allow_inf_nan=False); failure_behavior: str = Field(default='',max_length=500)
class Diagram(Strict):
    base_revision: int = Field(ge=0); nodes: list[Node] = Field(max_length=200); edges: list[Edge] = Field(max_length=500); assumptions: dict = Field(default_factory=dict)
    @field_validator('assumptions')
    @classmethod
    def validate_assumptions(cls,v): return bounded_json(v)
class Turn(Strict): epoch: int; text: str = Field(min_length=1,max_length=10000); kind: str = 'answer'
class Interrupt(Strict): expected_epoch: int

@router.get('/scenarios')
def scenarios(): return {'scenarios': list(SCENARIOS.values())}

@router.post('/workspaces')
def workspace(req: Request, data: Workspace, x_idempotency_key: str = Header(default='')):
    wid = ident(data.workspace_id); hashed = secret(data.workspace_token)
    # The client capability is used for verification and never included in stored replay.
    def create(conn):
        row=conn.execute('SELECT * FROM studio_workspaces WHERE id=?',(wid,)).fetchone()
        if row:
            if not hmac.compare_digest(row['token_hash'],hashed) or row['deleted_at']: err(409,'Workspace conflict')
            return {'workspace_id':wid,'expires_at':row['expires_at']}
        expiry=(now()+timedelta(days=30)).isoformat()
        conn.execute('INSERT INTO studio_workspaces VALUES(?,?,?,?,NULL)',(wid,hashed,iso(),expiry))
        return {'workspace_id':wid,'expires_at':expiry}
    return mutation(req,wid,x_idempotency_key,{'workspace_id':wid,'token_hash':hashed},create)

@router.post('/sessions')
def create_session(req: Request,data: NewSession,authorization: str = Header(default=''),x_idempotency_key: str = Header(default='')):
    wid=ident(data.workspace_id); sid=ident(data.session_id); hashed=secret(data.session_token)
    authenticate_workspace(req,wid,token(authorization))
    scenario=SCENARIOS.get(data.scenario_id)
    if not scenario or data.scenario_version != scenario['version']: err(422,'Unknown scenario version')
    allowed = {scenario['mode']}
    if scenario['mode']=='guided_system_design': allowed.add('architecture_mock_interview')
    if data.mode not in allowed or data.posture not in ('teaching','assessment'): err(422,'Invalid mode or posture')
    def create(conn):
        auth_workspace_row(conn,wid,authorization)
        if data.mode in ('repo_exploration','project_defense') and not data.repo_snapshot_id: err(422,'Repository snapshot required')
        if data.repo_snapshot_id:
            repo = conn.execute("SELECT id FROM repo_snapshots WHERE id=? AND workspace_id=? AND status='READY'", (data.repo_snapshot_id,wid)).fetchone()
            if not repo: err(404,'Repository snapshot unavailable')
        existing=conn.execute('SELECT * FROM studio_sessions WHERE id=?',(sid,)).fetchone()
        if existing: err(409,'Session ID already exists')
        expiry=(now()+timedelta(days=30)).isoformat()
        conn.execute('INSERT INTO studio_sessions(id,workspace_id,token_hash,mode,posture,scenario_id,scenario_version,repo_snapshot_id,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(sid,wid,hashed,data.mode,data.posture,data.scenario_id,data.scenario_version,data.repo_snapshot_id,iso(),expiry))
        spec=get_content(data.scenario_id)
        conn.execute('UPDATE studio_sessions SET scenario_json=?,scenario_hash=? WHERE id=?',(encode(spec),spec['content_sha256'],sid))
        conn.execute('INSERT INTO studio_diagrams VALUES(?,0,NULL,?,?)',(sid,encode(spec['seed_graph']),iso()))
        if data.mode=='architecture_mock_interview':
            duration=data.duration_seconds or 2700
            conn.execute('UPDATE studio_sessions SET deadline_at=?,remaining_seconds=? WHERE id=?',((now()+timedelta(seconds=duration)).isoformat(),duration,sid))
        event(conn,sid,'session.created',{'epoch':1,'phase':'clarify'})
        return {'session_id':sid,'epoch':1,'diagram_revision':0,'expires_at':expiry}
    body=data.model_dump(); body['session_token']=hashed
    return mutation(req,wid,x_idempotency_key,body,create)

@router.get('/sessions/{sid}')
def snapshot(req: Request,sid: str,authorization: str = Header(default='')):
    with closing(connection(req)) as conn:
        s=auth(conn,sid,authorization)
        graph=json.loads(conn.execute('SELECT graph_json FROM studio_diagrams WHERE session_id=? AND revision=?',(sid,s['diagram_revision'])).fetchone()[0])
        events=[dict(r) for r in conn.execute('SELECT sequence,event_type,payload_json,created_at FROM studio_events WHERE session_id=? ORDER BY sequence',(sid,))]
        turns=[dict(r) for r in conn.execute('SELECT id,epoch,diagram_revision,kind,content,created_at,transcript_revision,superseded_by FROM studio_turns WHERE session_id=? ORDER BY created_at,id',(sid,))]
        from backend.app.repo_learning.service import repo_session_summary
        repo_summary=repo_session_summary(database_target(req.app.state.settings),s['workspace_id'],sid) if s['repo_snapshot_id'] else None
        phase=next((json.loads(e['payload_json'])['phase'] for e in reversed(events) if 'phase' in json.loads(e['payload_json'])),'clarify')
        return {'phase':phase,'repo_summary':repo_summary,'session_id':sid,'workspace_id':s['workspace_id'],'mode':s['mode'],'posture':s['posture'],'scenario_id':s['scenario_id'],'scenario_version':s['scenario_version'],'repo_snapshot_id':s['repo_snapshot_id'],'epoch':s['epoch'],'diagram_revision':s['diagram_revision'],'state':s['state'],'scenario_hash':s['scenario_hash'],'constraint_index':s['constraint_index'],'hint_level':s['hint_level'],'expires_at':s['expires_at'],'deadline_at':s['deadline_at'],'remaining_seconds':s['remaining_seconds'],'graph':graph,'turns':turns,'events':[{'sequence':e['sequence'],'type':e['event_type'],'payload':json.loads(e['payload_json']),'created_at':e['created_at']} for e in events]}

@router.put('/sessions/{sid}/diagram')
def diagram(req: Request,sid: str,data: Diagram,authorization: str = Header(default=''),x_idempotency_key: str = Header(default='')):
    with closing(connection(req)) as c: auth(c,sid,authorization)
    graph=data.model_dump(exclude={'base_revision'}); checked=evaluate(graph)
    if checked['structural_errors']: err(422,checked['structural_errors'])
    def update(conn):
        s=auth(conn,sid,authorization)
        if s['state']=='completed': err(409,'Reopen practice before editing')
        if s['diagram_revision'] != data.base_revision: err(409,'Diagram revision conflict')
        revision=data.base_revision+1
        conn.execute('INSERT INTO studio_diagrams VALUES(?,?,?,?,?)',(sid,revision,data.base_revision,encode(graph),iso()))
        conn.execute('UPDATE studio_sessions SET diagram_revision=?,epoch=epoch+1 WHERE id=?',(revision,sid))
        event(conn,sid,'diagram.updated',{'revision':revision,'epoch':s['epoch']+1,'phase':'transfer' if in_transfer(conn,sid) else 'revision'})
        return {'revision':revision,'epoch':s['epoch']+1,'validation':checked}
    from backend.app.studio.speech import cancel_tasks
    return mutation(req,sid,x_idempotency_key,data.model_dump(),update,on_commit=lambda out: cancel_tasks(sid,before_epoch=out['epoch']) if 'epoch' in out else None)

@router.post('/sessions/{sid}/turns')
def turn(req: Request,sid: str,data: Turn,authorization: str = Header(default=''),x_idempotency_key: str = Header(default='')):
    with closing(connection(req)) as c: auth(c,sid,authorization)
    def add(conn):
        s=auth(conn,sid,authorization)
        if data.epoch != s['epoch']: err(409,'Turn epoch conflict')
        if s['state']=='completed': err(409,'Reopen practice before answering')
        if s['mode']=='architecture_mock_interview' and s['posture']=='assessment' and (s['state']!='active' or not s['deadline_at'] or datetime.fromisoformat(s['deadline_at'])<=now()): err(409,'Mock timer is not active')
        turn_id=str(uuid.uuid4())
        conn.execute('INSERT INTO studio_turns(id,session_id,epoch,diagram_revision,kind,content,created_at) VALUES(?,?,?,?,?,?,?)',(turn_id,sid,s['epoch'],s['diagram_revision'],data.kind,data.text,iso()))
        payload={'turn_id':turn_id,'epoch':s['epoch'],'transcript_revision':1,'feedback_status':'abstained_insufficient_signal'}
        event(conn,sid,'turn.recorded',payload)
        return payload
    return mutation(req,sid,x_idempotency_key,data.model_dump(),add)

@router.post('/sessions/{sid}/interrupt')
def interrupt(req: Request,sid: str,data: Interrupt,authorization: str = Header(default=''),x_idempotency_key: str = Header(default='')):
    with closing(connection(req)) as c: auth(c,sid,authorization)
    def act(conn):
        s=auth(conn,sid,authorization)
        if s['epoch'] != data.expected_epoch: err(409,'Turn epoch conflict')
        epoch=s['epoch']+1
        conn.execute('UPDATE studio_sessions SET epoch=? WHERE id=?',(epoch,sid)); event(conn,sid,'turn.interrupted',{'epoch':epoch})
        return {'epoch':epoch}
    from backend.app.studio.speech import cancel_tasks
    return mutation(req,sid,x_idempotency_key,data.model_dump(),act,on_commit=lambda out: cancel_tasks(sid,before_epoch=out['epoch']) if 'epoch' in out else None)

@router.get('/sessions/{sid}/events')
def events(req: Request,sid: str,authorization: str = Header(default=''),last_event_id: str = Header(default='0')):
    try: cursor=max(0,int(last_event_id))
    except ValueError: err(400,'Invalid event cursor')
    with closing(connection(req)) as conn:
        auth(conn,sid,authorization)
        first=conn.execute('SELECT MIN(sequence) FROM studio_events WHERE session_id=?',(sid,)).fetchone()[0]
        if first is not None and cursor < first-1: err(409,'Event cursor expired; reload snapshot')
    async def stream():
        nonlocal cursor
        while not await req.is_disconnected():
            try:
                with closing(connection(req)) as conn:
                    auth(conn,sid,authorization)
                    rows=[dict(r) for r in conn.execute('SELECT sequence,event_type,payload_json FROM studio_events WHERE session_id=? AND sequence>? ORDER BY sequence LIMIT 100',(sid,cursor))]
            except HTTPException:
                return
            if rows:
                for row in rows:
                    cursor=row['sequence']
                    yield f"id: {cursor}\nevent: {row['event_type']}\ndata: {row['payload_json']}\n\n"
            else:
                yield ': keepalive\n\n'
                await asyncio.sleep(1)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})

@router.delete('/sessions/{sid}')
def delete(req: Request,sid: str,authorization: str = Header(default=''),x_idempotency_key: str = Header(default='')):
    with closing(connection(req)) as c: auth(c,sid,authorization)
    def act(conn):
        auth(conn,sid,authorization)
        conn.execute('UPDATE studio_sessions SET deleted_at=?,epoch=epoch+1 WHERE id=?',(iso(),sid))
        from backend.app.studio.speech import cancel_tasks
        cancel_tasks(sid)
        purge_speech_usage(conn,sid)
        from backend.app.studio.model_budget import purge_session
        purge_session(conn,sid)
        conn.execute('DELETE FROM repo_defense_sessions WHERE studio_session_id=?',(sid,))
        for table in ('studio_review_cards','studio_diagrams','studio_events','studio_turns','studio_proposals'): conn.execute(f'DELETE FROM {table} WHERE session_id=?',(sid,))
        conn.execute('DELETE FROM studio_idempotency WHERE owner_id=?',(sid,))
        return {'deleted':True}
    from backend.app.studio.speech import cancel_tasks
    return mutation(req,sid,x_idempotency_key,{},act,on_commit=lambda _: cancel_tasks(sid))

class RevisionAction(Strict): base_revision: int = Field(ge=0); target_revision: int = Field(ge=0)
class Proposal(Strict): base_revision: int = Field(ge=0); graph: dict

@router.get('/sessions/{sid}/diagrams')
def diagram_history(req: Request,sid: str,authorization: str = Header(default='')):
    with closing(connection(req)) as conn:
        auth(conn,sid,authorization)
        return {'revisions':[{'revision':r['revision'],'parent_revision':r['parent_revision'],'created_at':r['created_at']} for r in conn.execute('SELECT revision,parent_revision,created_at FROM studio_diagrams WHERE session_id=? ORDER BY revision',(sid,))]}

@router.post('/sessions/{sid}/diagrams/restore')
def restore_diagram(req: Request,sid: str,data: RevisionAction,authorization: str = Header(default=''),x_idempotency_key: str = Header(default='')):
    with closing(connection(req)) as c: auth(c,sid,authorization)
    def act(conn):
        s=auth(conn,sid,authorization)
        if s['state']=='completed': err(409,'Reopen practice before editing')
        if s['diagram_revision']!=data.base_revision: err(409,'Diagram revision conflict')
        target=conn.execute('SELECT graph_json FROM studio_diagrams WHERE session_id=? AND revision=?',(sid,data.target_revision)).fetchone()
        if not target: err(404,'Revision unavailable')
        rev=s['diagram_revision']+1
        conn.execute('INSERT INTO studio_diagrams VALUES(?,?,?,?,?)',(sid,rev,data.base_revision,target['graph_json'],iso()))
        conn.execute('UPDATE studio_sessions SET diagram_revision=?,epoch=epoch+1 WHERE id=?',(rev,sid))
        event(conn,sid,'diagram.restored',{'revision':rev,'source_revision':data.target_revision,'epoch':s['epoch']+1})
        return {'revision':rev,'epoch':s['epoch']+1,'graph':json.loads(target['graph_json'])}
    from backend.app.studio.speech import cancel_tasks
    return mutation(req,sid,x_idempotency_key,data.model_dump(),act,on_commit=lambda out: cancel_tasks(sid,before_epoch=out['epoch']) if 'epoch' in out else None)

@router.post('/sessions/{sid}/proposals')
def preview(req: Request,sid: str,data: Proposal,authorization: str = Header(default=''),x_idempotency_key: str = Header(default='')):
    with closing(connection(req)) as c: auth(c,sid,authorization)
    try:
        parsed=Diagram.model_validate({**data.graph,'base_revision':data.base_revision})
    except ValidationError:
        err(422,'Invalid proposal graph')
    graph=parsed.model_dump(exclude={'base_revision'})
    checked=evaluate(graph)
    if checked['structural_errors']: err(422,checked['structural_errors'])
    def act(conn):
        s=auth(conn,sid,authorization)
        if s['state']=='completed': err(409,'Reopen practice before editing')
        if s['diagram_revision']!=data.base_revision: err(409,'Diagram revision conflict')
        pid=str(uuid.uuid4())
        conn.execute('INSERT INTO studio_proposals VALUES(?,?,?,?,?,?)',(pid,sid,data.base_revision,encode(graph),'pending',iso()))
        return {'proposal_id':pid,'base_revision':data.base_revision,'graph':graph,'validation':checked}
    return mutation(req,sid,x_idempotency_key,data.model_dump(),act)

@router.post('/sessions/{sid}/proposals/{pid}/{action}')
def proposal_action(req: Request,sid: str,pid: str,action: str,authorization: str = Header(default=''),x_idempotency_key: str = Header(default='')):
    if action not in ('accept','discard'): err(404,'Unknown action')
    with closing(connection(req)) as c: auth(c,sid,authorization)
    def act(conn):
        s=auth(conn,sid,authorization)
        p=conn.execute('SELECT * FROM studio_proposals WHERE id=? AND session_id=? AND status=?',(pid,sid,'pending')).fetchone()
        if not p: err(404,'Proposal unavailable')
        if action=='accept':
            if s['state']=='completed': err(409,'Reopen practice before editing')
            if p['base_revision']!=s['diagram_revision']: err(409,'Diagram revision conflict')
            rev=s['diagram_revision']+1
            conn.execute('INSERT INTO studio_diagrams VALUES(?,?,?,?,?)',(sid,rev,s['diagram_revision'],p['graph_json'],iso()))
            conn.execute('UPDATE studio_sessions SET diagram_revision=?,epoch=epoch+1 WHERE id=?',(rev,sid))
            event(conn,sid,'diagram.updated',{'revision':rev,'epoch':s['epoch']+1})
        else: rev=s['diagram_revision']
        conn.execute('UPDATE studio_proposals SET status=? WHERE id=?',(action,pid))
        return {'status':action,'revision':rev,'epoch':s['epoch']+(action=='accept')}
    from backend.app.studio.speech import cancel_tasks
    return mutation(req,sid,x_idempotency_key,{'action':action},act,on_commit=lambda out: cancel_tasks(sid,before_epoch=out['epoch']) if 'epoch' in out else None)

@router.get('/sessions/{sid}/summary')
def summary(req: Request,sid: str,authorization: str = Header(default='')):
    with closing(connection(req)) as conn:
        s=auth(conn,sid,authorization)
        count=conn.execute('SELECT count(*) FROM studio_turns WHERE session_id=? AND superseded_by IS NULL',(sid,)).fetchone()[0]
        dimensions=('algorithm_correctness','architecture_reasoning','codebase_comprehension','technical_communication')
        assisted=conn.execute("SELECT count(*) FROM studio_events WHERE session_id=? AND CAST(json_extract(payload_json,'$.assistance') AS TEXT) IN ('1','true')",(sid,)).fetchone()[0]
        from backend.app.studio.turns import latest_feedback
        feedback=latest_feedback(conn,s) if s['posture']!='assessment' or s['state']=='completed' else {}
        criteria=feedback.get('criteria',[])
        by_dimension={x['dimension']:x for x in criteria}
        assessments=[{**by_dimension.get(d,{'dimension':d,'status':'abstained_insufficient_signal','evidence_ids':[]}),'confidence':'low' if d in by_dimension and by_dimension[d]['status']=='observed_signal' else None} for d in dimensions]
        graph=json.loads(conn.execute('SELECT graph_json FROM studio_diagrams WHERE session_id=? AND revision=?',(sid,s['diagram_revision'])).fetchone()[0])
        spec=json.loads(s['scenario_json'])
        evaluation=evaluate_scenario(graph,s['scenario_id'],s['constraint_index'],spec=spec,transfer=in_transfer(conn,sid),evidence_verified=repo_stage_verified(conn,s,s['constraint_index'])) if s['posture']!='assessment' or s['state']=='completed' else {'status':'withheld_until_debrief','checks':[]}
        for check in evaluation['checks']: check.pop('required_fields',None)
        fields=rule_input_fields(spec,s['constraint_index'],transfer=in_transfer(conn,sid)) if s['posture']!='assessment' or s['state']=='completed' else []
        missing=[f['key'] for f in fields if f['location']=='assumptions' and f['key'] not in graph.get('assumptions',{})]
        return {'session_id':sid,'scenario_id':s['scenario_id'],'turn_count':count,'assistance_events':assisted,'dimensions':assessments,'artifact':{'diagram_revision':s['diagram_revision'],'node_count':len(graph['nodes']),'edge_count':len(graph['edges'])},'constraint_checks':evaluation,'missing_assumptions':missing,'next_transfer':spec['fresh_transfer_question'] if s['posture']!='assessment' or s['state']=='completed' else None,'limitation':'Checks assess declarations, not runtime behavior or understanding; semantic signals are low-confidence.'}

@router.get('/sessions/{sid}/export')
def export_session(req: Request,sid: str,authorization: str = Header(default=''),format: str = 'json'):
    out=snapshot(req,sid,authorization)
    with closing(connection(req)) as conn:
        auth(conn,sid,authorization)
        out['turns']=[dict(r) for r in conn.execute('SELECT id,epoch,diagram_revision,kind,content,created_at,transcript_revision,superseded_by FROM studio_turns WHERE session_id=? ORDER BY created_at',(sid,))]
    if format=='json': return out
    if format!='markdown': err(422,'Unsupported export format')
    lines=['# Studio session',f"Scenario: {out['scenario_id']}",f"Diagram revision: {out['diagram_revision']}",'', '## Learner turns']
    lines.extend('- '+turn['content'].replace('\n',' ') for turn in out['turns'])
    return PlainTextResponse('\n'.join(lines),media_type='text/markdown')

class ReviewCreate(Strict):
    turn_id: str; prompt: str = Field(min_length=1,max_length=1000)
class ReviewRating(Strict): rating: int = Field(ge=1,le=4)

@router.post('/sessions/{sid}/review-cards')
def create_review(req: Request,sid: str,data: ReviewCreate,authorization: str = Header(default=''),x_idempotency_key: str = Header(default='')):
    from fsrs import Card
    with closing(connection(req)) as c: auth(c,sid,authorization)
    def act(conn):
        s=auth(conn,sid,authorization)
        evidence=conn.execute('SELECT id,epoch FROM studio_turns WHERE id=? AND session_id=? AND superseded_by IS NULL',(data.turn_id,sid)).fetchone()
        if not evidence: err(404,'Evidence unavailable')
        card=Card(); cid=str(uuid.uuid4())
        conn.execute('INSERT INTO studio_review_cards VALUES(?,?,?,?,?,?,?)',(cid,s['workspace_id'],sid,data.prompt,encode([{'turn_id':data.turn_id}]),card.to_json(),card.due.isoformat()))
        return {'card_id':cid,'due_at':card.due.isoformat(),'scheduler':'fsrs-6.3.3'}
    return mutation(req,sid,x_idempotency_key,data.model_dump(),act)

@router.get('/workspaces/{wid}/reviews')
def review_queue(req: Request,wid: str,authorization: str = Header(default='')):
    authenticate_workspace(req,wid,token(authorization))
    with closing(connection(req)) as conn:
        rows=conn.execute('SELECT c.id,c.session_id,c.prompt,c.evidence_json,c.due_at FROM studio_review_cards c JOIN studio_sessions s ON s.id=c.session_id WHERE c.workspace_id=? AND c.due_at<=? AND s.deleted_at IS NULL AND s.expires_at>? ORDER BY c.due_at,c.id LIMIT 100',(wid,iso(),iso())).fetchall()
        return {'cards':[{'card_id':r['id'],'session_id':r['session_id'],'prompt':r['prompt'],'evidence':json.loads(r['evidence_json']),'due_at':r['due_at']} for r in rows]}

@router.post('/workspaces/{wid}/reviews/{cid}/rating')
def rate_review(req: Request,wid: str,cid: str,data: ReviewRating,authorization: str = Header(default=''),x_idempotency_key: str = Header(default='')):
    from fsrs import Card, Rating, Scheduler
    authenticate_workspace(req,wid,token(authorization))
    def act(conn):
        auth_workspace_row(conn,wid,authorization)
        row=conn.execute('SELECT c.fsrs_json FROM studio_review_cards c JOIN studio_sessions s ON s.id=c.session_id WHERE c.id=? AND c.workspace_id=? AND s.deleted_at IS NULL AND s.expires_at>?',(cid,wid,iso())).fetchone()
        if not row: err(404,'Card unavailable')
        card=Card.from_json(row['fsrs_json'])
        updated,_=Scheduler(enable_fuzzing=False).review_card(card,Rating(data.rating),review_datetime=now())
        conn.execute('UPDATE studio_review_cards SET fsrs_json=?,due_at=? WHERE id=? AND workspace_id=?',(updated.to_json(),updated.due.isoformat(),cid,wid))
        return {'card_id':cid,'due_at':updated.due.isoformat(),'scheduler':'fsrs-6.3.3'}
    return mutation(req,wid,x_idempotency_key,data.model_dump(),act)

@router.post('/sessions/{sid}/timer/{action}')
def timer(req: Request,sid: str,action: str,authorization: str = Header(default=''),x_idempotency_key: str = Header(default='')):
    if action not in ('pause','resume'): err(404,'Unknown timer action')
    with closing(connection(req)) as c: auth(c,sid,authorization)
    def act(conn):
        s=auth(conn,sid,authorization)
        if s['mode']!='architecture_mock_interview' or s['posture']!='assessment': err(409,'No active mock timer')
        if action=='pause':
            if s['state']!='active' or not s['deadline_at']: err(409,'Timer not active')
            left=max(0,ceil((datetime.fromisoformat(s['deadline_at'])-now()).total_seconds()))
            state='paused' if left else 'expired'
            conn.execute('UPDATE studio_sessions SET state=?,remaining_seconds=?,deadline_at=NULL,paused_at=?,epoch=epoch+1 WHERE id=?',(state,left,iso(),sid))
            deadline=None
        else:
            if s['state']!='paused' or not s['remaining_seconds']: err(409,'Timer not paused')
            left=s['remaining_seconds']; state='active'; deadline=(now()+timedelta(seconds=left)).isoformat()
            conn.execute('UPDATE studio_sessions SET state=?,deadline_at=?,paused_at=NULL,epoch=epoch+1 WHERE id=?',(state,deadline,sid))
        event(conn,sid,'timer.'+state,{'remaining_seconds':left,'deadline_at':deadline})
        return {'state':state,'remaining_seconds':left,'deadline_at':deadline,'epoch':s['epoch']+1}
    from backend.app.studio.speech import cancel_tasks
    return mutation(req,sid,x_idempotency_key,{'action':action},act,on_commit=lambda out: cancel_tasks(sid,before_epoch=out['epoch']) if 'epoch' in out else None)

@router.delete('/workspaces/{wid}')
def delete_workspace(req: Request,wid: str,authorization: str = Header(default=''),x_idempotency_key: str = Header(default='')):
    authenticate_workspace(req,wid,token(authorization))
    def act(conn):
        auth_workspace_row(conn,wid,authorization)
        row=conn.execute('SELECT * FROM studio_workspaces WHERE id=?',(wid,)).fetchone()
        if not row or row['deleted_at']: err(410,'Workspace unavailable')
        ids=[r['id'] for r in conn.execute('SELECT id FROM studio_sessions WHERE workspace_id=?',(wid,))]
        from backend.app.db.repository import tombstone_session_in_connection
        linked=[r['session_id'] for r in conn.execute('SELECT session_id FROM workspace_dsa_sessions WHERE workspace_id=?',(wid,))]
        for linked_id in linked:
            tombstone_session_in_connection(conn, linked_id)
        conn.execute('UPDATE studio_workspaces SET deleted_at=? WHERE id=?',(iso(),wid))
        conn.execute('UPDATE studio_sessions SET deleted_at=?,epoch=epoch+1 WHERE workspace_id=?',(iso(),wid))
        for sid in ids:
            from backend.app.studio.speech import cancel_tasks
            cancel_tasks(sid)
            purge_speech_usage(conn,sid)
            from backend.app.studio.model_budget import purge_session
            purge_session(conn,sid)
            conn.execute('DELETE FROM repo_defense_sessions WHERE studio_session_id=?',(sid,))
            for table in ('studio_review_cards','studio_diagrams','studio_events','studio_turns','studio_proposals'): conn.execute(f'DELETE FROM {table} WHERE session_id=?',(sid,))
            conn.execute('DELETE FROM studio_idempotency WHERE owner_id=?',(sid,))
        conn.execute('DELETE FROM repo_snapshots WHERE workspace_id=?',(wid,))
        conn.execute('DELETE FROM studio_idempotency WHERE owner_id=?',(wid,))
        return {'deleted':True}
    from backend.app.repo_learning.lifecycle import cancel_workspace
    return mutation(req,wid,x_idempotency_key,{},act,
                    on_commit=lambda _: cancel_workspace(database_target(req.app.state.settings),wid))

@router.get('/sessions/{sid}/scenario')
def current_scenario(req: Request,sid: str,authorization: str = Header(default='')):
    with closing(connection(req)) as conn:
        s=auth(conn,sid,authorization); spec=json.loads(s['scenario_json']); idx=s['constraint_index']
        c=spec['progressive_constraints'][idx]
        fields=[] if s['posture']=='assessment' and s['state']!='completed' else rule_input_fields(spec,idx)
        return {'required_fields':fields,'id':spec['scenario_id'],'version':spec['scenario_version'],'content_sha256':s['scenario_hash'],'title':spec['title'],'problem_statement':spec['problem_statement'],'prerequisites':spec['prerequisites'],'learning_objectives':spec['learning_objectives'],'clarification_facts':spec['clarification_facts'],'linked_exercise_ids':spec['linked_exercise_ids'],'constraint_index':idx,'transfer_active':in_transfer(conn,sid),'constraint':{'id':c['id'],'title':c['title'],'description':c['description']},'hint_level':s['hint_level']}

@router.get('/sessions/{sid}/evaluation')
def evaluate_current(req: Request,sid: str,authorization: str = Header(default='')):
    with closing(connection(req)) as conn:
        s=auth(conn,sid,authorization)
        graph=json.loads(conn.execute('SELECT graph_json FROM studio_diagrams WHERE session_id=? AND revision=?',(sid,s['diagram_revision'])).fetchone()[0])
        spec=json.loads(s['scenario_json'])
        if s['posture']=='assessment' and s['state']!='completed':
            return {'status':'withheld_until_debrief','checks':[],'semantic_reasoning_status':'unassessed'}
        result=evaluate_scenario(graph,s['scenario_id'],s['constraint_index'],spec=spec,transfer=in_transfer(conn,sid),evidence_verified=repo_stage_verified(conn,s,s['constraint_index']))
        for check in result['checks']: check.pop('required_fields',None)
        return result

@router.get('/sessions/{sid}/clarifications')
def clarifications(req: Request,sid: str,authorization: str = Header(default='')):
    with closing(connection(req)) as conn:
        session=auth(conn,sid,authorization)
        spec=json.loads(session['scenario_json'])
        return {'facts':spec['clarification_facts'],'epoch':session['epoch']}


class CoachAction(Strict): action: str

@router.post('/sessions/{sid}/coach')
def coach(req: Request,sid: str,data: CoachAction,authorization: str = Header(default=''),x_idempotency_key: str = Header(default='')):
    allowed={'clarify','hint','options','sketch','explain','skip','rewind','teachback','transfer','advance','finish','reopen'}
    if data.action not in allowed: err(422,'Unknown coaching action')
    with closing(connection(req)) as conn: auth(conn,sid,authorization)
    def act(conn):
        s=auth(conn,sid,authorization); spec=json.loads(s['scenario_json']); action=data.action; idx=s['constraint_index']; hint=s['hint_level']
        if s['state']=='completed' and action not in {'reopen','explain','transfer','clarify'}: err(409,'Reopen practice before continuing')
        if s['posture']=='assessment' and (action in {'options','sketch','explain','rewind','teachback','transfer'} or (action=='hint' and hint>=1)): err(409,'Switch to teaching to reveal further assistance')
        if action=='clarify':
            text=' '.join(f"{key.replace('_',' ')}: {value}." for key,value in spec['clarification_facts'].items())
        elif action=='hint':
            hint=min(3,hint+1); text=spec['hint_ladder'][f'level_{hint}']
            conn.execute('UPDATE studio_sessions SET hint_level=? WHERE id=?',(hint,sid))
        elif action=='options':
            names=[family['name'] for family in spec['valid_architecture_families']]
            text='Compare these approaches: '+ '; '.join(names)+'. Explain how each addresses '+spec['progressive_constraints'][idx]['title']+'.'
        elif action=='sketch': text='Start with the provided seed graph. For this constraint: '+spec['progressive_constraints'][idx]['description']+' Add a connected component and state its role.'
        elif action=='explain': text=spec['consolidation']
        elif action=='teachback': text='Restate the mechanism, one trade-off, and what remains unverified in your own words.'
        elif action=='transfer': text=spec['fresh_transfer_question']
        elif action=='reopen':
            if s['state']!='completed': err(409,'Session is not completed')
            text='Practice reopened. Previous completion is no longer current.'
            conn.execute("UPDATE studio_sessions SET state='active',posture='teaching',deadline_at=NULL,epoch=epoch+1 WHERE id=?",(sid,))
        elif action=='finish':
            if idx!=3: err(409,'Reach the final constraint first')
            if s['posture']=='teaching':
                history=[(r['sequence'],r['event_type'],json.loads(r['payload_json'])) for r in conn.execute('SELECT sequence,event_type,payload_json FROM studio_events WHERE session_id=? ORDER BY sequence',(sid,))]
                teach=next((seq for seq,kind,payload in reversed(history) if kind=='coach.action' and payload.get('action')=='teachback'),None)
                transfer=next((seq for seq,kind,payload in reversed(history) if kind=='coach.action' and payload.get('action')=='transfer'),None)
                from backend.app.studio.turns import current_recorded_turns
                recorded=current_recorded_turns(conn,sid,history)
                restated=teach is not None and transfer is not None and teach<transfer and any(teach<seq<transfer for seq,_ in recorded)
                attempted=transfer is not None and any(seq>transfer for seq,_ in recorded)
                if not restated or not attempted: err(409,'Submit a teach-back and a transfer response first')
            text='Practice complete. Reasoning remains unassessed without sufficient evidence.'
            conn.execute("UPDATE studio_sessions SET state='completed',epoch=epoch+1 WHERE id=?",(sid,))
            if s['posture']=='teaching':
                transfer_id=next(tid for seq,tid in reversed(recorded) if seq>transfer)
                evidence=conn.execute('SELECT id FROM studio_turns WHERE id=? AND session_id=?',(transfer_id,sid)).fetchone()
            else:
                evidence=conn.execute('SELECT id FROM studio_turns WHERE session_id=? AND superseded_by IS NULL ORDER BY created_at DESC,rowid DESC LIMIT 1',(sid,)).fetchone()
            exists=conn.execute('SELECT id FROM studio_review_cards WHERE session_id=? AND prompt=?',(sid,spec['fresh_transfer_question'])).fetchone()
            if evidence and not exists:
                from fsrs import Card
                card=Card(); cid=str(uuid.uuid4())
                conn.execute('INSERT INTO studio_review_cards VALUES(?,?,?,?,?,?,?)',(cid,s['workspace_id'],sid,spec['fresh_transfer_question'],encode([{'turn_id':evidence['id']}]),card.to_json(),card.due.isoformat()))
                event(conn,sid,'review.created',{'card_id':cid,'evidence_turn_id':evidence['id'],'scheduler':'fsrs-6.3.3'})
        else:
            if action=='advance':
                graph=json.loads(conn.execute('SELECT graph_json FROM studio_diagrams WHERE session_id=? AND revision=?',(sid,s['diagram_revision'])).fetchone()[0])
                outcome=evaluate_scenario(graph,s['scenario_id'],idx,spec=spec,evidence_verified=repo_stage_verified(conn,s,idx))
                if outcome['status']!='satisfied_under_declared_assumptions': err(409,'Current modeled checks are not satisfied; revise or explicitly skip')
            complete=False
            idx=max(0,idx-1) if action=='rewind' else min(3,idx+1)
            text='Practice complete. Reasoning remains unassessed without sufficient evidence.' if complete else spec['progressive_constraints'][idx]['description']
            conn.execute('UPDATE studio_sessions SET constraint_index=?,hint_level=0,epoch=epoch+1,state=? WHERE id=?',(idx,'completed' if complete else s['state'],sid))
        phases={'clarify':'clarify','hint':'hint','options':'hint','sketch':'proposal','explain':'consolidation','teachback':'consolidation','transfer':'transfer','advance':'challenge','skip':'challenge','rewind':'decision','finish':'completed','reopen':'revision'}
        phase='consolidation' if action=='advance' and s['constraint_index']==3 else phases[action]
        payload={'action':action,'phase':phase,'assistance':action in {'hint','options','sketch','explain','skip','reopen'},'text':text,'constraint_index':idx,'hint_level':hint if action in {'hint','options','sketch','explain','teachback','transfer'} else 0,'epoch':s['epoch']+(action in {'advance','skip','rewind','finish','reopen'}),'feedback_status':'unassessed'}
        payload={**payload,'validated':True,**({'facts':spec['clarification_facts']} if action=='clarify' else {})}
        event(conn,sid,'coach.action',payload)
        return payload
    from backend.app.studio.speech import cancel_tasks
    return mutation(req,sid,x_idempotency_key,data.model_dump(),act,on_commit=lambda out: cancel_tasks(sid,before_epoch=out['epoch']) if 'epoch' in out else None)

@router.post('/workspaces/{wid}/extend')
def extend_workspace(req: Request,wid: str,authorization: str = Header(default=''),x_idempotency_key: str = Header(default='')):
    authenticate_workspace(req,wid,token(authorization))
    def act(conn):
        auth_workspace_row(conn,wid,authorization)
        expiry=(now()+timedelta(days=30)).isoformat()
        conn.execute('UPDATE studio_workspaces SET expires_at=? WHERE id=?',(expiry,wid))
        conn.execute('UPDATE studio_sessions SET expires_at=? WHERE workspace_id=? AND deleted_at IS NULL AND expires_at>?',(expiry,wid,iso()))
        return {'workspace_id':wid,'expires_at':expiry,'retention':'Review cards expire with the workspace or when their session is deleted.'}
    return mutation(req,wid,x_idempotency_key,{},act)

class PostureChange(Strict): posture: str
@router.post('/sessions/{sid}/posture')
def change_posture(req: Request,sid: str,data: PostureChange,authorization: str = Header(default=''),x_idempotency_key: str = Header(default='')):
    if data.posture!='teaching': err(422,'Only an explicit switch to teaching is supported')
    with closing(connection(req)) as c: auth(c,sid,authorization)
    def act(conn):
        s=auth(conn,sid,authorization)
        if s['posture']!='assessment': err(409,'Session already uses teaching posture')
        conn.execute("UPDATE studio_sessions SET posture=?,state='active',deadline_at=NULL,paused_at=NULL,epoch=epoch+1 WHERE id=?",('teaching',sid))
        payload={'posture':'teaching','epoch':s['epoch']+1,'phase':'hint','assistance':True,'assessment_interrupted':True}
        event(conn,sid,'posture.changed',payload)
        return payload
    from backend.app.studio.speech import cancel_tasks
    return mutation(req,sid,x_idempotency_key,data.model_dump(),act,on_commit=lambda out: cancel_tasks(sid,before_epoch=out['epoch']) if 'epoch' in out else None)
