"""Local launch environment rejects accidental credential inheritance."""

import sys
from types import SimpleNamespace

import pytest
from scripts.start_local import IMPLEMENTATION, main, preview_environment


@pytest.mark.parametrize(
    "arguments, reload_enabled", [([], True), (["--no-reload"], False)]
)
def test_local_backend_reloads_current_routes_without_changing_database(
    monkeypatch, tmp_path, arguments, reload_enabled
):
    env_file = tmp_path / "private.env"
    env_file.write_text("VCC_ENV=development\n")
    database = str(tmp_path / "existing.db")
    monkeypatch.setenv("VCC_DATABASE_PATH", database)
    monkeypatch.setenv("VCC_ENV_FILE", "unused-before-test")
    monkeypatch.setattr("scripts.start_local.os.chdir", lambda path: None)
    monkeypatch.setattr(sys, "path", list(sys.path))
    calls = []
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        SimpleNamespace(run=lambda *args, **kwargs: calls.append((args, kwargs))),
    )
    assert main(["--env-file", str(env_file), "--port", "8020", *arguments]) == 0
    import os

    assert os.environ["VCC_DATABASE_PATH"] == database
    assert os.environ["VCC_ENV_FILE"] == str(env_file)
    args, options = calls[0]
    assert args == ("backend.app.main:app",)
    assert options["reload"] is reload_enabled
    assert options["host"] == "127.0.0.1"
    assert options["proxy_headers"] is False
    assert options["reload_dirs"] == (
        [str(IMPLEMENTATION / "backend" / "app")] if reload_enabled else None
    )


@pytest.mark.parametrize(
    "arguments", [["--port", "1"], ["--env-file", "/unavailable-test-environment-file"]]
)
def test_invalid_startup_arguments_fail_before_launch(arguments):
    with pytest.raises(SystemExit) as failure:
        main(arguments)
    assert failure.value.code == 2


def test_preview_removes_aliases_file_opt_in_and_private_secrets():
    source = {
        "VCC_GNANI_API_KEY": "test-only",
        "GNANI_API_KEY": "test-only",
        "GNANI_API_KEY_ID": "test-only",
        "VCC_ENV_FILE": "private.env",
        "VCC_OPERATIONS_TOKEN": "test-only",
        "VCC_INTERNAL_WORKER_SECRET": "test-only",
        "VCC_ALLOW_PUBLIC_CUSTOM_CODE": "true",
        "PATH": "safe-path",
    }
    result = preview_environment(source)
    assert result["VCC_GNANI_API_KEY"] == ""
    assert "GNANI_API_KEY" not in result and "VCC_ENV_FILE" not in result
    assert result["VCC_OPERATIONS_TOKEN"] == ""
    assert result["VCC_ALLOW_PUBLIC_CUSTOM_CODE"] == "false"
    assert result["VCC_LLM_PROVIDER"] == "deterministic"
    assert result["PATH"] == "safe-path"
    assert source["VCC_GNANI_API_KEY"] == "test-only"
