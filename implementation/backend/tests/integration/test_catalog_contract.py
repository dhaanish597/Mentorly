"""Real HTTP catalog/session contracts; no provider or learner execution."""
import json

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app


def test_advertised_catalog_is_complete_public_safe_and_session_compatible(tmp_path):
    settings = Settings(
        _env_file=None, database_path=tmp_path / "catalog.db",
        tts_cache_dir=tmp_path / "tts", gnani_api_key=None,
        llm_provider="deterministic", allow_public_custom_code=False,
        per_ip_request_limit=1000, global_request_limit=1000,
        session_creation_limit=1000,
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/meta/exercises")
        assert response.status_code == 200
        catalog = response.json()
        assert len(catalog) >= 30
        ids = [problem["exercise_id"] for problem in catalog]
        assert len(ids) == len(set(ids))
        assert ids[:3] == ["ex1_shortest_subarray", "ex2_binary_search", "ex3_max_product"]
        for forbidden in ("oracle", "holdout", "reference_output", "known_bugs", "correct_alternatives"):
            assert forbidden not in json.dumps(catalog).lower()
        for problem in catalog:
            assert problem["examples"] and problem["input_schema"] and problem["output_schema"]
            assert problem["catalog_status"] == "READY"
            assert problem["comparator"] == "strict_structural"
            assert problem["provenance"]["source"]
            for spec in problem["spec_versions"]:
                created = client.post("/api/v1/sessions", json={
                    "exercise_id": problem["exercise_id"], "spec_version": spec["spec_version"],
                    "interaction_mode": "TYPED_FALLBACK",
                })
                assert created.status_code == 200, created.text
                payload = created.json()
                assert payload["starter_code"] == problem["starter_code"]
                assert payload["revision"]["exercise_id"] == problem["exercise_id"]
                assert payload["revision"]["spec_version"] == spec["spec_version"]
                restored = client.get("/api/v1/sessions/" + payload["session_id"], headers={
                    "Authorization": "Bearer " + payload["session_token"],
                })
                assert restored.status_code == 200, restored.text
                assert restored.json()["source_code"] == problem["starter_code"]
        assert client.get("/api/v1/meta/health").json()["custom_code_execution_enabled"] is False
