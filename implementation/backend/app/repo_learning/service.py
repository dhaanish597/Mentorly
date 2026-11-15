"""Immutable sanitized repository snapshots and evidence retrieval."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from contextlib import closing
import json
import re
import sqlite3
import uuid
from backend.app.db.migrations import open_connection
from .ingest import chunk_spans, digest, structure
from . import idempotency, lifecycle


def recover_incomplete(db_path: str) -> None:
    with closing(open_connection(db_path)) as db:
        from backend.app.db.postgres.runtime import PostgresTarget
        if isinstance(db_path, PostgresTarget):
            cutoff = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
            db.execute("UPDATE repo_snapshots SET status='FAILED', failure_code='INTERRUPTED' WHERE status IN ('QUEUED','INDEXING') AND created_at<?", (cutoff,))
        else:
            db.execute("UPDATE repo_snapshots SET status='FAILED', failure_code='INTERRUPTED' WHERE status IN ('QUEUED','INDEXING')")


def make_id(): return str(uuid.uuid4())
def now(): return datetime.now(timezone.utc).isoformat()

def _rank(paths, structures):
    by_name = {}
    for path in paths:
        name = path.rsplit('/', 1)[-1].rsplit('.', 1)[0]
        by_name.setdefault(name, []).append(path)
    edges = {}
    for path in paths:
        tokens = set(re.findall(r'[A-Za-z_][A-Za-z0-9_]*', ' '.join(structures[path]['imports'])))
        edges[path] = sorted({target for token in tokens for target in by_name.get(token, ()) if target != path})[:256]
    if not paths: return {}
    ranks = {p:1/len(paths) for p in paths}
    for _ in range(20):
        dangling = sum(ranks[p] for p in paths if not edges[p]) / len(paths)
        next_rank = {p:0.15/len(paths)+0.85*dangling for p in paths}
        for p in paths:
            for q in edges[p]: next_rank[q] += 0.85*ranks[p]/len(edges[p])
        ranks = next_rank
    return ranks

WORKSPACE_SNAPSHOT_LIMIT = 5
GLOBAL_SNAPSHOT_LIMIT = 25
WORKSPACE_BYTE_LIMIT = 100 * 1024 * 1024
GLOBAL_BYTE_LIMIT = 500 * 1024 * 1024
PENDING_RESERVATION = 20 * 1024 * 1024
SNAPSHOT_OVERHEAD = 128 * 1024
FILE_OVERHEAD = 2048
CHUNK_OVERHEAD = 2048

class QuotaExceeded(ValueError):
    pass

def _snapshot_charge(files, structures=None):
    # Charge the actual symbol partition, including metadata and FTS overhead.
    structures = structures if structures is not None else {path: structure(path, text) for path, text in files.items()}
    return SNAPSHOT_OVERHEAD + sum(8 * len(text.encode('utf-8')) + FILE_OVERHEAD + CHUNK_OVERHEAD * len(chunk_spans(text, structures[path])) for path, text in files.items())

def _usage(db, workspace, exclude=None):
    rows=db.execute("""SELECT s.id,s.workspace_id,s.status,
      COALESCE((SELECT SUM(8*length(CAST(f.content AS BLOB)) + ?) FROM repo_files f WHERE f.snapshot_id=s.id),0) +
      COALESCE((SELECT COUNT(*)*? FROM repo_chunks c WHERE c.snapshot_id=s.id),0) AS charge
      FROM repo_snapshots s WHERE (? IS NULL OR s.id!=?)""",(FILE_OVERHEAD,CHUNK_OVERHEAD,exclude,exclude)).fetchall()
    ws_count=global_count=ws_bytes=global_bytes=0
    for row in rows:
        charge=PENDING_RESERVATION if row['status'] in ('QUEUED','INDEXING') else SNAPSHOT_OVERHEAD+row['charge']
        global_count+=1; global_bytes+=charge
        if row['workspace_id']==workspace: ws_count+=1; ws_bytes+=charge
    return ws_count,global_count,ws_bytes,global_bytes

def _check_quota(db, workspace, prospective_bytes, exclude=None):
    wc,gc,wb,gb=_usage(db,workspace,exclude)
    if wc+1>WORKSPACE_SNAPSHOT_LIMIT or gc+1>GLOBAL_SNAPSHOT_LIMIT or wb+prospective_bytes>WORKSPACE_BYTE_LIMIT or gb+prospective_bytes>GLOBAL_BYTE_LIMIT:
        raise QuotaExceeded('repository storage quota exceeded')

def _queue(db, workspace, source_kind, source_locator):
    _check_quota(db,workspace,PENDING_RESERVATION)
    if db.execute("SELECT count(*) FROM repo_snapshots WHERE status IN ('QUEUED','INDEXING')").fetchone()[0] >= 4:
        raise RuntimeError('ingestion capacity reached')
    row=db.execute('SELECT 1 FROM studio_workspaces WHERE id=? AND deleted_at IS NULL AND expires_at>?',(workspace,now())).fetchone()
    if not row: raise ValueError('workspace unavailable')
    snapshot_id = make_id()
    db.execute("INSERT INTO repo_snapshots(id,workspace_id,source_kind,source_locator,status,created_at) VALUES (?,?,?,?,'QUEUED',?)",(snapshot_id,workspace,source_kind,source_locator,now()))
    return snapshot_id


def queue(db_path: str, workspace: str, source_kind: str, source_locator: str | None = None) -> str:
    with closing(open_connection(db_path)) as db:
        db.execute('BEGIN IMMEDIATE')
        snapshot_id = _queue(db, workspace, source_kind, source_locator)
        db.commit()
    return snapshot_id


def queue_import(db_path: str, workspace: str, source_kind: str, source_locator: str | None,
                 request_hash: str, key: str | None = None) -> tuple[dict, bool]:
    retry_key = idempotency.key_for(key, request_hash)
    with closing(open_connection(db_path)) as db:
        db.execute('BEGIN IMMEDIATE')
        response = idempotency.replay(db, workspace, 'ingest', retry_key, request_hash)
        if response is not None:
            return response, False
        snapshot_id = _queue(db, workspace, source_kind, source_locator)
        response = {'snapshot_id': snapshot_id, 'status': 'QUEUED', 'progress_url': f'/api/v1/repos/{snapshot_id}'}
        idempotency.remember(db, workspace, 'ingest', retry_key, request_hash, snapshot_id, response)
        db.commit()
    return response, True

def import_live(db_path: str, workspace: str, snapshot_id: str) -> bool:
    with closing(open_connection(db_path)) as db:
        return db.execute("SELECT 1 FROM repo_snapshots s JOIN studio_workspaces w ON w.id=s.workspace_id WHERE s.id=? AND s.workspace_id=? AND s.status IN ('QUEUED','INDEXING') AND w.deleted_at IS NULL AND w.expires_at>?", (snapshot_id, workspace, now())).fetchone() is not None


def fail(db_path: str, snapshot_id: str, code: str = 'IMPORT_FAILED') -> None:
    with closing(open_connection(db_path)) as db:
        db.execute("UPDATE repo_snapshots SET status='FAILED',failure_code=? WHERE id=? AND status IN ('QUEUED','INDEXING')",(code,snapshot_id))

def create(db_path: str, workspace: str, source_kind: str, files: dict[str,str], coverage: dict, snapshot_id: str | None = None) -> dict:
    if not files: raise ValueError('no indexable files')
    if snapshot_id is None: snapshot_id=queue(db_path,workspace,source_kind)
    with closing(open_connection(db_path)) as db:
        changed=db.execute("UPDATE repo_snapshots SET status='INDEXING' WHERE id=? AND workspace_id=? AND status='QUEUED'",(snapshot_id,workspace)).rowcount
        if changed != 1: raise ValueError('ingestion unavailable')
    try:
        paths=sorted(files); structures={}
        for number, path in enumerate(paths, 1):
            structures[path]=structure(path,files[path])
            if number == 1 or number % 25 == 0 or number == len(paths):
                progress=dict(coverage, stage='parsing', parsed_so_far=number, indexable_files=len(paths))
                with closing(open_connection(db_path)) as db:
                    updated=db.execute("UPDATE repo_snapshots SET total_files=?,coverage_json=? WHERE id=? AND workspace_id=? AND status='INDEXING' AND EXISTS (SELECT 1 FROM studio_workspaces w WHERE w.id=repo_snapshots.workspace_id AND w.deleted_at IS NULL AND w.expires_at>?)",(coverage['total'],json.dumps(progress),snapshot_id,workspace,now())).rowcount
                    if not updated: raise ValueError('ingestion cancelled')
        ranks=_rank(paths,structures)
        hashes = {p:digest(files[p].encode()) for p in paths}
        snapshot_hash=digest(json.dumps(hashes,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode())
        coverage = dict(coverage, parsed=sum(x['status']=='parsed' for x in structures.values()), lexical=sum(x['status']=='lexical' for x in structures.values()), parse_errors=sum(x['status'] not in ('parsed','lexical') for x in structures.values()))
        with closing(open_connection(db_path)) as db:
            db.execute('BEGIN IMMEDIATE')
            _check_quota(db,workspace,_snapshot_charge(files, structures),snapshot_id)
            for p in paths:
                file_id=make_id(); info=structures[p]; text=files[p]
                db.execute('INSERT INTO repo_files VALUES (?,?,?,?,?,?,?,?,?,?,?)',(file_id,snapshot_id,p,text,hashes[p],info['language'],info['status'],json.dumps(info['imports']),json.dumps(info['calls']),json.dumps(info['symbols']),ranks[p]))
                lines=text.splitlines(keepends=True)
                for symbol,start,end in chunk_spans(text, info):
                    part=''.join(lines[start-1:end]); chunk_id=make_id(); ch=digest(part.encode())
                    db.execute('INSERT INTO repo_chunks VALUES (?,?,?,?,?,?,?,?,?)',(chunk_id,snapshot_id,file_id,p,symbol,start,end,ch,part))
                    db.execute('INSERT INTO repo_chunks_fts(chunk_id,snapshot_id,text) VALUES (?,?,?)',(chunk_id,snapshot_id,part))
            updated = db.execute("UPDATE repo_snapshots SET status='READY',snapshot_hash=?,total_files=?,files_indexed=?,coverage_json=? WHERE id=? AND status='INDEXING' AND EXISTS (SELECT 1 FROM studio_workspaces w WHERE w.id=repo_snapshots.workspace_id AND w.deleted_at IS NULL AND w.expires_at>?)",(snapshot_hash,coverage['total'],len(files),json.dumps(coverage),snapshot_id,now())).rowcount
            if updated != 1: raise ValueError('workspace unavailable')
            source=db.execute('SELECT source_locator FROM repo_snapshots WHERE id=?',(snapshot_id,)).fetchone()
            if source and source['source_locator']=='REPO-EXP-01':
                curated=('backend/app/main.py','backend/app/api/routes_sessions.py','backend/app/orchestration/worker_client.py','backend/app/orchestration/state_machine.py','backend/app/speech/routes.py','backend/app/db/repository.py','exec_worker/worker_app/sandbox_runner.py','exec_worker/worker_app/verifier_harness.py')
                for path in curated:
                    chunk=db.execute('SELECT path,symbol,start_line,end_line,chunk_hash FROM repo_chunks WHERE snapshot_id=? AND path=? ORDER BY start_line LIMIT 1',(snapshot_id,path)).fetchone()
                    if chunk:
                        citation=dict(chunk)
                        card={'topic':'Inspect '+path,'observed_code':[citation],'explicit_docs':[],'inferred_rationale':[],'learner_alternative':None,'author_intent_verifiable':False}
                        db.execute('INSERT INTO repo_evidence_cards VALUES (?,?,?,?,?,?,?)',(make_id(),snapshot_id,workspace,card['topic'],json.dumps(card),now(),'curated'))
            db.commit()
    except Exception as exc:
        with closing(open_connection(db_path)) as db:
            db.execute("UPDATE repo_snapshots SET status='FAILED',failure_code=? WHERE id=? AND status IN ('QUEUED','INDEXING')",('QUOTA_EXCEEDED' if isinstance(exc,QuotaExceeded) else 'INDEX_FAILED',snapshot_id))
        raise
    return get(db_path,workspace,snapshot_id)

def get(db_path,workspace,snapshot_id):
    with closing(open_connection(db_path)) as db:
        row=db.execute('SELECT * FROM repo_snapshots WHERE id=? AND workspace_id=?',(snapshot_id,workspace)).fetchone()
        if row is None: raise LookupError('snapshot not found')
        d=dict(row); d['snapshot_id']=d.pop('id'); d['coverage']=json.loads(d.pop('coverage_json')); d['coverage_ratio'] = d['files_indexed']/d['total_files'] if d['total_files'] else 0
        return d

def get_file(db_path,workspace,snapshot_id,path):
    get(db_path,workspace,snapshot_id)
    with closing(open_connection(db_path)) as db:
        row=db.execute('SELECT path,content,content_hash FROM repo_files WHERE snapshot_id=? AND path=?',(snapshot_id,path)).fetchone()
        if not row: raise LookupError('file not found')
        return dict(row)

def repo_map(db_path,workspace,snapshot_id):
    get(db_path,workspace,snapshot_id)
    with closing(open_connection(db_path)) as db:
        rows=db.execute('SELECT path,rank,language,parse_status,imports_json,calls_json,symbols_json FROM repo_files WHERE snapshot_id=? ORDER BY rank DESC,path',(snapshot_id,)).fetchall()
    result=[]
    for row in rows:
        item=dict(row)
        for k in ('imports','calls','symbols'): item[k]=json.loads(item.pop(k+'_json'))
        result.append(item)
    by_name = {}
    for entry in result:
        name=entry['path'].rsplit('/',1)[-1].rsplit('.',1)[0]
        by_name.setdefault(name,[]).append(entry['path'])
    edges=[]
    for entry in result:
        tokens=set(re.findall(r'[A-Za-z_][A-Za-z0-9_]*',' '.join(entry['imports'])))
        targets=sorted({target for token in tokens for target in by_name.get(token,()) if target != entry['path']})
        edges.extend({'source':entry['path'],'target':target,'basis':'static import name match; unverified'} for target in targets[:256])
    return {'files':result,'edges':edges,'note':'Static import-name matches are approximate; calls and runtime behavior are not verified.'}

def search(db_path,workspace,snapshot_id,query):
    get(db_path,workspace,snapshot_id)
    terms=re.findall(r'[\w]+',query,flags=re.UNICODE)[:12]
    if not terms: return {'results':[]}
    match=' OR '.join('"'+t+'"' for t in terms)
    with closing(open_connection(db_path)) as db:
        rows=db.execute('SELECT c.path,c.symbol,c.start_line,c.end_line,c.chunk_hash,c.text FROM repo_chunks_fts f JOIN repo_chunks c ON c.id=f.chunk_id WHERE repo_chunks_fts MATCH ? AND f.snapshot_id=? AND c.snapshot_id=? ORDER BY bm25(repo_chunks_fts) LIMIT 20',(match,snapshot_id,snapshot_id)).fetchall()
        return {'results':[dict(r) for r in rows]}

def validate_citation(db_path,workspace,snapshot_id,citation):
    get(db_path,workspace,snapshot_id)
    with closing(open_connection(db_path)) as db:
        row=db.execute('SELECT text FROM repo_chunks WHERE snapshot_id=? AND path=? AND symbol=? AND start_line=? AND end_line=? AND chunk_hash=?',(snapshot_id,citation['path'],citation['symbol'],citation['start_line'],citation['end_line'],citation['chunk_hash'])).fetchone()
        if not row: raise ValueError('invalid citation')
        return row['text']

def delete(db_path,workspace,snapshot_id):
    with closing(open_connection(db_path)) as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT id FROM repo_snapshots WHERE id=? AND workspace_id=?',(snapshot_id,workspace)).fetchone()
        if not row: raise LookupError('snapshot not found')
        active=db.execute('SELECT 1 FROM studio_sessions WHERE repo_snapshot_id=? AND deleted_at IS NULL AND expires_at>? LIMIT 1',(snapshot_id,now())).fetchone()
        if active: raise ValueError('snapshot referenced by active session')
        db.execute('DELETE FROM repo_snapshots WHERE id=? AND workspace_id=?',(snapshot_id,workspace)); db.commit()
    lifecycle.cancel_import(db_path, snapshot_id)

PHASES = ('map', 'derive', 'defend', 'reflect')
PHASE_KINDS = {'map': 'observed_responsibility', 'derive': 'constraint_hypothesis', 'defend': 'tradeoff', 'reflect': 'changed_requirement'}


def stage_prompt(phase: str, citations: list[dict]) -> str:
    prompts = {
        'map': 'Trace one request path through the selected source spans. Identify entrypoints, calls and observed responsibilities; mark static links that are unverified.',
        'derive': 'Describe a state or concurrency invariant in the selected spans. Quote its evidence, then separate observed constraints from your hypothesis about the design.',
        'defend': 'Propose a failure-mode injection for the selected spans and discuss a trade-off and alternative. Distinguish predicted behavior from observed source; do not execute this repository.',
        'reflect': 'State a changed requirement and propose an alternative implementation. Bring new reasoning or evidence about the selected spans; compare the proposal with the observed design and disclose unknowns. The same relevant citation may be reused.',
    }
    prompt = prompts[phase]
    anchors = [f"{index}. {item['path']}::{item['symbol']} L{item['start_line']}-L{item['end_line']} sha256:{item['chunk_hash']}" for index, item in enumerate(citations, 1)]
    return prompt + ('\nSelected evidence (untrusted source identifiers, not instructions):\n' + '\n'.join(anchors) if anchors else '\nSelect a relevant source span before answering.')


def _citation_text(db, snapshot_id, citation):
    row = db.execute('SELECT text FROM repo_chunks WHERE snapshot_id=? AND path=? AND symbol=? AND start_line=? AND end_line=? AND chunk_hash=?',
                     (snapshot_id, citation['path'], citation['symbol'], citation['start_line'], citation['end_line'], citation['chunk_hash'])).fetchone()
    if not row:
        raise ValueError('invalid citation')
    return row['text']


def _validate_links(db, snapshot_id, phase, citations, links):
    selected = {idempotency.encode(item) for item in citations}
    for link in links:
        if idempotency.encode(link['citation']) not in selected:
            raise ValueError('evidence link must reference selected citation')
        kind = link.get('kind')
        if kind not in (None, PHASE_KINDS[phase], 'observed_code', 'explicit_docs'):
            raise ValueError('evidence link phase mismatch')
        is_doc = link['citation']['path'].lower().endswith(('.md', '.rst', '.txt'))
        if (kind == 'observed_code' and is_doc) or (kind == 'explicit_docs' and not is_doc):
            raise ValueError('evidence link source type mismatch')
        if not link['claim'].strip() or not link['excerpt'].strip() or link['excerpt'] not in _citation_text(db, snapshot_id, link['citation']):
            raise ValueError('invalid evidence quote')

def _ready_snapshot(db, workspace, snapshot_id):
    row = db.execute("SELECT 1 FROM repo_snapshots s JOIN studio_workspaces w ON w.id=s.workspace_id WHERE s.id=? AND s.workspace_id=? AND s.status='READY' AND w.deleted_at IS NULL AND w.expires_at>?", (snapshot_id, workspace, now())).fetchone()
    if not row:
        raise LookupError('snapshot not found')


def save_evidence(db_path, workspace, snapshot_id, card, key=None):
    request_hash = idempotency.fingerprint(card)
    retry_key = idempotency.key_for(key, request_hash)
    operation = 'evidence:' + snapshot_id
    with closing(open_connection(db_path)) as db:
        db.execute('BEGIN IMMEDIATE')
        _ready_snapshot(db, workspace, snapshot_id)
        previous = idempotency.replay(db, workspace, operation, retry_key, request_hash)
        if previous is not None:
            return previous
        for item in card['observed_code']+card['explicit_docs']:
            row=db.execute('SELECT text FROM repo_chunks WHERE snapshot_id=? AND path=? AND symbol=? AND start_line=? AND end_line=? AND chunk_hash=?',(snapshot_id,item['path'],item['symbol'],item['start_line'],item['end_line'],item['chunk_hash'])).fetchone()
            if not row or ('excerpt' in item and item['excerpt'] not in row['text']): raise ValueError('invalid citation')
        if db.execute('SELECT count(*) FROM repo_evidence_cards WHERE snapshot_id=?',(snapshot_id,)).fetchone()[0] >= 100: raise QuotaExceeded('evidence limit exceeded')
        card_id=make_id()
        db.execute('INSERT INTO repo_evidence_cards VALUES (?,?,?,?,?,?,?)',(card_id,snapshot_id,workspace,card['topic'],json.dumps(card),now(),'learner'))
        response = {'evidence_card_id':card_id,**card}
        idempotency.remember(db, workspace, operation, retry_key, request_hash, snapshot_id, response, evidence_card_id=card_id)
        db.commit()
    return response

def list_evidence(db_path, workspace, snapshot_id):
    get(db_path,workspace,snapshot_id)
    with closing(open_connection(db_path)) as db:
        rows=db.execute('SELECT id,origin,evidence_json FROM repo_evidence_cards WHERE snapshot_id=? AND workspace_id=? ORDER BY created_at,id',(snapshot_id,workspace)).fetchall()
        return {'cards':[{'evidence_card_id':r['id'],'origin':r['origin'],**json.loads(r['evidence_json'])} for r in rows]}

def _session(db, workspace, session_id, session_token):
    import hmac
    from backend.app.studio.security import digest_token
    row=db.execute('SELECT * FROM studio_sessions WHERE id=? AND workspace_id=?',(session_id,workspace)).fetchone()
    if not row or not session_token or not hmac.compare_digest(row['token_hash'] if row else '0'*64,digest_token(session_token)):
        raise PermissionError('invalid session')
    owner = db.execute('SELECT deleted_at,expires_at FROM studio_workspaces WHERE id=?', (workspace,)).fetchone()
    if row['deleted_at'] or row['expires_at']<=now() or row['state']!='active' or not owner or owner['deleted_at'] or owner['expires_at']<=now(): raise PermissionError('invalid session')
    return row

def _publish_defense_prompt(db, session, phase, citations):
    latest = db.execute("SELECT payload_json FROM studio_events WHERE session_id=? AND event_type='coach.action' ORDER BY sequence DESC LIMIT 1", (session['id'],)).fetchone()
    if latest:
        previous = json.loads(latest['payload_json'])
        if previous.get('source') == 'authored_repo_defense' and previous.get('epoch') == session['epoch'] and previous.get('phase') == phase and previous.get('snapshot_id') == session['repo_snapshot_id']:
            return
    selected = []
    for item in citations:
        _citation_text(db, session['repo_snapshot_id'], item)
        selected.append({key: item[key] for key in ('path','symbol','start_line','end_line','chunk_hash')})
    # Speech uses fixed authored prose only. Source identifiers are data in the
    # event, never imported instructions, learner prose or an external prompt.
    text = stage_prompt(phase, []).split('\n', 1)[0] if phase in PHASES else 'Your cited learner statements are recorded. This summary is unassessed; runtime behavior and undocumented author intent remain unknown.'
    payload = {'action':'repo_defense_prompt','source':'authored_repo_defense','validated':True,
               'phase':phase,'epoch':session['epoch'],'diagram_revision':session['diagram_revision'],
               'snapshot_id':session['repo_snapshot_id'],'citations':selected,'text':text}
    sequence = db.execute('SELECT COALESCE(MAX(sequence),0)+1 FROM studio_events WHERE session_id=?', (session['id'],)).fetchone()[0]
    db.execute('INSERT INTO studio_events VALUES (?,?,?,?,?)', (session['id'],sequence,'coach.action',json.dumps(payload),now()))
    db.execute('DELETE FROM studio_events WHERE session_id=? AND sequence<=?', (session['id'],sequence-5000))


def defense_start(db_path,workspace,snapshot_id,session_id,session_token):
    with closing(open_connection(db_path)) as db:
        db.execute('BEGIN IMMEDIATE')
        session=_session(db,workspace,session_id,session_token)
        snapshot=db.execute("SELECT 1 FROM repo_snapshots WHERE id=? AND workspace_id=? AND status='READY'",(snapshot_id,workspace)).fetchone()
        if not snapshot or session['repo_snapshot_id']!=snapshot_id or session['mode'] not in ('repo_exploration','project_defense'): raise ValueError('session not bound to snapshot')
        row=db.execute('SELECT id,phase FROM repo_defense_sessions WHERE studio_session_id=?',(session_id,)).fetchone()
        if not row:
            db.execute('INSERT INTO repo_defense_sessions VALUES (?,?,?,?,?,?)',(make_id(),session_id,snapshot_id,workspace,'map',now()))
        phase = row['phase'] if row else 'map'
        summary = _repo_session_summary(db,workspace,session_id)
        if summary is None:
            raise PermissionError('invalid session')
        _publish_defense_prompt(db,session,phase,summary['history'][-1]['citations'] if summary['history'] else [])
        db.commit()
    return summary

def defense_answer(db_path,workspace,snapshot_id,session_id,session_token,expected_phase,answer,citations,
                   evidence_links=None,changed_requirement=None,learner_alternative=None,unknowns=None,key=None):
    links = evidence_links or []
    unknowns = unknowns or []
    request_hash = idempotency.fingerprint({'phase': expected_phase, 'answer': answer, 'citations': citations, 'evidence_links': links,
                                           'changed_requirement': changed_requirement, 'learner_alternative': learner_alternative, 'unknowns': unknowns})
    retry_key = idempotency.key_for(key, request_hash)
    operation = 'defense_answer:' + session_id
    with closing(open_connection(db_path)) as db:
        db.execute('BEGIN IMMEDIATE'); session=_session(db,workspace,session_id,session_token)
        _ready_snapshot(db, workspace, snapshot_id)
        if session['repo_snapshot_id'] != snapshot_id: raise ValueError('session not bound to snapshot')
        defense=db.execute('SELECT * FROM repo_defense_sessions WHERE studio_session_id=? AND snapshot_id=? AND workspace_id=?',(session_id,snapshot_id,workspace)).fetchone()
        if not defense: raise LookupError('defense not found')
        previous = idempotency.replay(db, workspace, operation, retry_key, request_hash)
        if previous is not None:
            return previous
        if defense['phase']!=expected_phase or expected_phase not in PHASES: raise ValueError('phase conflict')
        if not answer.strip() or not citations:
            raise ValueError('answer and source evidence required')
        for item in citations:
            _citation_text(db, snapshot_id, item)
        _validate_links(db, snapshot_id, expected_phase, citations, links)
        if expected_phase == 'reflect' and session['mode'] == 'project_defense':
            # Appendix E, REPO-DEF-02: live requirement change proposal. This is
            # a structural submission requirement, never a correctness score.
            if not changed_requirement or not changed_requirement.strip() or not learner_alternative or not learner_alternative.strip():
                raise ValueError('changed requirement and proposal required')
        sequence=db.execute('SELECT count(*) FROM repo_defense_answers WHERE defense_id=?',(defense['id'],)).fetchone()[0]+1
        answer_id = make_id()
        db.execute('INSERT INTO repo_defense_answers VALUES (?,?,?,?,?,?,?)',(answer_id,defense['id'],sequence,expected_phase,answer,json.dumps(citations),now()))
        db.execute('INSERT INTO repo_defense_answer_evidence VALUES (?,?,?,?,?)', (answer_id,json.dumps(links),changed_requirement,learner_alternative,json.dumps(unknowns)))
        index=PHASES.index(expected_phase); next_phase=PHASES[index+1] if index+1<len(PHASES) else 'complete'
        db.execute('UPDATE repo_defense_sessions SET phase=? WHERE id=?',(next_phase,defense['id']))
        db.execute('UPDATE studio_sessions SET epoch=epoch+1 WHERE id=?', (session_id,))
        session = db.execute('SELECT * FROM studio_sessions WHERE id=?', (session_id,)).fetchone()
        _publish_defense_prompt(db,session,next_phase,citations)
        response = _repo_session_summary(db,workspace,session_id)
        if response is None:
            raise ValueError('session unavailable')
        idempotency.remember(db, workspace, operation, retry_key, request_hash, snapshot_id, response, studio_session_id=session_id, defense_id=defense['id'])
        db.commit()
    from backend.app.studio.speech import cancel_tasks
    cancel_tasks(session_id, before_epoch=session['epoch'])
    return response

def _repo_session_summary(db,workspace_id,studio_session_id):
    row=db.execute("SELECT d.*,s.mode FROM repo_defense_sessions d JOIN studio_sessions s ON s.id=d.studio_session_id JOIN repo_snapshots r ON r.id=d.snapshot_id AND r.workspace_id=d.workspace_id JOIN studio_workspaces w ON w.id=d.workspace_id WHERE d.workspace_id=? AND d.studio_session_id=? AND s.workspace_id=? AND s.repo_snapshot_id=d.snapshot_id AND s.deleted_at IS NULL AND s.expires_at>? AND w.deleted_at IS NULL AND w.expires_at>? AND r.status='READY'",(workspace_id,studio_session_id,workspace_id,now(),now())).fetchone()
    if not row: return None
    answers=db.execute('SELECT a.phase,a.answer,a.citations_json,a.created_at,e.evidence_links_json,e.changed_requirement,e.learner_alternative,e.unknowns_json FROM repo_defense_answers a LEFT JOIN repo_defense_answer_evidence e ON e.answer_id=a.id WHERE a.defense_id=? ORDER BY a.sequence',(row['id'],)).fetchall()
    history=[{'phase':a['phase'],'answer':a['answer'],'citations':json.loads(a['citations_json']),'created_at':a['created_at'],
              'evidence_links':json.loads(a['evidence_links_json'] or '[]'),'changed_requirement':a['changed_requirement'],
              'learner_alternative':a['learner_alternative'],'unknowns':json.loads(a['unknowns_json'] or '[]'),
              'evidence_status':'explicit_quote_linked_unassessed' if a['evidence_links_json'] and a['evidence_links_json'] != '[]' else 'citation_attached_unassessed'} for a in answers]
    prompt = stage_prompt(row['phase'], history[-1]['citations'] if history else []) if row['phase'] in PHASES else None
    required_fields = ['changed_requirement', 'learner_alternative'] if row['phase'] == 'reflect' and row['mode'] == 'project_defense' else []
    return {'defense_id':row['id'],'snapshot_id':row['snapshot_id'],'phase':row['phase'],'mode':row['mode'],'prompt':prompt,
            'required_fields':required_fields,'history':history,'synthesis':{
                'basis':'Learner statements and cited source spans; no assessment of truth or author motivation.',
                'assessment_status':'unassessed','author_intent':'unknown','git_history':'unavailable',
                'statements':[{'phase':a['phase'],'answer':a['answer'],'citations':a['citations'],'evidence_links':a['evidence_links']} for a in history]}}


def repo_session_summary(db_path,workspace_id,studio_session_id):
    with closing(open_connection(db_path)) as db:
        db.execute('BEGIN')
        return _repo_session_summary(db,workspace_id,studio_session_id)

def save_decision(db_path,workspace,snapshot_id,topic,evidence_ids,rationale,learner_alternative,key=None):
    request_hash = idempotency.fingerprint({'topic': topic, 'evidence_ids': evidence_ids, 'rationale': rationale, 'learner_alternative': learner_alternative})
    retry_key = idempotency.key_for(key, request_hash)
    operation = 'decision:' + snapshot_id
    with closing(open_connection(db_path)) as db:
        db.execute('BEGIN IMMEDIATE')
        _ready_snapshot(db, workspace, snapshot_id)
        previous = idempotency.replay(db, workspace, operation, retry_key, request_hash)
        if previous is not None:
            return previous
        for card_id in evidence_ids:
            if not db.execute('SELECT 1 FROM repo_evidence_cards WHERE id=? AND workspace_id=? AND snapshot_id=?',(card_id,workspace,snapshot_id)).fetchone(): raise ValueError('invalid evidence card')
        if db.execute('SELECT count(*) FROM repo_decisions WHERE snapshot_id=?',(snapshot_id,)).fetchone()[0] >= 100: raise QuotaExceeded('decision limit exceeded')
        decision_id=make_id()
        db.execute('INSERT INTO repo_decisions VALUES (?,?,?,?,?,?,?,?)',(decision_id,snapshot_id,workspace,topic,json.dumps(evidence_ids),rationale,learner_alternative,now()))
        response = {'decision_id':decision_id,'topic':topic,'evidence_card_ids':evidence_ids,'inferred_rationale':rationale,'learner_alternative':learner_alternative,'uncertainty':'The rationale is a learner inference, not established author intent.'}
        idempotency.remember(db, workspace, operation, retry_key, request_hash, snapshot_id, response, decision_id=decision_id)
        db.commit()
        return response

def list_decisions(db_path,workspace,snapshot_id):
    get(db_path,workspace,snapshot_id)
    with closing(open_connection(db_path)) as db:
        rows=db.execute('SELECT * FROM repo_decisions WHERE workspace_id=? AND snapshot_id=? ORDER BY created_at,id',(workspace,snapshot_id)).fetchall()
    return {'decisions':[{'decision_id':r['id'],'topic':r['topic'],'evidence_card_ids':json.loads(r['evidence_ids_json']),'inferred_rationale':r['rationale'],'learner_alternative':r['learner_alternative'],'uncertainty':'The rationale is a learner inference, not established author intent.'} for r in rows]}
