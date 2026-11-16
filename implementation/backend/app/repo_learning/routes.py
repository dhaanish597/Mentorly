"""Authenticated workspace-scoped, passive repository learning endpoints."""
from __future__ import annotations
from backend.app.db.migrations import database_target
from email import policy
from email.parser import BytesParser
import asyncio
import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from . import idempotency, ingest, lifecycle, service
from .network import PublicArchiveTransport, public_archive_url
from backend.app.studio.security import authenticate_workspace

router = APIRouter(prefix='/repos', tags=['repository-learning'])

def auth(request, workspace, token):
    authenticate_workspace(request, workspace, token)
    return database_target(request.app.state.settings)

def scope(workspace: str = Header(..., alias='X-Workspace-Id'), token: str = Header(..., alias='X-Workspace-Token')):
    return workspace, token

BODY_IDLE_TIMEOUT = 5.0
BODY_TOTAL_TIMEOUT = 60.0


async def bounded_body(request):
    limit=ingest.MAX_COMPRESSED+1024*1024
    declared=request.headers.get('content-length')
    if declared:
        try: size=int(declared)
        except ValueError: raise HTTPException(400, 'invalid request')
        if size<0 or size>limit: raise HTTPException(413, 'request too large')
    data=bytearray()
    stream = request.stream().__aiter__()
    try:
        async with asyncio.timeout(BODY_TOTAL_TIMEOUT):
            while True:
                try:
                    async with asyncio.timeout(BODY_IDLE_TIMEOUT):
                        chunk = await stream.__anext__()
                except StopAsyncIteration:
                    break
                if len(data)+len(chunk)>limit: raise HTTPException(413, 'request too large')
                data.extend(chunk)
    except TimeoutError as exc:
        raise HTTPException(408, 'request body timeout') from exc
    return bytes(data)

ARCHIVE_TOTAL_TIMEOUT = 20.0


def retry_key(request: Request) -> str | None:
    values = [value for name, value in request.scope.get('headers', []) if name.lower() == b'x-idempotency-key']
    if len(values) > 1:
        raise HTTPException(400, 'one idempotency key required')
    key = request.headers.get('x-idempotency-key')
    if key is not None and not idempotency.KEY_PATTERN.fullmatch(key):
        raise HTTPException(400, 'invalid idempotency key')
    return key


async def fetch_public_archive(locator: str) -> bytes:
    url=public_archive_url(locator)
    try:
        async with asyncio.timeout(ARCHIVE_TOTAL_TIMEOUT):
            async with httpx.AsyncClient(transport=PublicArchiveTransport(), follow_redirects=False, trust_env=False, timeout=httpx.Timeout(20,connect=5)) as client:
                async with client.stream('GET',url,headers={'Accept-Encoding': 'identity'}) as response:
                    # All redirects are rejected, including redirects to private IPs.
                    if response.status_code!=200: raise ingest.ImportFailure('archive unavailable')
                    if response.headers.get('content-encoding', 'identity').lower() != 'identity':
                        raise ingest.ImportFailure('encoded archive response rejected')
                    declared = response.headers.get('content-length')
                    if declared is not None and (not declared.isdigit() or int(declared) > ingest.MAX_COMPRESSED):
                        raise ingest.ImportFailure('archive exceeds compressed limit')
                    data=bytearray()
                    async for chunk in response.aiter_raw():
                        if len(data)+len(chunk)>ingest.MAX_COMPRESSED: raise ingest.ImportFailure('archive exceeds compressed limit')
                        data.extend(chunk)
                    return bytes(data)
    except TimeoutError as exc: raise ingest.ImportFailure('archive download timeout') from exc
    except httpx.HTTPError as exc: raise ingest.ImportFailure('archive unavailable') from exc

async def run_import(db, workspace, snapshot_id, source_kind, locator, raw):
    lifecycle.register(db, snapshot_id, workspace)
    try:
        if not await run_in_threadpool(service.import_live, db, workspace, snapshot_id):
            await run_in_threadpool(service.fail,db,snapshot_id,'IMPORT_CANCELLED')
            return
        if source_kind == 'golden_curated': files,coverage=await run_in_threadpool(ingest.golden,locator)
        else:
            if source_kind == 'public_git_url':
                raw=await fetch_public_archive(locator)
                if not await run_in_threadpool(service.import_live, db, workspace, snapshot_id):
                    return
            files,coverage=await run_in_threadpool(ingest.unpack,raw)
        await run_in_threadpool(service.create,db,workspace,source_kind,files,coverage,snapshot_id)
    except asyncio.CancelledError:
        await run_in_threadpool(service.fail,db,snapshot_id,'IMPORT_CANCELLED')
    except service.QuotaExceeded:
        await run_in_threadpool(service.fail,db,snapshot_id,'QUOTA_EXCEEDED')
    except Exception:
        await run_in_threadpool(service.fail,db,snapshot_id)
    finally:
        lifecycle.unregister(db, snapshot_id)

@router.post('/ingest',status_code=202)
async def import_repo(request: Request, background_tasks: BackgroundTasks, workspace: str = Header(...,alias='X-Workspace-Id'), token: str = Header(...,alias='X-Workspace-Token')):
    db=auth(request,workspace,token)
    key = retry_key(request)
    content_types=[v for k,v in request.scope.get('headers',[]) if k.lower()==b'content-type']
    if len(content_types)!=1: raise HTTPException(400,'one content type required')
    body=await bounded_body(request); content_type=request.headers.get('content-type','')
    raw=None; locator=None
    try:
        if content_type.lower().startswith('multipart/form-data'):
            message=BytesParser(policy=policy.default).parsebytes(b'Content-Type: '+content_type.encode('ascii')+b'\r\nMIME-Version: 1.0\r\n\r\n'+body)
            parts=list(message.iter_parts()) if message.is_multipart() else []
            if len(parts)!=1 or parts[0].get_param('name',header='content-disposition')!='file': raise ingest.ImportFailure('invalid upload')
            raw=parts[0].get_payload(decode=True)
            if raw is None or len(raw)>ingest.MAX_COMPRESSED: raise ingest.ImportFailure('invalid upload')
            source_kind='zip_upload'
        elif content_type.lower().startswith('application/json'):
            import json
            obj=json.loads(body)
            if not isinstance(obj,dict) or set(obj)!={'source_kind','source_locator'} or not isinstance(obj['source_locator'],str) or len(obj['source_locator'])>512: raise ingest.ImportFailure('invalid import request')
            source_kind=obj['source_kind']; locator=obj['source_locator']
            if source_kind not in ('golden_curated','public_git_url'): raise ingest.ImportFailure('unsupported source')
            if source_kind=='golden_curated' and locator not in ('REPO-EXP-01','REPO-EXP-02','REPO-FASTAPI-CORE'): raise ingest.ImportFailure('unknown golden repository')
        else: raise ingest.ImportFailure('unsupported content type')
        request_hash = idempotency.fingerprint({'source_kind': source_kind, 'source_locator': locator, 'archive_hash': ingest.digest(raw) if raw is not None else None})
        response, created = await run_in_threadpool(service.queue_import,db,workspace,source_kind,locator if source_kind=='golden_curated' else None,request_hash,key)
        if created:
            background_tasks.add_task(run_import,db,workspace,response['snapshot_id'],source_kind,locator,raw)
        return response
    except idempotency.IdempotencyConflict as exc: raise HTTPException(409,'idempotency key conflict') from exc
    except idempotency.RetryQuotaExceeded as exc: raise HTTPException(429,'repository retry storage limit reached') from exc
    except service.QuotaExceeded as exc: raise HTTPException(429,'repository storage quota exceeded') from exc
    except RuntimeError as exc: raise HTTPException(429,'repository import capacity reached') from exc
    except (ingest.ImportFailure, ValueError, UnicodeError) as exc: raise HTTPException(422, 'repository import rejected') from exc

@router.get('/{snapshot_id}')
def snapshot(snapshot_id: str, request: Request, workspace: str = Header(...,alias='X-Workspace-Id'), token: str = Header(...,alias='X-Workspace-Token')):
    db=auth(request,workspace,token)
    try: return service.get(db,workspace,snapshot_id)
    except LookupError: raise HTTPException(404,'snapshot not found')

@router.get('/{snapshot_id}/files')
def file(snapshot_id: str, path: str, request: Request, workspace: str = Header(...,alias='X-Workspace-Id'), token: str = Header(...,alias='X-Workspace-Token')):
    db=auth(request,workspace,token)
    try: return service.get_file(db,workspace,snapshot_id,path)
    except LookupError: raise HTTPException(404,'file not found')

@router.get('/{snapshot_id}/map')
def repo_map(snapshot_id: str, request: Request, workspace: str = Header(...,alias='X-Workspace-Id'), token: str = Header(...,alias='X-Workspace-Token')):
    db=auth(request,workspace,token)
    try: return service.repo_map(db,workspace,snapshot_id)
    except LookupError: raise HTTPException(404,'snapshot not found')

@router.get('/{snapshot_id}/search')
def search(snapshot_id: str, q: str, request: Request, workspace: str = Header(...,alias='X-Workspace-Id'), token: str = Header(...,alias='X-Workspace-Token')):
    db=auth(request,workspace,token)
    if len(q)>200: raise HTTPException(422,'query too long')
    try: return service.search(db,workspace,snapshot_id,q)
    except LookupError: raise HTTPException(404,'snapshot not found')

@router.delete('/{snapshot_id}',status_code=204)
def delete(snapshot_id: str, request: Request, workspace: str = Header(...,alias='X-Workspace-Id'), token: str = Header(...,alias='X-Workspace-Token')):
    db=auth(request,workspace,token)
    try: service.delete(db,workspace,snapshot_id)
    except LookupError: raise HTTPException(404,'snapshot not found')
    except ValueError: raise HTTPException(409,'snapshot is in use')

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class Citation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    path: str = Field(min_length=1,max_length=512)
    symbol: str = Field(max_length=256)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    chunk_hash: str = Field(pattern=r'^[0-9a-f]{64}$')

class DocCitation(Citation):
    excerpt: str = Field(min_length=1,max_length=400)

class EvidenceRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    topic: str = Field(min_length=1,max_length=200)
    observed_code: list[Citation] = Field(default_factory=list,max_length=10)
    explicit_docs: list[DocCitation] = Field(default_factory=list,max_length=10)
    inferred_rationale: list[str] = Field(default_factory=list,max_length=10)
    learner_alternative: str | None = Field(default=None,max_length=2000)

@router.post('/{snapshot_id}/evidence')
def evidence(snapshot_id: str, payload: EvidenceRequest, request: Request, workspace: str = Header(...,alias='X-Workspace-Id'), token: str = Header(...,alias='X-Workspace-Token')):
    db=auth(request,workspace,token)
    try:
        for item in payload.observed_code:
            if item.path.lower().endswith(('.md','.rst','.txt')): raise ValueError('code citation must reference code')
            service.validate_citation(db,workspace,snapshot_id,item.model_dump())
        for item in payload.explicit_docs:
            if not item.path.lower().endswith(('.md','.rst','.txt')): raise ValueError('doc citation must reference docs')
            text=service.validate_citation(db,workspace,snapshot_id,item.model_dump())
            if item.excerpt not in text: raise ValueError('excerpt not found')
        if any(not item.strip() or len(item)>400 for item in payload.inferred_rationale): raise ValueError('invalid inference')
        service.get(db,workspace,snapshot_id)
    except LookupError: raise HTTPException(404,'snapshot not found')
    except ValueError: raise HTTPException(422,'invalid evidence citation')
    card={'topic':payload.topic,'observed_code':[c.model_dump() for c in payload.observed_code], 'explicit_docs':[c.model_dump() for c in payload.explicit_docs], 'inferred_rationale':[{'hypothesis':x,'confidence':'speculative_unverified','uncertainty':'Inference; author intent is not established.'} for x in payload.inferred_rationale], 'learner_alternative':payload.learner_alternative, 'author_intent_verifiable':False}
    try: return service.save_evidence(db,workspace,snapshot_id,card,retry_key(request))
    except idempotency.IdempotencyConflict: raise HTTPException(409,'idempotency key conflict')
    except idempotency.RetryQuotaExceeded: raise HTTPException(429,'repository retry storage limit reached')
    except LookupError: raise HTTPException(404,'snapshot not found')
    except service.QuotaExceeded: raise HTTPException(429,'evidence limit reached')
    except ValueError: raise HTTPException(422,'invalid evidence citation')

class DefenseRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    phase: Literal['map','derive','defend','reflect']
    topic: str = Field(min_length=1,max_length=200)
    citations: list[Citation] = Field(default_factory=list,max_length=10)
    learner_alternative: str | None = Field(default=None,max_length=2000)

@router.post('/{snapshot_id}/defense')
def defense(snapshot_id: str, payload: DefenseRequest, request: Request, workspace: str = Header(...,alias='X-Workspace-Id'), token: str = Header(...,alias='X-Workspace-Token')):
    db=auth(request,workspace,token)
    try:
        service.get(db,workspace,snapshot_id)
        for item in payload.citations: service.validate_citation(db,workspace,snapshot_id,item.model_dump())
    except LookupError: raise HTTPException(404,'snapshot not found')
    except ValueError: raise HTTPException(422,'invalid evidence citation')
    selected = [c.model_dump() for c in payload.citations]
    return {'phase':payload.phase,'topic':payload.topic,'prompt':service.stage_prompt(payload.phase, selected),'citations':selected, 'learner_alternative':payload.learner_alternative,'assessment_status':'unassessed','uncertainty':'Static source evidence does not establish runtime behavior or author intent.'}


@router.get('/{snapshot_id}/evidence')
def evidence_list(snapshot_id: str, request: Request, workspace: str = Header(...,alias='X-Workspace-Id'), token: str = Header(...,alias='X-Workspace-Token')):
    db=auth(request,workspace,token)
    try: return service.list_evidence(db,workspace,snapshot_id)
    except LookupError: raise HTTPException(404,'snapshot not found')

class StartDefense(BaseModel):
    model_config=ConfigDict(extra='forbid')
    studio_session_id: str = Field(min_length=1,max_length=128)

class EvidenceLink(BaseModel):
    model_config=ConfigDict(extra='forbid')
    kind: Literal['observed_code','explicit_docs','observed_responsibility','constraint_hypothesis','tradeoff','changed_requirement'] | None = None
    claim: str = Field(min_length=1,max_length=4000)
    citation: Citation
    excerpt: str = Field(min_length=1,max_length=400)


class AnswerDefense(BaseModel):
    model_config=ConfigDict(extra='forbid')
    studio_session_id: str = Field(min_length=1,max_length=128)
    expected_phase: Literal['map','derive','defend','reflect']
    answer: str = Field(min_length=1,max_length=4000)
    citations: list[Citation] = Field(min_length=1,max_length=10)
    evidence_links: list[EvidenceLink] = Field(default_factory=list,max_length=10)
    changed_requirement: str | None = Field(default=None,max_length=2000)
    learner_alternative: str | None = Field(default=None,max_length=2000)
    unknowns: list[str] = Field(default_factory=list,max_length=10)

@router.post('/{snapshot_id}/defense/start')
def start_defense(snapshot_id: str, payload: StartDefense, request: Request, workspace: str = Header(...,alias='X-Workspace-Id'), token: str = Header(...,alias='X-Workspace-Token'), session_token: str = Header(...,alias='X-Session-Token')):
    db=auth(request,workspace,token)
    try: return service.defense_start(db,workspace,snapshot_id,payload.studio_session_id,session_token)
    except PermissionError: raise HTTPException(401,'invalid session capability')
    except ValueError: raise HTTPException(409,'session is not bound to this snapshot')

@router.post('/{snapshot_id}/defense/answer')
def answer_defense(snapshot_id: str, payload: AnswerDefense, request: Request, workspace: str = Header(...,alias='X-Workspace-Id'), token: str = Header(...,alias='X-Workspace-Token'), session_token: str = Header(...,alias='X-Session-Token')):
    db=auth(request,workspace,token)
    try:
        if any(not item.strip() or len(item)>400 for item in payload.unknowns): raise ValueError('invalid unknown disclosure')
        return service.defense_answer(db,workspace,snapshot_id,payload.studio_session_id,session_token,payload.expected_phase,payload.answer,[c.model_dump() for c in payload.citations],
                                     [link.model_dump() for link in payload.evidence_links],payload.changed_requirement,payload.learner_alternative,payload.unknowns,retry_key(request))
    except idempotency.IdempotencyConflict: raise HTTPException(409,'idempotency key conflict')
    except idempotency.RetryQuotaExceeded: raise HTTPException(429,'repository retry storage limit reached')
    except PermissionError: raise HTTPException(401,'invalid session capability')
    except LookupError: raise HTTPException(404,'defense not found')
    except ValueError: raise HTTPException(409,'invalid phase or citation')

class DecisionRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    topic: str = Field(min_length=1,max_length=200)
    evidence_card_ids: list[str] = Field(min_length=1,max_length=10)
    inferred_rationale: str = Field(min_length=1,max_length=2000)
    learner_alternative: str | None = Field(default=None,max_length=2000)

@router.post('/{snapshot_id}/decisions')
def decision_create(snapshot_id: str, payload: DecisionRequest, request: Request, workspace: str = Header(...,alias='X-Workspace-Id'), token: str = Header(...,alias='X-Workspace-Token')):
    db=auth(request,workspace,token)
    try: return service.save_decision(db,workspace,snapshot_id,payload.topic,payload.evidence_card_ids,payload.inferred_rationale,payload.learner_alternative,retry_key(request))
    except idempotency.IdempotencyConflict: raise HTTPException(409,'idempotency key conflict')
    except idempotency.RetryQuotaExceeded: raise HTTPException(429,'repository retry storage limit reached')
    except LookupError: raise HTTPException(404,'snapshot not found')
    except service.QuotaExceeded: raise HTTPException(429,'decision limit reached')
    except ValueError: raise HTTPException(422,'invalid evidence card')

@router.get('/{snapshot_id}/decisions')
def decisions(snapshot_id: str, request: Request, workspace: str = Header(...,alias='X-Workspace-Id'), token: str = Header(...,alias='X-Workspace-Token')):
    db=auth(request,workspace,token)
    try: return service.list_decisions(db,workspace,snapshot_id)
    except LookupError: raise HTTPException(404,'snapshot not found')
