"""Reuse existing behavioral HTTP assertions unchanged with actual PostgreSQL.

The same lesson/interview/repository contract assertions run on both backends;
this file supplies only PostgreSQL fixture setup. Unsupported SQL cannot be hidden
by independent mock expectations. DSN must be a dedicated disposable test DB.
"""

import inspect
from types import SimpleNamespace

import pytest
from backend.app.db.migrations import open_connection
from backend.app.studio.security import digest_token
from backend.tests.integration import test_product_interview_api as interviews
from backend.tests.integration import test_product_learning_api as lessons
from backend.tests.integration import test_repo_learning as repos
from backend.tests.integration import test_workspace_recovery as recovery
from backend.tests.integration.test_postgres_runtime import runtime as runtime  # noqa: PLC0414 - pytest fixture re-export
from fastapi import FastAPI
from fastapi.testclient import TestClient


def contracts(module, fixture):
    return [
        name
        for name, fn in vars(module).items()
        if name.startswith("test_")
        and callable(fn)
        and fixture in inspect.signature(fn).parameters
        and set(inspect.signature(fn).parameters) <= {fixture, "monkeypatch"}
    ]


@pytest.mark.parametrize("name", contracts(lessons, "learning"))
def test_existing_learning_contract_against_postgres(runtime, name, monkeypatch):
    _, target = runtime
    with TestClient(lessons.application(target)) as client:
        headers = lessons.workspace(client)
        args = {"learning": (client, headers, target), "monkeypatch": monkeypatch}
        fn = getattr(lessons, name)
        fn(**{key: args[key] for key in inspect.signature(fn).parameters})


@pytest.mark.parametrize("name", contracts(interviews, "harness"))
def test_existing_interview_contract_against_postgres(runtime, name, monkeypatch):
    _, target = runtime
    with TestClient(lessons.application(target)) as client:
        owner = lessons.workspace(client)
        other = lessons.workspace(client, "z")
        args = {"harness": (client, target, owner, other), "monkeypatch": monkeypatch}
        fn = getattr(interviews, name)
        fn(**{key: args[key] for key in inspect.signature(fn).parameters})


@pytest.mark.parametrize("name", contracts(repos, "context"))
def test_existing_repository_contract_against_postgres(runtime, name, monkeypatch):
    _, target = runtime
    from backend.app.repo_learning.routes import router

    with open_connection(target) as conn:
        for owner in ("a", "b"):
            conn.execute(
                "INSERT INTO studio_workspaces(id,token_hash,created_at,expires_at) VALUES(?,?,?,?)",
                (
                    owner,
                    digest_token(owner * 40),
                    "2026-01-01T00:00:00+00:00",
                    "2099-01-01T00:00:00+00:00",
                ),
            )
    app = FastAPI()
    app.state.settings = SimpleNamespace(database_path=target)
    app.include_router(router, prefix="/api/v1")
    with TestClient(app) as client:
        fn = getattr(repos, name)
        args = {"context": (target, client), "monkeypatch": monkeypatch}
        fn(**{key: args[key] for key in inspect.signature(fn).parameters})


@pytest.mark.parametrize("name", contracts(recovery, "harness"))
def test_existing_workspace_recovery_contract_against_postgres(
    runtime, name, monkeypatch
):
    client, target = runtime
    headers = lessons.workspace(client)
    args = {
        "harness": (
            client,
            target,
            headers["X-Workspace-Id"],
            headers["X-Workspace-Token"],
        ),
        "monkeypatch": monkeypatch,
    }
    fn = getattr(recovery, name)
    fn(**{key: args[key] for key in inspect.signature(fn).parameters})
