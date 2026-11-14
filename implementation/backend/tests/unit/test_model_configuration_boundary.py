"""Selected app settings, never ambient keys, determine model requests."""
from pydantic import SecretStr
import pytest
from backend.app.api import routes_sessions
from backend.app.core.config import Settings


@pytest.mark.parametrize("provider,key,model,expected_key,expected_model", [
    ("deterministic", "test-valid-credential", "test-model", "", ""),
    ("groq", None, "test-model", "", ""),
    ("groq", "test-valid-credential", "test-model", "test-valid-credential", "test-model"),
])
def test_model_factories_use_selected_settings(monkeypatch, provider, key, model, expected_key, expected_model):
    monkeypatch.setenv("VCC_GROQ_API_KEY", "ambient-key-must-not-be-used")
    monkeypatch.setenv("VCC_LLM_MODEL", "ambient-model-must-not-be-used")
    selected = Settings(_env_file=None, llm_provider=provider, groq_api_key=SecretStr(key) if key else None, llm_model=model)
    monkeypatch.setattr(routes_sessions, "get_settings", lambda: selected)
    coach = routes_sessions._configured_coach()
    extractor = routes_sessions._configured_extractor()
    assert coach._api_key == expected_key
    assert coach._model == expected_model
    assert extractor.api_key == expected_key
    assert extractor.model == expected_model


def test_websocket_factory_can_receive_selected_app_settings(monkeypatch):
    ambient = Settings(_env_file=None, llm_provider="groq", groq_api_key=SecretStr("ambient-test-key"), llm_model="ambient-test-model")
    selected = Settings(_env_file=None, llm_provider="deterministic", groq_api_key=None)
    monkeypatch.setattr(routes_sessions, "get_settings", lambda: ambient)
    extractor = routes_sessions._configured_extractor(selected)
    assert extractor.api_key == ""
    assert extractor.model == ""
