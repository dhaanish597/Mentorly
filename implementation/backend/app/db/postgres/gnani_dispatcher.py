"""Opt-in Gnani facade using the experimental PostgreSQL coordination ledger.

Each call uses a fresh idle connection from ``connect``; the factory and HTTP
transport are trusted local infrastructure. No recovery or retry is attempted.
A STARTED lease remains occupied and fully charged on any indeterminate outcome,
including cancellation, process death, or a failed final database commit.
"""
from collections.abc import Callable

from backend.app.speech.audio_utils import inspect_and_validate_stt_wav
from backend.app.speech.gnani_adapter import GnaniSpeechAdapter
from backend.app.speech.pre_tts_normalizer import to_speakable
from .speech_coordination import reserve, start, complete


class GnaniDispatcher:
    def __init__(self, *, connect: Callable, adapter: GnaniSpeechAdapter, lease_seconds: int = 300):
        if type(adapter) is not GnaniSpeechAdapter:
            raise TypeError("Expected the concrete Gnani adapter")
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise ValueError("Invalid lease duration")
        self._connect = connect
        self._adapter = adapter
        self._lease_seconds = lease_seconds

    async def transcribe_rest(self, req, wav_bytes: bytes):
        if type(wav_bytes) is not bytes:
            raise TypeError("Audio must be immutable bytes")
        req = req.model_copy(deep=True)
        audio = inspect_and_validate_stt_wav(wav_bytes)
        stt_ms = (audio.num_frames * 1000 + audio.sample_rate_hz - 1) // audio.sample_rate_hz
        with self._connect() as conn:
            lease = reserve(conn, stt_ms=stt_ms, tts_chars=0, calls=1, lease_seconds=self._lease_seconds)
            start(conn, lease)
            result = await self._adapter.transcribe_rest(req, wav_bytes)
            complete(conn, lease)
            return result

    async def synthesize_tts(self, req):
        req = req.model_copy(deep=True)
        chunks = to_speakable(req.text)
        if len(chunks) != 1 or not chunks[0].strip():
            raise ValueError("TTS requires exactly one speakable provider segment")
        with self._connect() as conn:
            lease = reserve(conn, stt_ms=0, tts_chars=len(chunks[0]), calls=1, lease_seconds=self._lease_seconds)
            start(conn, lease)
            result = await self._adapter.synthesize_tts(req)
            complete(conn, lease)
            return result
