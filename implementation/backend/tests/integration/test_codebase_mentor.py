"""Integration tests for Codebase Learning AI Mentor service and routes."""

import json
import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.db.migrations import apply_migrations, open_connection
from backend.app.main import create_app
from backend.app.repo_learning.ingest import golden
from backend.app.repo_learning.service import create as create_repo, queue as queue_repo


@pytest.fixture
def mentor_env(tmp_path: Path):
    db_path = tmp_path / "mentor_test.db"
    tts_dir = tmp_path / "tts_cache"
    tts_dir.mkdir()
    apply_migrations(db_path)

    conn = open_connection(db_path)
    # Create workspace
    conn.execute("INSERT INTO studio_workspaces VALUES ('ws_mentor', 'tok_hash', '2026-11-15T00:00:00', '2026-11-16T00:00:00', NULL)")

    # Ingest golden repo
    files, cov = golden("REPO-EXP-01")
    snap_id = queue_repo(str(db_path), "ws_mentor", "golden_curated", "REPO-EXP-01")
    create_repo(str(db_path), "ws_mentor", "golden_curated", files, cov, snap_id)
    conn.close()

    settings = Settings(
        _env_file=".env",
        database_path=db_path,
        tts_cache_dir=tts_dir,
    )
    app = create_app(settings)
    client = TestClient(app)
    headers = {"X-Workspace-Id": "ws_mentor", "X-Workspace-Token": "tok_hash"}
    return {"client": client, "headers": headers, "snap_id": snap_id, "db_path": db_path}


def test_session_lifecycle_and_mentor_greeting(mentor_env):
    client = mentor_env["client"]
    headers = mentor_env["headers"]
    snap_id = mentor_env["snap_id"]

    # 1. Create session
    create_res = client.post("/api/v1/codebase-learning/sessions", headers=headers, json={
        "snapshot_id": snap_id,
        "repo_url": "https://github.com/fastapi/fastapi",
        "repo_name": "fastapi/fastapi",
        "branch": "main",
        "title": "Understanding FastAPI",
    })
    assert create_res.status_code == 201
    data = create_res.json()
    session_id = data["session_id"]
    assert data["repo_snapshot_id"] == snap_id
    assert data["title"] == "Understanding FastAPI"
    assert data["knowledge_level"] == "undetermined"
    assert len(data["messages"]) == 1
    greeting = data["messages"][0]
    assert greeting["role"] == "mentor"
    assert "Before we dive in" in greeting["content"]

    # 2. Get session
    get_res = client.get(f"/api/v1/codebase-learning/sessions/{session_id}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["session_id"] == session_id

    # 3. Rename session
    rename_res = client.patch(f"/api/v1/codebase-learning/sessions/{session_id}", headers=headers, json={
        "title": "Deep Dive into FastAPI Architecture"
    })
    assert rename_res.status_code == 200
    assert rename_res.json()["title"] == "Deep Dive into FastAPI Architecture"

    # 4. Submit text turn
    turn_res = client.post(f"/api/v1/codebase-learning/sessions/{session_id}/turns", headers=headers, json={
        "text": "I am an experienced Python developer, but I want to understand how routes and sessions work."
    })
    assert turn_res.status_code == 200
    turn_data = turn_res.json()
    assert turn_data["learner_message"]["role"] == "learner"
    assert turn_data["mentor_message"]["role"] == "mentor"
    assert turn_data["knowledge_level"] == "advanced"
    assert len(turn_data["mentor_message"]["content"]) > 10

    # 5. List sessions
    list_res = client.get("/api/v1/codebase-learning/sessions", headers=headers)
    assert list_res.status_code == 200
    sessions = list_res.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == session_id
    assert sessions[0]["title"] == "Deep Dive into FastAPI Architecture"
    assert sessions[0]["message_count"] == 3

    # 6. Delete session
    del_res = client.delete(f"/api/v1/codebase-learning/sessions/{session_id}", headers=headers)
    assert del_res.status_code == 204

    # 7. Confirm deleted session not listed
    list_after = client.get("/api/v1/codebase-learning/sessions", headers=headers)
    assert len(list_after.json()["sessions"]) == 0


def test_session_bound_validation(mentor_env):
    client = mentor_env["client"]
    headers = mentor_env["headers"]

    # Attempt to bind session to non-existent snapshot
    res = client.post("/api/v1/codebase-learning/sessions", headers=headers, json={
        "snapshot_id": "nonexistent_snapshot_id",
        "repo_url": "https://github.com/fastapi/fastapi",
        "repo_name": "fastapi/fastapi",
    })
    assert res.status_code == 409
    msg = res.json().get("message") or res.json().get("detail", "")
    assert "snapshot is not ready" in msg.lower()


def test_text_turn_validation(mentor_env):
    client = mentor_env["client"]
    headers = mentor_env["headers"]
    snap_id = mentor_env["snap_id"]

    res = client.post("/api/v1/codebase-learning/sessions", headers=headers, json={
        "snapshot_id": snap_id,
        "repo_url": "https://github.com/fastapi/fastapi",
        "repo_name": "fastapi/fastapi",
    })
    session_id = res.json()["session_id"]

    # Empty turn text
    empty_turn = client.post(f"/api/v1/codebase-learning/sessions/{session_id}/turns", headers=headers, json={
        "text": "   "
    })
    assert empty_turn.status_code == 422
