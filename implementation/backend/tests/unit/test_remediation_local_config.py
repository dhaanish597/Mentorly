import json
import pytest
from backend.app.core.config import Settings
from backend.app.core.local_config import local_development
from scripts.doctor import diagnostics
from scripts.start_local import preview_environment


def test_canonical_loopback_ports_and_explicit_override():
    config = local_development()
    assert config.backend_origin == 'http://127.0.0.1:8020'
    assert config.frontend_port == 5173
    assert set(config.cors_origins.split(',')) == {'http://localhost:5173', 'http://127.0.0.1:5173'}
    override = local_development({'VCC_BACKEND_PORT': '8037', 'VCC_FRONTEND_PORT': '5191'})
    assert override.backend_port == 8037
    assert 'http://localhost:5191' in override.cors_origins


@pytest.mark.parametrize('env', [{'VCC_BACKEND_PORT': '-1'}, {'VCC_FRONTEND_PORT': '8020/path'}, {'VCC_BACKEND_HOST': 'remote.invalid'}])
def test_invalid_local_routing_fails_closed(env):
    with pytest.raises(ValueError):
        local_development(env)


def test_preview_strips_database_credentials_and_cloud_mode():
    preview = preview_environment({'VCC_DATABASE_URL': 'postgresql://private.invalid/db', 'VCC_CLOUD_RUNTIME': 'true'})
    assert preview['VCC_DATABASE_URL'] == '' and preview['VCC_CLOUD_RUNTIME'] == 'false'


def test_doctor_is_redacted_and_offline_provider_safe():
    config = local_development()
    settings = Settings(_env_file=None, gnani_api_key=None, groq_api_key=None, database_url=None)
    visited = []
    report = diagnostics(settings, config, lambda origin: visited.append(origin) or True)
    assert report['api_reachable'] and report['cors_match']
    assert visited == ['http://127.0.0.1:8020']
    assert report['speech_provider'] == 'disabled'
    assert report['database_backend'] == 'sqlite'
    assert 'api_key' not in json.dumps(report) and 'database_url' not in json.dumps(report)
