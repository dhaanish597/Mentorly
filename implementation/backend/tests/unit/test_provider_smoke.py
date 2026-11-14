"""Smoke safety is exercised entirely against a MockTransport, never a provider."""
import asyncio
import base64
import httpx
from backend.app.core.config import Settings
from backend.app.speech.gnani_adapter import GnaniSpeechAdapter
from scripts.provider_smoke import run_smoke


def test_smoke_stops_on_first_auth_failure_without_stt_or_retry():
    dispatched=[]
    def respond(req):
        dispatched.append(req)
        return httpx.Response(401)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            summary=await run_smoke(Settings(_env_file=None,gnani_api_key='test-only'),adapter_factory=lambda **kwargs:GnaniSpeechAdapter(**kwargs,http_client=client))
            assert summary['status']=='BLOCKED_EXTERNAL'
            assert summary['http_status']==401
            assert summary['provider_calls_attempted']==1
            assert summary['retries']==0
            assert summary['stt_seconds_attempted']==0
            assert len(dispatched)==1
    asyncio.run(run())


def test_smoke_success_uses_three_calls_and_cache_replay_is_free():
    dispatched=[]
    pcm=base64.b64encode(b'\1\0'*1600).decode()
    body=f'event: chunk\ndata: {{"chunk_index":1,"audio":"{pcm}"}}\n\nevent: complete\ndata: {{"chunk_index":2,"audio":"","is_final":true}}\n\n'
    def respond(req):
        dispatched.append(req)
        if req.url.path.endswith('/tts/sse'):
            return httpx.Response(200,content=body)
        return httpx.Response(200,json={'success':True,'transcript':'The program returns three.','model':'prisma-v3.0'})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            summary=await run_smoke(Settings(_env_file=None,gnani_api_key='test-only'),adapter_factory=lambda **kwargs:GnaniSpeechAdapter(**kwargs,http_client=client))
            assert summary['status']=='PASS'
            assert summary['cache_replay']['cache_hit']
            assert summary['provider_calls_attempted']==len(dispatched)==3
            assert summary['stt_seconds_attempted']<=60
            assert summary['tts_characters_attempted']<=1500
            assert summary['ledger']['tts_requests_count']==1
            assert 'transcript' not in summary['stt_en_rest']
    asyncio.run(run())


def test_smoke_placeholder_never_builds_adapter():
    async def run():
        def forbidden(**kwargs):
            raise AssertionError('No provider client expected')
        summary=await run_smoke(Settings(_env_file=None,gnani_api_key='<API_KEY>'),adapter_factory=forbidden)
        assert summary['provider_calls_attempted']==0
    asyncio.run(run())
