"""The new Tanglish diagnostic is bounded and offline tests never call Gnani."""
import asyncio
import base64
import httpx
from backend.app.core.config import Settings
from backend.app.speech.gnani_adapter import GnaniSpeechAdapter
from scripts.tanglish_smoke import TANGLISH_TEXT, EXPECTED_PROGRAMMING_TOKENS, run_tanglish_smoke


def test_tanglish_diagnostic_has_two_calls_and_retains_private_wav(tmp_path):
    calls=[]
    pcm=base64.b64encode(b'\1\0'*1600).decode()
    stream=f'event: chunk\ndata: {{"chunk_index":1,"audio":"{pcm}"}}\n\nevent: complete\ndata: {{"chunk_index":2,"audio":"","is_final":true}}\n\n'
    def respond(request):
        calls.append(request)
        if request.url.path.endswith('/tts/sse'):
            import json
            payload=json.loads(request.content)
            assert payload['language']=='auto'
            assert any('஀' <= char <= '௿' for char in payload['text'])
            return httpx.Response(200,content=stream)
        assert b'codemix' in request.content and b'ta-IN,en-IN' in request.content
        return httpx.Response(200,json={'success':True,'transcript':'இந்த code nums sum target left index negative answer','model':'prisma-v3.0'})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            result=await run_tanglish_smoke(Settings(_env_file=None,gnani_api_key='test-only'),tmp_path,adapter_factory=lambda **kwargs:GnaniSpeechAdapter(**kwargs,http_client=client))
            assert result['status']=='PASS_SYNTHETIC_CODEMIX'
            assert result['provider_calls']==len(calls)==2
            assert result['tts_characters']<=300 and result['stt_seconds']<=15
            assert result['programming_tokens']['matched']==list(EXPECTED_PROGRAMMING_TOKENS)
            assert (tmp_path/'tanglish.wav').stat().st_mode & 0o777 == 0o600
            assert result['human_accuracy_claimed'] is False
    asyncio.run(run())


def test_auth_failure_stops_before_stt(tmp_path):
    calls=[]
    async def run():
        def respond(req):
            calls.append(req)
            return httpx.Response(401)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            result=await run_tanglish_smoke(Settings(_env_file=None,gnani_api_key='test-only'),tmp_path,adapter_factory=lambda **kwargs:GnaniSpeechAdapter(**kwargs,http_client=client))
            assert result['provider_calls']==len(calls)==1
            assert result['http_status']==401
            assert result['stt_seconds']==0
            assert result['retries']==0
    asyncio.run(run())


def test_tanglish_input_is_short_and_contains_actual_tamil_and_english():
    assert len(TANGLISH_TEXT)<=300
    assert any('஀' <= char <= '௿' for char in TANGLISH_TEXT)
    assert all(token in TANGLISH_TEXT for token in EXPECTED_PROGRAMMING_TOKENS)
