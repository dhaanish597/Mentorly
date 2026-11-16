"""Documented provider capabilities; configuration is not a live entitlement check."""
from __future__ import annotations

from backend.app.core.config import validated_credential
from backend.app.models.enums import LanguageMode, SpeechLocale, TTSVoice

STT_MODEL = 'prisma-v3.0'
TTS_MODEL = 'timbre-v3.0'
LANGUAGE_LABELS = ('English', 'Hindi', 'Tamil', 'Telugu', 'Kannada', 'Malayalam', 'Bengali', 'Gujarati', 'Marathi', 'Punjabi')
CODEMIX_MODES = (LanguageMode.TA_IN_EN_IN, LanguageMode.HI_IN_EN_IN, LanguageMode.BN_IN_EN_IN)


def resolve_tts_language(language_mode: LanguageMode | str, spoken_language: SpeechLocale | str | None = None) -> str:
    """An explicit spoken locale wins; legacy mixed STT uses documented script auto."""
    mode = LanguageMode(language_mode)
    if spoken_language is not None:
        if spoken_language == 'auto':
            return 'auto'
        return SpeechLocale(spoken_language).value
    return 'auto' if mode in CODEMIX_MODES else SpeechLocale(mode.value).value


def resolve_tts_selection(language_mode: LanguageMode | str = LanguageMode.EN_IN, *,
                          spoken_language: SpeechLocale | str | None = None,
                          voice: TTSVoice | str | None = None, model: str = TTS_MODEL,
                          default_voice: TTSVoice | str = TTSVoice.AVINASH) -> dict[str, str]:
    """Validate before reservation: never silently substitute an unsupported voice/model."""
    if model != TTS_MODEL:
        raise ValueError('Only the documented Timbre v3.0 voice catalog is enabled.')
    return {'language': resolve_tts_language(language_mode, spoken_language),
            'voice': TTSVoice(voice if voice is not None else default_voice).value,
            'model': model}


def session_tts_selection(session, *, model: str = TTS_MODEL, default_voice: str = 'Avinash',
                          language: str | None = None, voice: str | None = None) -> dict[str, str]:
    """Read optional migrated session columns without breaking pre-migration callers."""
    keys = session.keys()
    mode = session['language_mode'] if 'language_mode' in keys and session['language_mode'] else 'en-IN'
    spoken = language if language is not None else (session['spoken_language'] if 'spoken_language' in keys else None)
    selected_voice = voice if voice is not None else (session['voice'] if 'voice' in keys else None)
    return resolve_tts_selection(mode, spoken_language=spoken, voice=selected_voice,
                                 model=model, default_voice=default_voice)


def speech_capabilities(settings=None) -> dict[str, object]:
    """Public data only; no network, credentials, provider balance, or readiness promises."""
    configured = bool(settings is not None and validated_credential(settings.gnani_api_key))
    locales = [locale.value for locale in SpeechLocale]
    voices = [voice.value for voice in TTSVoice]
    return {
        'provider': 'gnani', 'stt_model': STT_MODEL, 'tts_model': TTS_MODEL,
        'documented': True, 'live_unverified': True, 'provider_verified': False,
        'configured': configured, 'status': 'CONFIGURED_UNVERIFIED' if configured else 'TEXT_ONLY',
        'languages': [{'code': locale, 'label': label, 'documented': True, 'config_tested': True,
                       'live_unverified': True, 'compatible_voices': list(voices),
                       'code_mixing': f'{locale},en-IN' in CODEMIX_MODES}
                      for locale, label in zip(locales, LANGUAGE_LABELS)],
        'voices': [{'id': voice, 'model': TTS_MODEL, 'languages': list(locales),
                    'documented': True, 'live_unverified': True} for voice in voices],
        'language_modes': [mode.value for mode in LanguageMode],
        'code_mixing_modes': [mode.value for mode in CODEMIX_MODES],
        'tts_auto_language': True,
        'defaults': {'stt_language': 'en-IN', 'spoken_language': 'en-IN', 'voice': 'Avinash'},
        'limits': {'capture_seconds': 30, 'pcm_sample_rate': 16000, 'pcm_channels': 1,
                   'requested_concurrency': settings.gnani_max_concurrency if settings else 1,
                   'effective_concurrency': settings.gnani_effective_concurrency if settings else 1,
                   'coordination_scope': 'single_coordinator'},
    }
