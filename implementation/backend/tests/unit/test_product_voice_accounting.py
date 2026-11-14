import asyncio
from types import SimpleNamespace

import pytest

from backend.app.models.api_schemas import STTRequest, TTSRequest
from backend.app.speech.audio_utils import generate_sine_wav_bytes
from backend.app.speech.gatekeeper import SpeechGatekeeper, SpeechQuotaExhaustedError
from backend.app.speech.gnani_adapter import GnaniTransportError
from backend.app.speech.pre_tts_normalizer import to_speakable


class Adapter:
    def __init__(self, reject=False):
        self.calls = 0
        self.reject = reject

    async def synthesize_tts(self, req, **kwargs):
        self.calls += 1
        if self.reject:
            raise GnaniTransportError('Rejected', status_code=429, retryable=True)
        return SimpleNamespace(total_chars_billed=sum(map(len, to_speakable(req.text))), cache_hit=False)

    async def transcribe_rest(self, req, wav):
        self.calls += 1
        if self.reject:
            raise GnaniTransportError('Rejected', status_code=429, retryable=True)
        return SimpleNamespace(audio_duration_sec=.1)


def test_product_voice_multisegment_admission_counts_physical_calls():
    async def scenario():
        adapter = Adapter()
        gate = SpeechGatekeeper(adapter, global_daily_call_limit=1)
        text = 'Hello world. ' * 200
        assert len(to_speakable(text)) > 1
        with pytest.raises(SpeechQuotaExhaustedError):
            await gate.execute_tts(TTSRequest(session_id='test', text=text))
        assert adapter.calls == 0
        gate._conn.close()
    asyncio.run(scenario())


def test_product_voice_multisegment_ledger_counts_physical_calls():
    async def scenario():
        adapter = Adapter()
        gate = SpeechGatekeeper(adapter)
        request = TTSRequest(session_id='test', text='Hello world. ' * 200)
        await gate.execute_tts(request)
        expected = len(to_speakable(request.text))
        assert gate._conn.execute('SELECT request_count FROM usage_ledger').fetchone()[0] == expected
        assert gate._conn.execute('SELECT request_count FROM usage_reservations').fetchone()[0] == expected
        gate._conn.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('operation', ['STT', 'TTS'])
def test_product_voice_retry_cannot_bypass_global_daily_limit(operation):
    async def scenario():
        adapter = Adapter(reject=True)
        gate = SpeechGatekeeper(adapter, global_daily_call_limit=1, retry_backoff_base_sec=0, max_429_retries=2)
        with pytest.raises(SpeechQuotaExhaustedError):
            if operation == 'TTS':
                await gate.execute_tts(TTSRequest(session_id='test', text='Hello'))
            else:
                await gate.execute_stt(STTRequest(session_id='test'), generate_sine_wav_bytes(duration_sec=.1))
        assert adapter.calls == 1
        assert gate.get_capacity_status().active_requests == 0
        assert gate._conn.execute("SELECT SUM(request_count) FROM usage_reservations WHERE status='COMMITTED'").fetchone()[0] == 1
        gate._conn.close()
    asyncio.run(scenario())
