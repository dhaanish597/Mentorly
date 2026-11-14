import asyncio
import json
from contextlib import asynccontextmanager

import pytest

from backend.app.models.api_schemas import STTRequest
from backend.app.speech.audio_utils import generate_sine_wav_bytes
from backend.app.speech.gatekeeper import SpeechGatekeeper
from backend.app.speech.gnani_adapter import GnaniSpeechAdapter, GnaniTransportError
from backend.app.speech.ws_streamer import GnaniWebSocketSTTRelay


def relay_with_events(events):
    sent=[]
    class Connection:
        def __init__(self):
            self.events=iter(events)
        async def send(self,value):
            sent.append(value)
        async def recv(self):
            if not hasattr(self,'queue'):
                self.queue=asyncio.Queue()
                async def populate():
                    for delay,event in events:
                        await asyncio.sleep(delay)
                        await self.queue.put(json.dumps(event))
                self.populate=asyncio.create_task(populate())
            return await self.queue.get()
    @asynccontextmanager
    async def connect(*args,**kwargs):
        connection=Connection()
        try:
            yield connection
        finally:
            if hasattr(connection,'populate'):
                connection.populate.cancel()
                await asyncio.gather(connection.populate,return_exceptions=True)
    gate=SpeechGatekeeper(GnaniSpeechAdapter(api_key='test-only'),max_429_retries=0)
    return GnaniWebSocketSTTRelay(gate,connect_fn=connect,pace_frames=False),sent


@pytest.mark.parametrize('live',[True,False])
def test_product_voice_wire_never_pads_past_thirty_seconds(live):
    async def scenario():
        relay,sent=relay_with_events([(0,{'type':'connected'}),(0,{'type':'transcript','text':'done','is_final':True,'utterance_id':'one'})])
        req=STTRequest(session_id='test')
        try:
            if live:
                async def incoming():
                    for _ in range(15):
                        yield b'\0'*64000
                result=await relay._live_wire(req,incoming())
            else:
                result=await relay._transcribe(req,generate_sine_wav_bytes(duration_sec=30))
            frames=[value for value in sent if isinstance(value,bytes)]
            assert sum(map(len,frames))==960000
            assert len(frames[-1])==512
            assert result.audio_duration_sec==30
        finally:
            relay.gatekeeper._conn.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('live',[True,False])
def test_product_voice_delayed_speech_start_holds_pending_utterance(live):
    async def scenario():
        relay,_=relay_with_events([(0,{'type':'connected'}),(0,{'type':'transcript','text':'first','is_final':True,'utterance_id':'one'}),(.35,{'type':'speech_start','utterance_id':'two'}),(1.15,{'type':'transcript','text':'second','is_final':True,'utterance_id':'two'})])
        req=STTRequest(session_id='test')
        try:
            if live:
                async def incoming():
                    yield b'\0'*1024
                result=await relay._live_wire(req,incoming())
            else:
                result=await relay._transcribe(req,generate_sine_wav_bytes(duration_sec=.1))
            assert result.raw_transcript=='first second'
        finally:
            relay.gatekeeper._conn.close()
    asyncio.run(scenario())


def test_product_voice_ws_requires_explicit_final_boolean():
    async def scenario():
        relay,_=relay_with_events([(0,{'type':'connected'}),(0,{'type':'transcript','text':'not declared final'})])
        try:
            with pytest.raises(GnaniTransportError):
                await relay._transcribe(STTRequest(session_id='test'),generate_sine_wav_bytes(duration_sec=.1))
        finally:
            relay.gatekeeper._conn.close()
    asyncio.run(scenario())
