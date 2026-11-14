"""Credential-safe configuration and provider-boundary regression checks."""
import asyncio
from pathlib import Path

import httpx
import pytest

from backend.app.core.config import Settings, clear_settings_cache, get_settings
from backend.app.models.api_schemas import STTRequest, TTSRequest
from backend.app.speech.audio_utils import generate_sine_wav_bytes
from backend.app.speech.gnani_adapter import GnaniSpeechAdapter, GnaniTransportError
from backend.app.speech.service import SpeechService


@pytest.fixture(autouse=True)
def isolated_credentials(monkeypatch):
    for key in ('VCC_GNANI_API_KEY', 'GNANI_API_KEY', 'GNANI_API_KEY_ID', 'VCC_ENV_FILE'):
        monkeypatch.delenv(key, raising=False)
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_canonical_key_wins_alias_without_exposing_secret(monkeypatch):
    monkeypatch.setenv('VCC_GNANI_API_KEY', 'canonical-test-credential')
    monkeypatch.setenv('GNANI_API_KEY', 'alias-test-credential')
    settings = Settings(_env_file=None)
    assert settings.gnani_api_key.get_secret_value() == 'canonical-test-credential'
    assert 'canonical-test-credential' not in repr(settings)


def test_canonical_file_key_wins_legacy_environment_alias(monkeypatch, tmp_path):
    path = tmp_path / '.env'
    path.write_text('VCC_GNANI_API_KEY=canonical-file-test\n')
    monkeypatch.setenv('GNANI_API_KEY', 'legacy-environment-test')
    assert Settings(_env_file=path).gnani_api_key.get_secret_value() == 'canonical-file-test'


def test_explicit_file_credentials_override_stale_process_credentials(monkeypatch, tmp_path):
    path = tmp_path / '.env'
    path.write_text('VCC_GNANI_API_KEY=selected-file-test\n')
    monkeypatch.setenv('VCC_GNANI_API_KEY', 'your-api-key')
    monkeypatch.setenv('VCC_GROQ_API_KEY', 'unselected-account-test')
    configured = Settings(_env_file=path)
    assert configured.gnani_api_key.get_secret_value() == 'selected-file-test'
    assert configured.groq_api_key is None
    assert Settings(_env_file=path, gnani_api_key=None).gnani_api_key is None


def test_official_sdk_alias_is_accepted(monkeypatch):
    monkeypatch.setenv('GNANI_API_KEY', 'alias-test-credential')
    assert Settings(_env_file=None).gnani_api_key.get_secret_value() == 'alias-test-credential'


@pytest.mark.parametrize('value', ['', 'your-gnani-api-key', 'YOUR_API_KEY_HERE', '<API_KEY>', 'replace_me', 'insert_actual_gnani_api_key_here', 'changeme'])
def test_placeholder_canonical_blocks_alias_fallback(monkeypatch, value):
    monkeypatch.setenv('VCC_GNANI_API_KEY', value)
    monkeypatch.setenv('GNANI_API_KEY', 'alias-test-credential')
    assert Settings(_env_file=None).gnani_api_key is None


def test_dotenv_is_loaded_only_after_explicit_opt_in(monkeypatch, tmp_path):
    path = tmp_path / '.env'
    path.write_text('VCC_GNANI_API_KEY=local-test-credential\n')
    monkeypatch.chdir(tmp_path)
    assert get_settings().gnani_api_key is None
    monkeypatch.setenv('VCC_ENV_FILE', str(path))
    clear_settings_cache()
    assert get_settings().gnani_api_key.get_secret_value() == 'local-test-credential'
    assert Settings(_env_file=None).gnani_api_key is None


def test_explicit_credential_free_service_never_uses_ambient_key(monkeypatch, tmp_path):
    monkeypatch.setenv('VCC_GNANI_API_KEY', 'ambient-test-credential')
    settings = Settings(_env_file=None, gnani_api_key=None)
    service = SpeechService(db_path=tmp_path/'db.sqlite', cache_dir=tmp_path/'cache', settings=settings)
    try:
        with pytest.raises(GnaniTransportError):
            service.adapter._resolve_api_key()
    finally:
        service.close()


def test_explicit_placeholder_adapter_blocks_network():
    with pytest.raises(GnaniTransportError):
        GnaniSpeechAdapter(api_key='your-api-key')._resolve_api_key()


def test_stt_network_error_is_safe_and_not_secret_bearing():
    def fail(request):
        raise httpx.ConnectError('secret-bearing-debug-detail', request=request)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
            adapter = GnaniSpeechAdapter(api_key='test-only', http_client=client)
            with pytest.raises(GnaniTransportError) as caught:
                await adapter.transcribe_rest(STTRequest(session_id='network'), generate_sine_wav_bytes(duration_sec=.1))
            assert 'secret-bearing-debug-detail' not in str(caught.value)
            assert caught.value.retryable and caught.value.status_code is None
    asyncio.run(run())


@pytest.mark.parametrize('speed', [.5, 2.0])
def test_provider_speed_outside_official_range_is_rejected_before_dispatch(speed):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(400))) as client:
            adapter = GnaniSpeechAdapter(api_key='test-only', http_client=client)
            with pytest.raises(ValueError, match='speed'):
                await adapter.synthesize_tts(TTSRequest(session_id='speed', text='Hello', speed=speed))
    asyncio.run(run())
