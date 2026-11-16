import os
import pytest
from backend.app.speech.audio_utils import wrap_raw_pcm_as_wav
from backend.app.speech.tts_cache import TTSDiskCache


def test_completed_audio_survives_disk_cache_outage(tmp_path, monkeypatch):
    cache = TTSDiskCache(tmp_path/'cache')
    wav = wrap_raw_pcm_as_wav(b'\0'*3200, sample_rate_hz=22050, num_channels=1, sample_width_bytes=2)
    monkeypatch.setattr(os, 'open', lambda *args, **kwargs: (_ for _ in ()).throw(OSError('test disk outage')))
    delivered = cache.put_completed_stream('key', wav, stream_completed=True, scope='SESSION_SCOPED', session_id='owned')
    assert delivered == wav
    assert cache.get_wav('key', session_id='owned') is None


def test_cache_restart_preserves_valid_scope_and_deletion(tmp_path):
    root = tmp_path/'cache'
    cache = TTSDiskCache(root)
    wav = wrap_raw_pcm_as_wav(b'\0'*3200, sample_rate_hz=22050, num_channels=1, sample_width_bytes=2)
    cache.put_completed_stream('key', wav, stream_completed=True, session_id='owned')
    restarted = TTSDiskCache(root)
    assert restarted.get_wav('key', session_id='owned') == wav
    assert restarted.get_wav('key', session_id='other') is None
    assert restarted.evict_session('owned') == 1
    assert cache.get_wav('key', session_id='owned') is None
    with pytest.raises(ValueError):
        restarted.put_completed_stream('../invalid', wav, stream_completed=True, session_id='owned')
