"""Shared cache acceptance with synthetic audio and real capability middleware."""
from contextlib import closing
from uuid import uuid4
from fastapi.testclient import TestClient
from backend.app.db.migrations import open_connection
from backend.app.db.repository import repository_for
from backend.app.main import create_app
from backend.app.orchestration.state_machine import CoordinatorStateMachine
from backend.app.models.api_schemas import TTSRequest
from backend.app.speech.audio_utils import generate_sine_wav_bytes
from backend.app.speech.postgres_cache import PostgresTTSCache
from backend.app.speech.pre_tts_normalizer import to_speakable
from backend.tests.integration.test_postgres_runtime import runtime as runtime  # noqa: F401


def session(client):
    result = client.post('/api/v1/sessions', json={'exercise_id':'ex1_shortest_subarray','spec_version':'v1_positive_only'})
    assert result.status_code in (200,201), result.text
    return result.json()


def test_legacy_audio_authenticated_replay_from_second_application(runtime, monkeypatch):
    client,target = runtime
    created,foreign = session(client),session(client)
    sid = created['session_id']
    turn,_ = repository_for(target).create_or_reuse_turn(session_id=sid,
        code_version_id=created['revision']['code_version_id'], challenge_id=None,
        transport_mode='TEXT', state='AWAITING_CLAIM_CONFIRMATION',
        raw_transcript='I shrink the window.', normalized_transcript='I shrink the window.')
    payload = {'revision':CoordinatorStateMachine(repository_for(target)).build_revision_ref(sid).model_dump(mode='json'),'turn_id':turn.id}
    headers = {'Authorization':'Bearer '+created['session_token']}
    reply = client.post(f'/api/v1/sessions/{sid}/conversation/text',json=payload,
        headers={**headers,'X-Idempotency-Key':str(uuid4())})
    assert reply.status_code == 200, reply.text
    req = TTSRequest(session_id=sid,text=reply.json()['text'],**client.app.state.speech._tts_selection(sid))
    key = PostgresTTSCache.compute_cache_key(normalized_text='\n'.join(to_speakable(req.text)),
        model=req.model,voice=req.voice,language=req.language,speed=req.speed,audio_config=req.audio_config)
    wav = generate_sine_wav_bytes(duration_sec=.1, sample_rate_hz=22050)
    with closing(open_connection(target)) as db:
        db.execute('CREATE TABLE legacy_cloud_audio (LIKE cloud_audio INCLUDING ALL)')
        db.execute('INSERT INTO legacy_cloud_audio VALUES(?,?,?,?,?)',('SESSION_SCOPED',sid,key,wav,1.0))
    app = create_app(client.app.state.settings)
    with TestClient(app) as other:
        async def forbidden(*args,**kwargs):
            raise AssertionError('No provider request allowed')
        monkeypatch.setattr(app.state.speech.adapter,'synthesize_tts',forbidden)
        path = f'/api/v1/sessions/{sid}/speech/conversation'
        denied = other.post(path,json=payload,headers={'Authorization':'Bearer '+foreign['session_token'],'X-Idempotency-Key':str(uuid4())})
        assert denied.status_code in (401,403)
        response = other.post(path,json=payload,headers={**headers,'X-Idempotency-Key':str(uuid4())})
        assert response.status_code == 200,response.text
        assert response.content == wav
        assert app.state.speech.cache.get_wav(key,session_id=foreign['session_id']) is None
        assert app.state.speech.cache.evict_session(sid) == 1
        assert app.state.speech.cache.get_wav(key,session_id=sid) is None


def test_shared_new_cache_bounds_expiry_and_scope(runtime):
    client,target = runtime
    sid = session(client)['session_id']
    wav = generate_sine_wav_bytes(duration_sec=.1, sample_rate_hz=22050)
    first = PostgresTTSCache(target,max_bytes=len(wav)*2,max_entries=1)
    second = PostgresTTSCache(target,max_bytes=len(wav)*2,max_entries=1)
    first.put_completed_stream('private',wav,stream_completed=True,session_id=sid)
    assert second.get_wav('private',session_id=sid) == wav
    assert second.get_wav('private',scope='PUBLIC_GENERIC') is None
    first.put_completed_stream('public',wav,stream_completed=True,scope='PUBLIC_GENERIC')
    assert second.get_wav('private',session_id=sid) is None
    assert second.get_wav('public',scope='PUBLIC_GENERIC') == wav
    with closing(open_connection(target)) as db:
        db.execute('UPDATE cloud_audio SET created_at=0')
    assert second.enforce_limits() == 1
    assert second.get_wav('public',scope='PUBLIC_GENERIC') is None


def test_retained_audio_consumes_budget_without_eviction(runtime):
    client,target = runtime
    sid = session(client)['session_id']
    wav = generate_sine_wav_bytes(duration_sec=.1, sample_rate_hz=22050)
    cache = PostgresTTSCache(target,max_bytes=len(wav),max_entries=1)
    with closing(open_connection(target)) as db:
        db.execute('CREATE TABLE legacy_cloud_audio (LIKE cloud_audio INCLUDING ALL)')
        db.execute('INSERT INTO legacy_cloud_audio VALUES(?,?,?,?,?)',('SESSION_SCOPED',sid,'old',wav,1.0))
    assert cache.put_completed_stream('new',wav,stream_completed=True,session_id=sid) == wav
    assert cache.get_wav('new',session_id=sid) is None
    assert cache.get_wav('old',session_id=sid) == wav
    with closing(open_connection(target)) as db:
        db.execute('UPDATE sessions SET deleted_at=? WHERE id=?',('2026-11-15T00:00:00+00:00',sid))
    assert cache.get_wav('old',session_id=sid) is None
