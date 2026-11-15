import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.core.config import Settings
from backend.app.db.repository import SQLiteRepository
from backend.app.main import create_app
from backend.app.orchestration.state_machine import CoordinatorStateMachine
from backend.app.speech.service import SpeechService
from backend.app.studio.speech import NeutralAdapter, STTBody, TTSBody


@pytest.mark.parametrize('mode', ['hi-IN,en-IN','bn-IN,en-IN'])
def test_product_voice_studio_codemix_uses_shared_format(mode):
    from backend.app.models.api_schemas import STTRequest
    form, _ = NeutralAdapter(api_key='test-only').build_rest_stt_form_fields(STTRequest(session_id='test',language_mode=mode))
    assert form['format'] == 'codemix'


def test_product_voice_studio_accepts_only_declared_optional_selection():
    assert TTSBody(epoch=1,event_sequence=1,language='bn-IN',voice='Shivani').voice == 'Shivani'
    with pytest.raises(ValidationError):
        TTSBody(epoch=1,event_sequence=1,voice='Nalini')


@pytest.mark.parametrize('method', ['synthesize','stream_synthesize','synthesize_fixed'])
@pytest.mark.parametrize('mode,expected', [('hi-IN','hi-IN'),('ta-IN,en-IN','auto'),('bn-IN','bn-IN')])
def test_product_voice_all_legacy_tts_paths_follow_session_language(tmp_path, method, mode, expected):
    settings = Settings(_env_file=None, gnani_api_key=None, database_path=tmp_path/'db',tts_cache_dir=tmp_path/'cache')
    repo = SQLiteRepository(settings.database_path); repo.initialize()
    sid = str(uuid4()); source = 'def first_at_least(nums, target):\n    return -1\n'
    repo.create_session(session_id=sid,token_hash=hashlib.sha256(sid.encode()).hexdigest(),exercise_id='ex2_binary_search',spec_version='v1_sorted_with_duplicates',language_mode=mode,interaction_mode='TEXT',starter_code=source,starter_code_hash=hashlib.sha256(source.encode()).hexdigest(),expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
    service = SpeechService(db_path=settings.database_path,cache_dir=settings.tts_cache_dir,settings=settings)
    revision = CoordinatorStateMachine(repo).build_revision_ref(sid)
    seen = []
    async def execute(request, **kwargs):
        seen.append(request)
        return SimpleNamespace(cache_hit=False,events=[])
    service.gatekeeper.execute_tts = execute
    async def scenario():
        if method == 'stream_synthesize':
            assert [event async for event in service.stream_synthesize(sid,'Hello',revision)] == []
        elif method == 'synthesize_fixed':
            await service.synthesize_fixed(sid,revision,purpose='TEST_VOICE')
        else:
            await service.synthesize(sid,'Hello',revision)
    try:
        asyncio.run(scenario())
        assert seen[0].language == expected
    finally:
        service.close()


def test_product_voice_studio_disconnect_cancels_provider_and_keeps_uncertain_usage(monkeypatch):
    from contextlib import asynccontextmanager
    from fastapi import HTTPException
    from backend.app.studio import speech
    statuses=[]
    cancelled=[]
    provider_markers=[]
    @asynccontextmanager
    async def slot(req):
        try:
            yield
        finally:
            assert cancelled==[True], 'Provider cancellation must finish before slot release'
    monkeypatch.setattr(speech,'speech_slot',slot)
    monkeypatch.setattr(speech,'reserve',lambda *args:'reserved')
    monkeypatch.setattr(speech,'settle',lambda req,rid,status:statuses.append(status))
    async def disconnected():
        return True
    gate=SimpleNamespace(
        mark_provider_dispatch=lambda:provider_markers.append('DISPATCHED'),
        mark_provider_complete=lambda:provider_markers.append('COMPLETE'),
    )
    request=SimpleNamespace(
        is_disconnected=disconnected,
        app=SimpleNamespace(state=SimpleNamespace(speech=SimpleNamespace(gatekeeper=gate))),
    )
    async def dispatch():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise
    async def scenario():
        started=asyncio.get_running_loop().time()
        with pytest.raises(HTTPException) as failure:
            await asyncio.wait_for(speech.run_provider(request,'session','token',1,'idem-key','TTS','digest',0,5,1,dispatch,lambda:None),timeout=1)
        assert failure.value.status_code==409
        assert asyncio.get_running_loop().time()-started < .5
    asyncio.run(scenario())
    assert cancelled==[True]
    assert provider_markers==['DISPATCHED']
    assert statuses==['UNCERTAIN']


def test_product_voice_text_conversation_needs_no_provider_and_is_authenticated(tmp_path, monkeypatch):
    settings=Settings(_env_file=None,gnani_api_key=None,database_path=tmp_path/'db',tts_cache_dir=tmp_path/'cache')
    app=create_app(settings)
    with TestClient(app) as client:
        created=client.post('/api/v1/sessions',json={'exercise_id':'ex1_shortest_subarray','spec_version':'v1_positive_only'}).json()
        sid=created['session_id']; repo=SQLiteRepository(settings.database_path)
        turn,_=repo.create_or_reuse_turn(session_id=sid,code_version_id=created['revision']['code_version_id'],challenge_id=None,transport_mode='TEXT',state='AWAITING_CLAIM_CONFIRMATION',raw_transcript='Why shrink the window?',normalized_transcript='Why shrink the window?',claim_json=None)
        payload={'turn_id':turn.id,'revision':CoordinatorStateMachine(repo).build_revision_ref(sid).model_dump(mode='json')}
        def forbidden(*args,**kwargs):
            pytest.fail('Text conversation must not call speech provider')
        monkeypatch.setattr(app.state.speech,'synthesize',forbidden)
        path=f'/api/v1/sessions/{sid}/conversation/text'
        headers={'Authorization':'Bearer '+created['session_token'],'X-Idempotency-Key':str(uuid4())}
        assert client.post(path,json=payload).status_code==401
        response=client.post(path,json=payload,headers=headers)
        assert response.status_code==200,response.text
        assert response.json()['source']=='authored_public_contract'
        assert '?' in response.json()['text']
        assert response.json()['turn_id']==turn.id
        assert repo.get_turn(sid,turn.id)==turn
