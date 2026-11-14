"""Exercise the authored persona corpus through the real local API.

This verifies deterministic guardrails, not live-model quality or educational
effectiveness. Canonical/alternative graph evaluation has separate fixtures.
"""
import json
from pathlib import Path
import secrets
import uuid

from fastapi.testclient import TestClient
import pytest

from backend.app.core.config import Settings
from backend.app.main import create_app

CORPUS = json.loads((Path(__file__).parents[3] / "evaluation/corpora/v3_pedagogical_eval.json").read_text())["cases"]


def mutation_headers(capability=None):
    return {"X-Idempotency-Key": str(uuid.uuid4()), **({"Authorization": "Bearer " + capability} if capability else {})}


@pytest.mark.parametrize("case", CORPUS, ids=lambda case: case["id"])
def test_local_corpus_preserves_evidence_and_uncertainty(case, tmp_path):
    settings = Settings(database_path=tmp_path / "corpus.sqlite3", tts_cache_dir=tmp_path / "audio",
                        gnani_api_key=None, groq_api_key=None, env="test",
                        session_creation_limit=1000, per_ip_request_limit=10000,
                        per_session_request_limit=10000, global_request_limit=10000)
    with TestClient(create_app(settings)) as client:
        workspace, session = str(uuid.uuid4()), str(uuid.uuid4())
        workspace_token, session_token = secrets.token_urlsafe(40), secrets.token_urlsafe(40)
        response = client.post("/api/v1/studio/workspaces", headers=mutation_headers(),
                               json={"workspace_id": workspace, "workspace_token": workspace_token})
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert workspace_token not in response.text
        catalog = client.get("/api/v1/studio/scenarios").json()["scenarios"]
        scenario = next(s for s in catalog if s["id"] == case["scenario_id"])
        snapshot_id = None
        repo_headers = {"X-Workspace-Id": workspace, "X-Workspace-Token": workspace_token}
        if scenario["mode"] in ("repo_exploration", "project_defense"):
            golden = "REPO-EXP-02" if scenario["id"] == "REPO-EXP-02" else "REPO-EXP-01"
            response = client.post("/api/v1/repos/ingest", headers=repo_headers,
                                   json={"source_kind": "golden_curated", "source_locator": golden})
            assert response.status_code == 202
            snapshot_id = response.json()["snapshot_id"]
            assert client.get(f"/api/v1/repos/{snapshot_id}", headers=repo_headers).json()["status"] == "READY"
        response = client.post("/api/v1/studio/sessions", headers=mutation_headers(workspace_token),
                               json={"workspace_id": workspace, "session_id": session, "session_token": session_token,
                                     "scenario_id": scenario["id"], "scenario_version": scenario["version"],
                                     "mode": scenario["mode"], "posture": "teaching", "repo_snapshot_id": snapshot_id})
        assert response.status_code == 200, response.text
        assert session_token not in response.text
        prefix = f"/api/v1/studio/sessions/{session}"
        last_turn = None
        for turn in case["turns"]:
            response = client.post(prefix + "/turns", headers=mutation_headers(session_token),
                                   json={"epoch": 1, "text": turn["text"]})
            assert response.status_code == 200
            assert response.json()["feedback_status"] == "abstained_insufficient_signal"
            last_turn = response.json()["turn_id"]
        feedback = client.post(prefix + "/feedback", headers=mutation_headers(session_token),
                               json={"epoch": 1, "turn_id": last_turn, "allow_external": False})
        assert feedback.status_code == 200, feedback.text
        assert feedback.json()["source"] == "deterministic_fallback"
        assert feedback.json()["evidence_turn_ids"] == [last_turn]
        current = client.get(prefix, headers=mutation_headers(session_token)).json()
        assert current["diagram_revision"] == 0  # Prose never silently changes an artifact.
        assert current["state"] != "completed"
        assert client.get(prefix, headers=mutation_headers(secrets.token_urlsafe(40))).status_code == 401
        if case["persona"] == "stuck_novice":
            for action in ("options", "explain", "teachback"):
                reply = client.post(prefix + "/coach", headers=mutation_headers(session_token), json={"action": action})
                assert reply.status_code == 200
                assert reply.json()["text"].strip()
            assert client.get(prefix, headers=mutation_headers(session_token)).json()["diagram_revision"] == 0
        if case["persona"] == "unsupported_claim":
            assert client.get(prefix + "/evaluation", headers=mutation_headers(session_token)).json()["status"] == "unknown"
            assert client.post(prefix + "/coach", headers=mutation_headers(session_token), json={"action": "advance"}).status_code == 409
        if case["persona"] == "undocumented_defender":
            found = client.get(f"/api/v1/repos/{snapshot_id}/search", headers=repo_headers, params={"q": "def"}).json()["results"]
            citation = next({k: item[k] for k in ("path", "symbol", "start_line", "end_line", "chunk_hash")}
                            for item in found if item["path"].endswith(".py"))
            evidence = client.post(f"/api/v1/repos/{snapshot_id}/evidence", headers=repo_headers,
                                   json={"topic": "Boundary defense", "observed_code": [citation],
                                         "inferred_rationale": ["An interpretation, not recorded author intent."],
                                         "learner_alternative": case["turns"][-1]["text"]})
            assert evidence.status_code == 200
            assert evidence.json()["author_intent_verifiable"] is False
            assert evidence.json()["inferred_rationale"][0]["uncertainty"]
            bad = {**citation, "chunk_hash": "0" * 64}
            assert client.post(f"/api/v1/repos/{snapshot_id}/evidence", headers=repo_headers,
                               json={"topic": "Fabricated citation", "observed_code": [bad]}).status_code == 422
        summary = client.get(prefix + "/summary", headers=mutation_headers(session_token))
        assert summary.status_code == 200
        assert all(d["status"] == "abstained_insufficient_signal" for d in summary.json()["dimensions"])
        assert client.delete(prefix, headers=mutation_headers(session_token)).status_code == 200
        assert client.get(prefix, headers=mutation_headers(session_token)).status_code == 410
        if snapshot_id:
            assert client.delete(f"/api/v1/repos/{snapshot_id}", headers=repo_headers).status_code == 204
