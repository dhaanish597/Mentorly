"""A local replay does not consume provider call/character allowance."""
import asyncio
import base64
import httpx
from backend.app.models.api_schemas import TTSRequest
from backend.app.speech.gatekeeper import SpeechGatekeeper
from backend.app.speech.gnani_adapter import GnaniSpeechAdapter
from backend.app.speech.tts_cache import TTSDiskCache


def test_cached_replay_succeeds_after_provider_call_budget_is_exhausted(tmp_path):
    dispatched=[]
    pcm=base64.b64encode(b'\x01\x00'*1600).decode()
    body=f'event: chunk\ndata: {{"chunk_index":1,"audio":"{pcm}"}}\n\nevent: complete\ndata: {{"chunk_index":2,"audio":"","is_final":true}}\n\n'
    def respond(req):
        dispatched.append(req)
        return httpx.Response(200,content=body)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            adapter=GnaniSpeechAdapter(api_key='test-only',tts_cache=TTSDiskCache(tmp_path/'tts'),http_client=client)
            gate=SpeechGatekeeper(adapter,db_path=tmp_path/'db',max_429_retries=0,global_daily_call_limit=1,max_tts_chars_budget=6)
            req=TTSRequest(session_id='cache',text='Hello.')
            first=await gate.execute_tts(req)
            second=await gate.execute_tts(req)
            assert second.cache_hit and second.wav_bytes==first.wav_bytes
            assert len(dispatched)==1
            assert gate.get_capacity_status().tts_chars_used==6
            count=gate._conn.execute("SELECT SUM(request_count) FROM usage_reservations WHERE status='COMMITTED'").fetchone()[0]
            assert count==1
            gate._conn.close()
    asyncio.run(run())
