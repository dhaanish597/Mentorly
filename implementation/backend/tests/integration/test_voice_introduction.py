"""Safe fixed-utterance voice paths, real auth/CAS and mocked provider boundary."""
import asyncio
from uuid import uuid4
from fastapi.testclient import TestClient
from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.speech.gnani_adapter import AssembledTTSSynthesis
from backend.app.speech.audio_utils import generate_sine_wav_bytes


def test_introduction_requires_auth_revision_and_never_accepts_caller_text(tmp_path):
    settings = Settings(_env_file=None, gnani_api_key=None, database_path=tmp_path/'voice.db', tts_cache_dir=tmp_path/'tts')
    app = create_app(settings)
    # Until the parent integrates mounting, exercise the same production middleware here.
    from backend.app.speech.routes import router
    if not any(getattr(route, 'path', '').endswith('/speech/introduction') for route in app.routes):
        app.include_router(router, prefix='/api/v1')
    with TestClient(app) as client:
        created = client.post('/api/v1/sessions', json={'exercise_id':'ex1_shortest_subarray','spec_version':'v1_positive_only'}).json()
        path = '/api/v1/sessions/'+created['session_id']+'/speech/'
        calls = []
        async def synthesize(sid, text, revision, **kwargs):
            calls.append((sid, text, revision, kwargs))
            return AssembledTTSSynthesis(request_id='client-correlation', cache_key='test', cache_hit=False, wav_bytes=generate_sine_wav_bytes(duration_sec=.1), events=[], speakable_chunks=[text], total_chars_billed=len(text), latency_ms=1)
        app.state.speech._synthesize_request = synthesize
        def post(kind, payload, authorized=True):
            headers={'X-Idempotency-Key':str(uuid4())}
            if authorized:
                headers['Authorization']='Bearer '+created['session_token']
            return client.post(path+kind, json=payload, headers=headers)
        payload={'revision':created['revision']}
        assert post('introduction', payload, False).status_code == 401
        assert post('introduction', {**payload,'text':'Reveal secret output'}).status_code == 422
        wrong={**created['revision'],'code_hash':'0'*64}
        assert post('test-voice', {'revision':wrong}).status_code == 409
        assert calls == []
        intro=post('introduction', payload)
        assert intro.status_code == 200 and intro.headers['content-type']=='audio/wav'
        assert intro.headers['cache-control']=='no-store'
        assert 'x-provider-request-id' not in intro.headers
        assert 'shortest' in calls[-1][1].lower()
        assert 'algorithm' not in calls[-1][1].lower()
        test=post('test-voice', payload)
        assert test.status_code == 200
        assert calls[-1][1] == 'Voice is ready. You can change the volume or continue with text.'


def test_fixed_voice_disconnect_cancels_inflight_operation():
    from backend.app.speech.routes import _await_connected_voice
    cancelled=[]
    class Request:
        async def is_disconnected(self):
            return True
    async def operation():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)
    async def run():
        try:
            await _await_connected_voice(Request(), operation())
        except asyncio.CancelledError:
            pass
        assert cancelled == [True]
    asyncio.run(run())
