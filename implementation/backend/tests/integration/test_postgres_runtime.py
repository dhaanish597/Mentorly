"""Actual HTTP coordinator parity against opt-in disposable PostgreSQL.

VIVA_POSTGRES_TEST_DSN must identify a dedicated test database, never production.
UUID schemas are deleted after each case. No provider or learner code executes.
"""

import json
import os
import uuid
from concurrent.futures import ProcessPoolExecutor
from contextlib import closing

import pytest
from backend.app.core.config import Settings
from backend.app.db.migrations import open_connection
from backend.app.db.postgres.runtime import PostgresTarget, initialize
from backend.app.main import create_app
from fastapi.testclient import TestClient
from pydantic import SecretStr

DSN = os.environ.get("VIVA_POSTGRES_TEST_DSN")
pytestmark = pytest.mark.skipif(
    not DSN, reason="Dedicated disposable PostgreSQL DSN required"
)


@pytest.fixture
def runtime(tmp_path):
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql

    schema = "viva_runtime_" + uuid.uuid4().hex
    target = PostgresTarget(DSN, schema)
    settings = Settings(
        database_url=SecretStr(DSN),
        database_schema=schema,
        database_path=tmp_path / "unused.sqlite3",
        tts_cache_dir=tmp_path / "cache",
        groq_api_key=None,
        gnani_api_key=None,
        env="test",
    )
    try:
        with TestClient(create_app(settings)) as client:
            yield client, target
        assert not settings.database_path.exists(), (
            "PostgreSQL must not silently create SQLite"
        )
    finally:
        with psycopg.connect(DSN, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema)
                )
            )


def _workspace(client):
    wid = str(uuid.uuid4())
    token = "w" * 48
    response = client.post(
        "/api/v1/studio/workspaces",
        json={"workspace_id": wid, "workspace_token": token},
        headers={"X-Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 200, response.text
    return wid, token, {"X-Workspace-Id": wid, "X-Workspace-Token": token}


def test_postgres_full_lifespan_learning_interview_and_privacy(runtime):
    client, target = runtime
    assert client.get("/api/v1/meta/health").status_code == 200
    wid, token, headers = _workspace(client)
    lesson = client.post(
        "/api/v1/learning/sessions",
        headers=headers,
        json={
            "lesson_id": "dsa-complexity",
            "mode": "practice",
            "language_mode": "en-IN",
        },
    )
    assert lesson.status_code == 200, lesson.text
    session = lesson.json()
    with closing(open_connection(target)) as conn:
        record = conn.execute(
            "SELECT lesson_json FROM learning_sessions WHERE id=?", (session["id"],)
        ).fetchone()
        answer = json.loads(record[0])["question"]["correct_answer"]
    response = client.post(
        f"/api/v1/learning/sessions/{session['id']}/answers",
        headers=headers,
        json={
            "expected_epoch": session["epoch"],
            "question_id": session["question"]["id"],
            "answer": answer,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "completed"
    progress = client.get("/api/v1/learning/progress", headers=headers)
    assert progress.status_code == 200, progress.text
    assert progress.json()["lessons_completed"] == 1
    interview = client.post(
        "/api/v1/interviews/sessions",
        headers=headers,
        json={
            "type": "dsa",
            "difficulty": "beginner",
            "topics": [],
            "duration_minutes": 15,
            "language_mode": "en-IN",
        },
    )
    assert interview.status_code == 200, interview.text
    data = interview.json()
    sid = data["id"]
    response = client.post(
        f"/api/v1/interviews/sessions/{sid}/answers",
        headers=headers,
        json={
            "expected_epoch": data["epoch"],
            "answer": "I would scan each value; no execution is claimed.",
        },
    )
    assert response.status_code == 200, response.text
    end = client.post(
        f"/api/v1/interviews/sessions/{sid}/finish",
        headers=headers,
        json={"expected_epoch": response.json()["epoch"]},
    )
    assert end.status_code == 200, end.text
    assert client.get(
        f"/api/v1/interviews/sessions/{sid}",
        headers={**headers, "X-Workspace-Token": "invalid"},
    ).status_code in {401, 404}
    deleted = client.delete(
        f"/api/v1/studio/workspaces/{wid}",
        headers={
            "Authorization": "Bearer " + token,
            "X-Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert deleted.status_code == 200, deleted.text
    with closing(open_connection(target)) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM learning_sessions WHERE workspace_id=?", (wid,)
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM interview_sessions WHERE workspace_id=?", (wid,)
            ).fetchone()[0]
            == 0
        )


def test_postgres_studio_idempotency_and_json_corrections(runtime):
    client, target = runtime
    wid, token, _ = _workspace(client)
    catalog = client.get("/api/v1/studio/scenarios").json()
    assert catalog
    # Reuse the stable scenario exercised by existing SQLite HTTP tests.
    from backend.app.studio.routes import SCENARIOS

    scenario = next(
        s for s in SCENARIOS.values() if s["mode"] == "guided_system_design"
    )
    sid = str(uuid.uuid4())
    key = str(uuid.uuid4())
    auth = {"Authorization": "Bearer " + token, "X-Idempotency-Key": key}
    payload = {
        "workspace_id": wid,
        "session_id": sid,
        "session_token": "s" * 48,
        "mode": scenario["mode"],
        "posture": "teaching",
        "scenario_id": scenario["id"],
        "scenario_version": scenario["version"],
    }
    first = client.post("/api/v1/studio/sessions", headers=auth, json=payload)
    assert first.status_code == 200, first.text
    assert (
        client.post("/api/v1/studio/sessions", headers=auth, json=payload).json()
        == first.json()
    )
    turns = {
        "Authorization": "Bearer " + "s" * 48,
        "X-Idempotency-Key": str(uuid.uuid4()),
    }
    response = client.post(
        f"/api/v1/studio/sessions/{sid}/turns",
        headers=turns,
        json={
            "epoch": 1,
            "kind": "typed",
            "text": "Users authenticate before any private query.",
        },
    )
    assert response.status_code == 200, response.text
    assert (
        client.get(f"/api/v1/studio/sessions/{sid}", headers=turns).status_code == 200
    )
    with open_connection(target) as conn:
        for sequence, value in enumerate((True, False, 1, 0), start=100):
            conn.execute(
                "INSERT INTO studio_events VALUES(?,?,?,?,?)",
                (
                    sid,
                    sequence,
                    "test.assistance",
                    json.dumps({"assistance": value}),
                    "2026-11-15T00:00:00+00:00",
                ),
            )
    summary = client.get(f"/api/v1/studio/sessions/{sid}/summary", headers=turns)
    assert summary.status_code == 200, summary.text
    assert summary.json()["assistance_events"] == 2
    with closing(open_connection(target)) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM studio_sessions WHERE workspace_id=?", (wid,)
            ).fetchone()[0]
            == 1
        )


def _reserve_admission(dsn, schema):
    from backend.app.operations.admission import AdmissionController

    target = PostgresTarget(dsn, schema)
    return (
        AdmissionController(target, global_limit=1, per_ip_limit=100)
        .admit(
            {
                "path": "/api/v1/meta/health",
                "method": "GET",
                "client": ("127.0.0.1", 0),
                "headers": [],
            }
        )
        .allowed
    )


def test_postgres_two_processes_atomically_share_admission(runtime):
    _, target = runtime
    with ProcessPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(_reserve_admission, [target.dsn] * 2, [target.schema] * 2)
        )
    assert sorted(results) == [False, True]


def test_postgres_schema_full_columns_triggers_and_idempotence(runtime):
    _, target = runtime
    assert initialize(target) == []
    with target.connect() as conn:
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema=%s",
            (target.schema,),
        ).fetchall()
        assert {
            "sessions",
            "workspace_recovery",
            "learning_sessions",
            "interview_sessions",
            "studio_sessions",
            "usage_reservations",
            "admission_counters",
            "model_dispatch_leases",
            "repo_chunks_fts",
        } <= {row[0] for row in tables}
        assert (
            conn.execute(
                "SELECT count(*) FROM information_schema.triggers WHERE trigger_schema=%s",
                (target.schema,),
            ).fetchone()[0]
            >= 27
        )
