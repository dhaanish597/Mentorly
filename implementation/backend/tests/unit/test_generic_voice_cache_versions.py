"""Fixed public audio cache varies by content contract, voice/model and language."""
from backend.app.models.api_schemas import TTSAudioConfig
from backend.app.speech.audio_utils import generate_sine_wav_bytes
from backend.app.speech import tts_cache


def test_public_content_version_separates_same_text_bytes(monkeypatch, tmp_path):
    first=tts_cache.TTSDiskCache(tmp_path)
    key=first.compute_cache_key(normalized_text='Fixed public voice test.')
    wav=generate_sine_wav_bytes(duration_sec=.1)
    first.put_completed_stream(key,wav,stream_completed=True,audio_config=TTSAudioConfig(sample_rate=16000,container='wav'),scope='PUBLIC_GENERIC')
    assert first.get_wav(key,scope='PUBLIC_GENERIC')==wav
    monkeypatch.setattr(tts_cache,'PUBLIC_GENERIC_CONTENT_VERSION','fixed-voice-v2')
    second=tts_cache.TTSDiskCache(tmp_path)
    assert second.public_dir != first.public_dir
    assert second.get_wav(key,scope='PUBLIC_GENERIC') is None
    assert first.get_wav(key,scope='PUBLIC_GENERIC')==wav


def test_language_voice_model_and_normalizer_version_separate_public_content_keys():
    compute=tts_cache.TTSDiskCache.compute_cache_key
    base=compute(normalized_text='Fixed public voice test.')
    assert compute(normalized_text='Fixed public voice test.',language='auto')!=base
    assert compute(normalized_text='Fixed public voice test.',voice='Shivani')!=base
    assert compute(normalized_text='Fixed public voice test.',model='different-model')!=base
    assert compute(normalized_text='Fixed public voice test.',normalizer_version='v-next')!=base
    assert compute(normalized_text='Changed public voice test.')!=base
