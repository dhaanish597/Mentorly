"""Authenticated shared fixed-voice cache economy; all provider work is mocked."""
import asyncio
import base64
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.models.domain import RevisionRef


@pytest.mark.parametrize('kind', ['test-voice', 'introduction'])
def test_public_fixed_voice_shares_one_provider_charge_between_sessions(tmp_path, kind):
    calls=[]
    audio=base64.b64encode(b'\1\0'*1600).decode()
    stream=f'event: chunk\ndata: {{"chunk_index":1,"audio":"{audio}"}}\n\nevent: complete\ndata: {{"chunk_index":2,"audio":"","is_final":true}}\n\n'
    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, content=stream)
    provider=httpx.AsyncClient(transport=httpx.MockTransport(respond))
    settings=Settings(_env_file=None, gnani_api_key='test-only', database_path=tmp_path/'app.db', tts_cache_dir=tmp_path/'cache')
    app=create_app(settings)
    try:
        with TestClient(app) as client:
            app.state.speech.adapter._http_client=provider
            first=client.post('/api/v1/sessions',json={'exercise_id':'ex1_shortest_subarray','spec_version':'v1_positive_only'}).json()
            second=client.post('/api/v1/sessions',json={'exercise_id':'ex1_shortest_subarray','spec_version':'v1_positive_only'}).json()
            def post(session, payload=None):
                return client.post('/api/v1/sessions/'+session['session_id']+'/speech/'+kind,
                    json=payload or {'revision':session['revision']},headers={'Authorization':'Bearer '+session['session_token'],'X-Idempotency-Key':str(uuid4())})
            assert post(first).status_code==200
            before=app.state.speech.gatekeeper.get_capacity_status()
            replay=post(second)
            assert replay.status_code==200
            after=app.state.speech.gatekeeper.get_capacity_status()
            assert len(calls)==1
            assert before.tts_chars_used==after.tts_chars_used>0
            assert after.tts_requests_count==1
            assert list(app.state.speech.cache.public_dir.glob('*.wav'))
            unauthorized=client.post('/api/v1/sessions/'+second['session_id']+'/speech/'+kind,
                json={'revision':second['revision']},headers={'X-Idempotency-Key':str(uuid4())})
            assert unauthorized.status_code==401
            wrong={**second['revision'],'code_hash':'0'*64}
            assert post(second,{'revision':wrong}).status_code==409
            assert post(second,{'revision':second['revision'],'text':'Learner private answer'}).status_code==422
            assert len(calls)==1
            # Identical personalized messages remain distinct session-scoped cache entries.
            for session in (first,second):
                client.portal.call(app.state.speech.synthesize,session['session_id'],'My private learner-specific reasoning.',RevisionRef.model_validate(session['revision']))
            assert len(calls)==3
            assert len(list(app.state.speech.cache.sessions_dir.rglob('*.wav')))==2
            deleted=client.delete('/api/v1/sessions/'+first['session_id'],headers={'Authorization':'Bearer '+first['session_token'],'X-Idempotency-Key':str(uuid4())})
            assert deleted.status_code==200
            assert len(list(app.state.speech.cache.sessions_dir.rglob('*.wav')))==1
            assert list(app.state.speech.cache.public_dir.glob('*.wav'))
            assert post(first).status_code==410
            assert post(second).status_code==200
            assert len(calls)==3
            # Durable HTTP replay must not bypass freshness after a code change.
            voice_path='/api/v1/sessions/'+second['session_id']+'/speech/'+kind
            replay_key=str(uuid4())
            replay_headers={'Authorization':'Bearer '+second['session_token'],'X-Idempotency-Key':replay_key}
            replay_body={'revision':second['revision']}
            cached=client.post(voice_path,json=replay_body,headers=replay_headers)
            assert cached.status_code==200
            assert client.post(voice_path,json=replay_body,headers=replay_headers).content==cached.content
            changed=client.put('/api/v1/sessions/'+second['session_id']+'/code',json={
                'code':second['starter_code']+'\n# a new revision',
                'expected_code_version_id':1,'client_edit_sequence':1,
            },headers={**replay_headers,'X-Idempotency-Key':str(uuid4())})
            assert changed.status_code==200
            stale=client.post(voice_path,json=replay_body,headers=replay_headers)
            assert stale.status_code==409 and stale.json()['code']=='REVISION_CONFLICT'
            assert len(calls)==3
            assert all('private' not in payload['text'] for payload in calls[:1])
    finally:
        asyncio.run(provider.aclose())
