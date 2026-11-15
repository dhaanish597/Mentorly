"""Unit tests for Phase 0 core configuration, branding, and metadata endpoints."""

import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from backend.app.core.branding import clear_branding_cache
from backend.app.core.config import clear_settings_cache
from backend.app.main import create_app


@pytest.fixture(autouse=True)
def _reset_caches(tmp_path, monkeypatch):
    monkeypatch.setenv("VCC_DATABASE_PATH", str(tmp_path / "meta.sqlite3"))
    branding_fixture = tmp_path / 'branding.json'
    branding_fixture.write_text(json.dumps({'productName': 'VIVA', 'productNameStatus': 'CONFIGURED', 'shortName': 'V', 'tagline': 'Explain, predict, verify, and transfer.'}), encoding='utf-8')
    monkeypatch.setenv('VCC_BRANDING_CONFIG_PATH', str(branding_fixture))
    clear_settings_cache()
    clear_branding_cache()
    yield
    clear_settings_cache()
    clear_branding_cache()


def test_health_endpoint_returns_minimal_liveness_and_safe_defaults() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/meta/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "vcc-coordinator"
    assert payload["phase"] == "P0-P9"
    assert payload["execution_status"] == "DISABLED"
    assert payload["custom_code_execution_enabled"] is False
    assert payload["product_name"] == "VIVA"
    assert payload["product_name_status"] == "CONFIGURED"
    assert "X-Request-ID" in response.headers


def test_branding_endpoint_returns_config_values() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/meta/branding")

    assert response.status_code == 200
    assert response.json() == {
        "productName": "VIVA",
        "productNameStatus": "CONFIGURED",
        "shortName": "V",
        "tagline": "Explain, predict, verify, and transfer.",
    }


def test_branding_override_via_env_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override_file = tmp_path / "custom_branding.json"
    override_file.write_text(
        json.dumps(
            {
                "productName": "CustomCoach",
                "productNameStatus": "FINALIZED",
                "shortName": "CC",
                "tagline": "Custom tagline for testing.",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("VCC_BRANDING_CONFIG_PATH", str(override_file))
    clear_settings_cache()
    clear_branding_cache()

    app = create_app()
    with TestClient(app) as client:
        branding_res = client.get("/api/v1/meta/branding")
        health_res = client.get("/api/v1/meta/health")

    assert branding_res.status_code == 200
    assert branding_res.json()["productName"] == "CustomCoach"
    assert branding_res.json()["productNameStatus"] == "FINALIZED"
    assert health_res.status_code == 200
    assert health_res.json()["product_name"] == "CustomCoach"


def test_exercises_metadata_covers_all_specs_without_oracle_or_holdout_leaks() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/meta/exercises")

    assert response.status_code == 200
    exercises = response.json()
    assert len(exercises) == 31
    assert [item["exercise_id"] for item in exercises[:3]] == [
        "ex1_shortest_subarray",
        "ex2_binary_search",
        "ex3_max_product",
    ]

    spec_pairs = {
        (item["exercise_id"], spec["spec_version"])
        for item in exercises
        for spec in item["spec_versions"]
    }
    assert len(spec_pairs) == 32
    assert spec_pairs >= {
        ("ex1_shortest_subarray", "v1_positive_only"),
        ("ex1_shortest_subarray", "v2_negatives_allowed"),
        ("ex2_binary_search", "v1_sorted_with_duplicates"),
        ("ex3_max_product", "v1_bounded_ints"),
    }

    serialized = json.dumps(exercises).lower()
    forbidden_terms = (
        "holdout",
        "oracle",
        "reference_output",
        "expected_output",
        "ref_shortest_subarray",
        "ref_first_at_least",
        "ref_max_product",
        "[2,-1,2,3]",
        "[0,3,3,8]",
        "[-2,-3,-4]",
    )
    for term in forbidden_terms:
        assert term not in serialized


def test_demo_presets_endpoint_is_public_safe() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/meta/demo-presets")

    assert response.status_code == 200
    presets = response.json()
    assert len(presets) >= 3
    for preset in presets:
        assert preset["provenance_label"] in {"RECORDED_DEMO", "LIVE_SESSION"}
        assert preset["language_mode"] in {"en-IN", "ta-IN,en-IN"}


def test_p1_plus_routes_are_not_faked_and_return_canonical_api_error() -> None:
    app = create_app()
    with TestClient(app) as client:
        for path in (
            "/api/v1/sessions/demo/turns/audio",
            "/api/v1/sessions/demo/verify",
            "/api/v1/sessions/demo/traces/t1",
            "/api/v1/sessions/demo/audio/p1",
        ):
            res = client.post(path) if "turns" in path or "verify" in path else client.get(path)
            assert res.status_code == 401
            body = res.json()
            assert body["code"] == "SESSION_AUTH_REQUIRED"
            assert isinstance(body["message"], str) and body["message"]
            assert isinstance(body["request_id"], str) and body["request_id"]
            assert body["retryable"] is False
