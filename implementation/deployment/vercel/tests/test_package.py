"""Offline packaging checks; these do not claim deployed/provider acceptance."""

import importlib.util
import json
from pathlib import Path
import tomllib

from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
import pytest

PACKAGE = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


packaging = load_module("deployment_staging", PACKAGE / "stage.py")
spa = load_module("deployment_spa", PACKAGE / "templates" / "deployment_spa.py")


@pytest.fixture
def client(tmp_path):
    app = FastAPI()

    @app.get("/api/known")
    async def known():
        return {"actual_api": True}

    @app.websocket("/ws/echo")
    async def echo(ws: WebSocket):
        await ws.accept()
        await ws.send_text(await ws.receive_text())
        await ws.close()

    index = tmp_path / "index.html"
    index.write_text("<!doctype html><title>Frontend</title>")
    spa.register_frontend_fallback(app, index)
    return TestClient(app)


@pytest.mark.parametrize("path", ["/", "/learning/course", "/interviews/report/123"])
def test_browser_navigation_receives_frontend(client, path):
    response = client.get(path, headers={"Accept": "text/html,application/xhtml+xml;q=0.9"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


@pytest.mark.parametrize("path", ["/api", "/api/missing", "/API/missing", "/ws", "/ws/missing", "/assets/missing", "/missing.js", "/favicon.ico"])
def test_unknown_api_ws_and_assets_never_receive_frontend(client, path):
    response = client.get(path, headers={"Accept": "text/html"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


@pytest.mark.parametrize("accept", ["*/*", "application/json", "text/html;q=0", "text/html;q=bogus", "text/html;q=2"])
def test_non_navigation_requests_never_receive_frontend(client, accept):
    response = client.get("/learning/course", headers={"Accept": accept})
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT", "PROPFIND"])
def test_unknown_methods_never_receive_frontend(client, method):
    response = client.request(method, "/api/missing", headers={"Accept": "text/html"})
    assert response.status_code == 405
    assert response.headers["content-type"].startswith("application/json")


def test_known_backend_route_and_websocket_keep_precedence(client):
    assert client.get("/api/known", headers={"Accept": "text/html"}).json() == {"actual_api": True}
    with client.websocket_connect("/ws/echo") as ws:
        ws.send_text("routing-check")
        assert ws.receive_text() == "routing-check"


@pytest.fixture
def minimal_source(tmp_path):
    source = tmp_path / "implementation"
    allowlist = json.loads((PACKAGE / "allowlist.json").read_text())
    for group in allowlist["groups"]:
        (source / group["source"]).mkdir(parents=True, exist_ok=True)
    for required in allowlist["required"]:
        path = source / required
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}" if path.suffix == ".json" else "# runtime file\n")
    for required in allowlist["required_directories"]:
        path = source / required / "asset.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
    dist = source / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Frontend</title>")
    return source


def test_stage_excludes_private_paths_and_renders_same_dependency_pins(minimal_source, tmp_path):
    (minimal_source / ".env").write_text("PRIVATE=value")
    (minimal_source / "backend" / "private.sqlite").write_text("private data")
    tests = minimal_source / "backend" / "tests"
    tests.mkdir()
    (tests / "test_private.py").write_text("# excluded")
    output = tmp_path / "upload"
    result = packaging.stage(minimal_source, output, tmp_path / "manifest.json")
    assert result["file_count"] == len(list(path for path in output.rglob("*") if path.is_file()))
    assert not any("private" in item["path"] or ".env" in item["path"] for item in result["files"])
    dependencies = tomllib.loads((output / "pyproject.toml").read_text())["project"]["dependencies"]
    requirements = [line for line in (output / "requirements.txt").read_text().splitlines() if line and not line.startswith("#")]
    assert requirements == dependencies
    assert "hypothesis==6.170.15" in dependencies
    assert not any(item.startswith("pytest") for item in dependencies)
    assert (output / "frontend-index.html").read_bytes() == (output / "public" / "index.html").read_bytes()


@pytest.mark.parametrize("asset", ["api/data.json", ".env", "assets/source.map"])
def test_stage_rejects_private_or_namespace_shadowing_frontend_assets(minimal_source, tmp_path, asset):
    path = minimal_source / "frontend" / "dist" / asset
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("private")
    with pytest.raises(ValueError):
        packaging.stage(minimal_source, tmp_path / "upload", tmp_path / "manifest.json")
    assert not (tmp_path / "upload").exists()


def test_stage_rejects_linked_runtime_source(minimal_source, tmp_path):
    target = minimal_source / "backend" / "app" / "linked.py"
    target.symlink_to(minimal_source / "backend" / "app" / "main.py")
    with pytest.raises(ValueError, match="Linked runtime file"):
        packaging.stage(minimal_source, tmp_path / "upload", tmp_path / "manifest.json")


def test_stage_refuses_to_overwrite_existing_upload(minimal_source, tmp_path):
    output = tmp_path / "upload"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("keep")
    with pytest.raises(ValueError, match="overwrite"):
        packaging.stage(minimal_source, output, tmp_path / "manifest.json")
    assert marker.read_text() == "keep"


def test_stage_rejects_runtime_inventory_added_during_copy(minimal_source, tmp_path, monkeypatch):
    original_copy = packaging.shutil.copyfile

    def concurrent_copy(source, destination):
        result = original_copy(source, destination)
        (minimal_source / "backend" / "app" / "new_runtime.py").write_text("# concurrent change\n")
        return result

    monkeypatch.setattr(packaging.shutil, "copyfile", concurrent_copy)
    with pytest.raises(ValueError, match="inventory changed"):
        packaging.stage(minimal_source, tmp_path / "upload", tmp_path / "manifest.json")
    assert not (tmp_path / "upload").exists()
