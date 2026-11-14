"""Authoritative service revision callback runs after queue admission, before charge."""
import asyncio
import pytest
from backend.app.models.api_schemas import STTRequest, TTSRequest
from backend.app.speech.audio_utils import generate_sine_wav_bytes
from backend.app.speech.gatekeeper import SpeechBusyError, SpeechGatekeeper


@pytest.mark.parametrize('operation', ['STT','TTS'])
def test_queued_source_change_never_dispatches_or_records_uncertain_usage(operation):
    entered=[]
    class Adapter:
        async def transcribe_rest(self, req, wav):
            entered.append(True)
            raise AssertionError('stale provider dispatch')
        async def synthesize_tts(self, req, **kwargs):
            entered.append(True)
            raise AssertionError('stale provider dispatch')
    async def run():
        gate=SpeechGatekeeper(Adapter())
        await gate._acquire_single_slot()
        current={'value':True}
        def guard():
            if not current['value']:
                raise SpeechBusyError('Authoritative source revision changed.')
        if operation=='STT':
            task=asyncio.create_task(gate.execute_stt(STTRequest(session_id='queued'),generate_sine_wav_bytes(duration_sec=.1),assert_current=guard))
        else:
            task=asyncio.create_task(gate.execute_tts(TTSRequest(session_id='queued',text='Hello.'),assert_current=guard))
        await asyncio.sleep(0)
        current['value']=False
        gate._release_single_slot()
        with pytest.raises(SpeechBusyError):
            await task
        assert entered==[]
        assert gate.get_capacity_status().uncertain_requests_count==0
        assert gate._conn.execute("SELECT status FROM usage_reservations").fetchone()[0]=='RELEASED'
        gate._conn.close()
    asyncio.run(run())
