"""Studio speech with shared bounded admission, durable quota and epoch fencing."""
import asyncio
import base64
import hashlib
import json
import threading
import uuid
from contextlib import closing, asynccontextmanager

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.app.core.config import validated_credential
from backend.app.db.migrations import open_connection
from backend.app.models.api_schemas import STTRequest, TTSRequest
from backend.app.models.enums import LanguageMode, SpeechLocale, TTSVoice
from backend.app.speech.capabilities import session_tts_selection
from backend.app.speech.audio_utils import inspect_and_validate_stt_wav
from backend.app.speech.gatekeeper import SpeechBusyError, accounted_speech_totals
from backend.app.speech.gnani_adapter import GnaniSpeechAdapter, GnaniTransportError, select_gnani_stt_format
from backend.app.speech.pre_tts_normalizer import to_speakable
from backend.app.studio.routes import auth, encode, iso

router=APIRouter(prefix='/studio/sessions',tags=['studio-speech'])
PROVIDER_DEADLINE_SECONDS=30.0
_TASKS={}
_TASKS_LOCK=threading.Lock()


def register_task(sid,epoch):
    task=asyncio.current_task(); loop=asyncio.get_running_loop()
    with _TASKS_LOCK: _TASKS.setdefault((sid,epoch),set()).add((loop,task))
    return loop,task


def unregister_task(sid,epoch,entry):
    with _TASKS_LOCK:
        group=_TASKS.get((sid,epoch),set()); group.discard(entry)
        if not group: _TASKS.pop((sid,epoch),None)


def cancel_tasks(sid,epoch=None,*,before_epoch=None):
    with _TASKS_LOCK:
        entries=[entry for (owner,generation),group in _TASKS.items() if owner==sid and (epoch is None or epoch==generation) and (before_epoch is None or generation<before_epoch) for entry in group]
    for loop,task in entries: loop.call_soon_threadsafe(task.cancel)


@asynccontextmanager
async def speech_slot(req):
    """Share legacy speech's bounded queue without duplicating its usage ledger."""
    gate=req.app.state.speech.gatekeeper
    await gate._acquire_single_slot()
    try:
        yield
    finally:
        gate._release_single_slot()


def event_text(db,session,epoch,sequence):
    if session['epoch']!=epoch:
        raise HTTPException(409,'Coach text superseded')
    row=db.execute("SELECT event_type,payload_json FROM studio_events WHERE session_id=? AND sequence=? AND event_type IN ('coach.action','feedback.ready')",(session['id'],sequence)).fetchone()
    if not row:
        raise HTTPException(404,'Validated coach text unavailable')
    payload=json.loads(row['payload_json'])
    if payload.get('epoch')!=epoch:
        raise HTTPException(409,'Coach text superseded')
    if not payload.get('validated'):
        raise HTTPException(422,'Coach event has not been validated')
    if row['event_type']=='coach.action':
        text=payload.get('text')
        if not isinstance(text,str) or not text.strip():
            raise HTTPException(422,'Coach text unavailable')
        return text
    from backend.app.studio.feedback import ModelFeedback, abstain, validate_candidate
    from backend.app.studio.turns import feedback_is_current
    if not feedback_is_current(db,session,payload):
        raise HTTPException(409,'Feedback evidence superseded')
    if session['posture']=='assessment' and session['state']!='completed':
        raise HTTPException(409,'Feedback withheld until debrief')
    try:
        candidate=ModelFeedback.model_validate({key:payload[key] for key in ('question','uncertainty','criteria')})
        active={r['id'] for r in db.execute('SELECT id FROM studio_turns WHERE session_id=? AND superseded_by IS NULL',(session['id'],))}
        repo=set()
        if session['repo_snapshot_id']:
            repo={r['id'] for r in db.execute("SELECT c.id FROM repo_chunks c JOIN repo_snapshots s ON s.id=c.snapshot_id WHERE s.id=? AND s.workspace_id=? AND s.status='READY'",(session['repo_snapshot_id'],session['workspace_id']))}
        validate_candidate(candidate,active|repo,len(active),repo)
        if payload.get('source')=='deterministic_fallback':
            fallback=abstain(payload.get('evidence_turn_ids',[]))
            if any(payload[key]!=fallback[key] for key in ('question','uncertainty','criteria')):
                raise ValueError('Unauthored fallback')
        elif payload.get('source')!='model_assisted':
            raise ValueError('Unknown feedback source')
    except (KeyError,ValueError,TypeError):
        raise HTTPException(422,'Feedback text failed validation')
    return candidate.question


class NeutralAdapter(GnaniSpeechAdapter):
    def build_rest_stt_form_fields(self,req):
        return {'model':'prisma-v3.0','language_code':req.language_mode.value,'format':select_gnani_stt_format(req.language_mode),'keyterms':'[]','topic':'Engineering architecture discussion'}, []


class STTBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    epoch:int=Field(ge=1)
    audio_base64:str=Field(min_length=1,max_length=2000000)
    language_mode:LanguageMode=LanguageMode.EN_IN


class TTSBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    epoch:int=Field(ge=1)
    event_sequence:int=Field(ge=1)
    language:SpeechLocale | None=None
    voice:TTSVoice | None=None


def reserve(req,sid,authorization,epoch,key,operation,digest,seconds,chars,calls):
    if not 8<=len(key)<=128: raise HTTPException(400,'X-Idempotency-Key required')
    settings=req.app.state.settings
    if not validated_credential(settings.gnani_api_key): raise HTTPException(503,'Cloud speech unavailable; use text')
    with closing(open_connection(settings.database_path)) as db:
        db.execute('BEGIN IMMEDIATE')
        s=auth(db,sid,authorization)
        if s['epoch']!=epoch: raise HTTPException(409,'Turn epoch conflict')
        old=db.execute('SELECT request_digest FROM studio_speech_usage WHERE session_id=? AND operation=? AND idempotency_key=?',(sid,operation,key)).fetchone()
        if old:
            raise HTTPException(409,'Speech request already dispatched or outcome uncertain' if old['request_digest']==digest else 'Idempotency key conflict')
        usage=db.execute("SELECT COALESCE(SUM(stt_seconds),0),COALESCE(SUM(tts_chars),0) FROM studio_speech_usage WHERE session_id=? AND status IN ('RESERVED','COMMITTED','UNCERTAIN')",(sid,)).fetchone()
        today=iso()
        count=db.execute("SELECT COALESCE(SUM(request_count),0) FROM studio_speech_usage WHERE status IN ('RESERVED','COMMITTED','UNCERTAIN') AND date(created_at)=date(?)",(today,)).fetchone()[0]
        count+=db.execute("SELECT COALESCE(SUM(request_count),0) FROM studio_speech_deleted_daily WHERE day=date(?)",(today,)).fetchone()[0]
        count+=db.execute("SELECT COALESCE(SUM(request_count),0) FROM usage_reservations WHERE status IN ('RESERVED','COMMITTED') AND date(created_at)=date(?)",(today,)).fetchone()[0]
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='module_speech_usage'").fetchone():
            count+=db.execute("SELECT COALESCE(SUM(request_count),0) FROM module_speech_usage WHERE status IN ('RESERVED','COMMITTED','UNCERTAIN') AND date(created_at)=date(?)",(today,)).fetchone()[0]
        total_seconds,total_chars=accounted_speech_totals(db)
        gate=req.app.state.speech.gatekeeper
        if (usage[0]+seconds>settings.max_stt_seconds_per_session or usage[1]+chars>settings.max_tts_chars_per_session
            or total_seconds+seconds>gate.max_stt_seconds_budget or total_chars+chars>gate.max_tts_chars_budget
            or count+calls>settings.global_daily_call_limit):
            raise HTTPException(429,'Speech quota exhausted; use text')
        rid=str(uuid.uuid4())
        db.execute('INSERT INTO studio_speech_usage VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(rid,sid,epoch,operation,key,digest,seconds,chars,calls,'RESERVED',today,today))
        db.commit()
        return rid


def settle(req,rid,status):
    if rid is None:
        return
    with closing(open_connection(req.app.state.settings.database_path)) as db:
        if status=='UNDISPATCHED':
            # No provider work occurred: remove admission, permitting a safe retry.
            db.execute("DELETE FROM studio_speech_usage WHERE id=? AND status='RESERVED'",(rid,))
        else:
            db.execute("UPDATE studio_speech_usage SET status=?,updated_at=? WHERE id=? AND status='RESERVED'",(status,iso(),rid))


def current(req,sid,authorization,epoch):
    with closing(open_connection(req.app.state.settings.database_path)) as db:
        row=auth(db,sid,authorization)
        if row['epoch']!=epoch: raise HTTPException(409,'Speech result superseded')


def adapter(req):
    settings=req.app.state.settings
    return NeutralAdapter(api_key=settings.gnani_api_key.get_secret_value() if settings.gnani_api_key else '',stt_endpoint=settings.gnani_base_url.rstrip('/')+'/stt/v3',tts_endpoint=settings.gnani_base_url.rstrip('/')+'/api/v1/tts/sse')


async def run_provider(req,sid,authorization,epoch,key,operation,digest,seconds,chars,calls,dispatch,check_current):
    check_current()
    entry=register_task(sid,epoch)
    rid=None
    status='UNDISPATCHED'
    try:
        async with speech_slot(req):
            check_current()
            rid=reserve(req,sid,authorization,epoch,key,operation,digest,seconds,chars,calls)
            check_current()
            status='UNCERTAIN'
            # wait_for cancels and awaits adapter cleanup before the lease releases.
            from backend.app.speech.routes import _await_connected_voice
            result=await asyncio.wait_for(_await_connected_voice(req,dispatch()),timeout=PROVIDER_DEADLINE_SECONDS)
            status='COMMITTED'
            check_current()
        return result
    except SpeechBusyError:
        raise HTTPException(429,'Speech is busy; use text or retry later')
    except asyncio.CancelledError:
        raise HTTPException(409,'Speech request superseded')
    except HTTPException:
        raise
    except (TimeoutError,GnaniTransportError):
        raise HTTPException(502,'Cloud speech unavailable; use text')
    except Exception:
        raise HTTPException(502,'Speech unavailable; use text')
    finally:
        try:
            settle(req,rid,status)
        finally:
            unregister_task(sid,epoch,entry)


@router.post('/{sid}/speech/stt')
async def stt(req:Request,sid:str,data:STTBody,authorization:str=Header(default=''),x_idempotency_key:str=Header(default='')):
    try:
        audio=base64.b64decode(data.audio_base64,validate=True)
        info=inspect_and_validate_stt_wav(audio)
    except (ValueError,TypeError):
        raise HTTPException(422,'Invalid WAV audio')
    digest=hashlib.sha256(encode(data.model_dump(mode='json')).encode()).hexdigest()
    request=STTRequest(session_id=sid,turn_generation=data.epoch,language_mode=data.language_mode,source_code='',topic_override='Engineering architecture discussion')
    result=await run_provider(req,sid,authorization,data.epoch,x_idempotency_key,'STT',digest,info.duration_sec,0,1,
                              lambda:adapter(req).transcribe_rest(request,audio),
                              lambda:current(req,sid,authorization,data.epoch))
    return {'raw_transcript':result.raw_transcript,'normalized_transcript':result.normalized_transcript,'requires_confirmation':True,'epoch':data.epoch}


@router.post('/{sid}/speech/tts')
async def tts(req:Request,sid:str,data:TTSBody,authorization:str=Header(default=''),x_idempotency_key:str=Header(default='')):
    with closing(open_connection(req.app.state.settings.database_path)) as db:
        session=auth(db,sid,authorization)
        text=event_text(db,session,data.epoch,data.event_sequence)
        selection=session_tts_selection(session,model=req.app.state.settings.gnani_tts_model,
                                         default_voice=req.app.state.settings.gnani_tts_voice,
                                         language=data.language,voice=data.voice)
    def check_current():
        with closing(open_connection(req.app.state.settings.database_path)) as db:
            session=auth(db,sid,authorization)
            if event_text(db,session,data.epoch,data.event_sequence)!=text:
                raise HTTPException(409,'Coach text superseded')
    chunks=to_speakable(text)
    chars=sum(len(c) for c in chunks)
    digest=hashlib.sha256(encode(data.model_dump()).encode()).hexdigest()
    request=TTSRequest(session_id=sid,turn_generation=data.epoch,text=text,**selection)
    result=await run_provider(req,sid,authorization,data.epoch,x_idempotency_key,'TTS',digest,0,chars,len(chunks),
                              lambda:adapter(req).synthesize_tts(request),check_current)
    return {'audio_base64':base64.b64encode(result.wav_bytes).decode(),'content_type':'audio/wav','epoch':data.epoch}
