"""Offline check-runner regressions; never execute learner source or live APIs."""
from __future__ import annotations

import ast
import json
import hashlib
import os
import re
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import run_all_checks as full
from scripts import run_phase2_checks as phase

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("relative", ["private.wav", "capture.webm", "data/state.sqlite", "runtime/session.db-wal", "keys/private.pem", "coverage/index.html", ".hypothesis/examples/case"])
def test_source_snapshot_excludes_private_and_runtime_artifacts(tmp_path, relative):
    file = tmp_path / relative
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(b"private-or-runtime-data")
    assert phase.is_approved_source_file(file, tmp_path) is False


def test_source_snapshot_rejects_sqlite_backup_with_misleading_extension(tmp_path):
    file = tmp_path / "backup.json"
    file.write_bytes(b"SQLite format 3\x00" + b"private data")
    assert phase.is_approved_source_file(file, tmp_path) is False


def test_coordinator_package_excludes_bytecode_namespaces():
    import fnmatch
    import tomllib
    config = tomllib.loads((ROOT / 'backend' / 'pyproject.toml').read_text())
    excluded = config['tool']['setuptools']['packages']['find']['exclude']
    for package in ('backend.app.__pycache__', 'backend.app.speech.__pycache__'):
        assert any(fnmatch.fnmatch(package, pattern) for pattern in excluded)


def test_frontend_image_copies_external_branding_input():
    dockerfile = (ROOT / "deployment/frontend/Dockerfile").read_text()
    assert "COPY config/branding.json /config/branding.json" in dockerfile


@pytest.mark.parametrize("output", ["", "no tests ran in 0.01s", "3 skipped in 0.01s", "Tests  0 passed"])
def test_successful_exit_without_executed_tests_fails(monkeypatch, output: str) -> None:
    monkeypatch.setattr(phase.subprocess, "run", Mock(return_value=subprocess.CompletedProcess([], 0, output, "")))
    result = phase.run_command("tests", ["python", "-m", "pytest", "tests"], ROOT)
    assert result["status"] == "FAIL"
    assert result["exit_code"] != 0


@pytest.mark.parametrize("command,output,count", [
    (["python", "-m", "pytest", "tests"], "=== 12 passed, 3 skipped in 1s ===", 12),
    (["npm", "test"], "Test Files  2 passed (2)\nTests  7 passed (7)", 7),
])
def test_nonempty_test_summaries_record_executed_counts(monkeypatch, command, output, count) -> None:
    monkeypatch.setattr(phase.subprocess, "run", Mock(return_value=subprocess.CompletedProcess([], 0, output, "")))
    result = phase.run_command("tests", command, ROOT)
    assert result["status"] == "PASS"
    assert result["tests_passed"] == count


@pytest.mark.parametrize("code,output,status", [
    (1, "real failure", "FAIL"),
    (2, '{"status": "BLOCKED_EXTERNAL", "reason": "no runtime"}', "BLOCKED_EXTERNAL"),
    (0, '{"status": "BLOCKED_EXTERNAL"}', "BLOCKED_EXTERNAL"),
    (1, '{"status": "BLOCKED_EXTERNAL"}', "FAIL"),
    (0, "BLOCKED_EXTERNAL in a log, not a structured result", "PASS"),
])
def test_external_blocked_status_requires_structured_evidence(monkeypatch, code, output, status) -> None:
    monkeypatch.setattr(phase.subprocess, "run", Mock(return_value=subprocess.CompletedProcess([], code, output, "")))
    result = phase.run_command("live", ["python", "smoke.py"], ROOT, required=False, gate_category="LIVE_EXTERNAL_PROVIDER")
    assert result["status"] == status


@pytest.mark.parametrize("error", [FileNotFoundError("npm missing"), PermissionError("denied"), subprocess.TimeoutExpired(["npm"], 600, output=b"partial log")])
def test_launch_errors_become_recorded_failures(monkeypatch, error) -> None:
    monkeypatch.setattr(phase.subprocess, "run", Mock(side_effect=error))
    result = phase.run_command("broken", ["npm", "test"], ROOT)
    assert result["status"] == "FAIL"
    assert result["stderr"]
    if isinstance(error, subprocess.TimeoutExpired):
        assert "partial log" in result["stdout"]


def test_captured_output_is_complete_but_secrets_are_redacted(monkeypatch, tmp_path) -> None:
    secret = "runner-test-private-value"
    monkeypatch.setenv("VCC_GNANI_API_KEY", secret)
    monkeypatch.setattr(phase.subprocess, "run", Mock(return_value=subprocess.CompletedProcess([], 1, f"stdout {secret} café", f"stderr {secret}")))
    result = phase.run_command("failure", ["tool"], ROOT)
    phase._persist_outputs(tmp_path, [result])
    saved = json.loads((tmp_path / "check_results.json").read_text())
    assert "café" in saved[0]["stdout"]
    assert saved[0]["stderr"] == "stderr [REDACTED]"
    assert secret not in (tmp_path / "TEST_LOGS.txt").read_text()


def test_offline_commands_cannot_inherit_explicit_live_secret_file(monkeypatch) -> None:
    monkeypatch.setenv("VCC_ENV_FILE", "/private/live-config.env")
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "1 passed in 0.01s", ""))
    monkeypatch.setattr(phase.subprocess, "run", run)
    phase.run_command("offline", ["python", "-m", "pytest", "tests"], ROOT)
    assert "VCC_ENV_FILE" not in run.call_args.kwargs["env"]


def test_internal_failure_is_recorded_instead_of_aborting() -> None:
    def broken() -> tuple[int, str, str]:
        raise FileNotFoundError("required runner module absent")
    result = phase.run_internal_check("runner_image_isolated_import", broken, ROOT)
    assert result["status"] == "FAIL"
    assert "FileNotFoundError" in result["stderr"]


def test_notebook_gate_checks_syntax_without_executing_cells(tmp_path) -> None:
    cloud = tmp_path / "cloud"
    cloud.mkdir()
    notebook = {"nbformat": 4, "cells": [{"cell_type": "code", "source": ["raise AssertionError('never execute')\n"]}]}
    for name in ("FULL_PROJECT_COLAB.ipynb", "PHASE_2_COLAB.ipynb"):
        (cloud / name).write_text(json.dumps(notebook))
    assert phase.validate_notebooks(tmp_path)[0] == 0
    notebook["cells"][0]["source"] = ["if broken syntax\n"]
    (cloud / "FULL_PROJECT_COLAB.ipynb").write_text(json.dumps(notebook))
    assert phase.validate_notebooks(tmp_path)[0] != 0


def _pass_result(name: str, command=None, cwd=ROOT, **kwargs) -> dict:
    return dict(name=name, command=command or ["internal:test"], cwd=str(cwd), exit_code=0, duration_s=0,
                required=kwargs.get("required", True), gate_category=kwargs.get("gate_category", "OFFLINE_REQUIRED"),
                status="PASS", stdout="full command output", stderr="")


def test_phase_runner_continues_after_internal_failure_and_reports_omitted_live_gate(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(phase, "run_command", _pass_result)
    monkeypatch.setattr(phase, "run_archive_sentinel_self_test", Mock(side_effect=OSError("sentinel failed")))
    monkeypatch.setattr(phase, "run_isolated_runner_copy_check", Mock(return_value=(0, "import-only", "")))
    from exec_worker.worker_app import sandbox_runner
    monkeypatch.setattr(sandbox_runner, "check_runtime_preflight", Mock(return_value=SimpleNamespace(ready=False, summary="gVisor unavailable")))
    code, results = phase.execute_all_checks(ROOT, tmp_path)
    assert code == 1
    indexed = {r["name"]: r for r in results}
    assert indexed["archive_sentinel_self_test"]["status"] == "FAIL"
    assert indexed["frontend_build"]["status"] == "PASS"
    assert indexed["live_gnani_smoke"]["status"] == "BLOCKED_EXTERNAL"
    assert indexed["live_gvisor_isolation_acceptance"]["status"] == "BLOCKED_EXTERNAL"
    assert indexed["runner_image_isolated_import"]["gate_category"] == "OFFLINE_IMPORT_ONLY"
    assert "-m" not in indexed["runner_image_isolated_import"]["command"]
    assert "notebook_syntax" in indexed


def test_preflight_exception_is_failure_not_external_block(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(phase, "run_command", _pass_result)
    monkeypatch.setattr(phase, "run_archive_sentinel_self_test", Mock(return_value=(0, "", "")))
    monkeypatch.setattr(phase, "run_isolated_runner_copy_check", Mock(return_value=(0, "", "")))
    from exec_worker.worker_app import sandbox_runner
    monkeypatch.setattr(sandbox_runner, "check_runtime_preflight", Mock(side_effect=RuntimeError("bug in preflight")))
    code, results = phase.execute_all_checks(ROOT, tmp_path)
    assert code == 1
    assert results[-1]["status"] == "FAIL"
    assert "RuntimeError" in results[-1]["stderr"]


def test_full_runner_requires_named_integration_suite_and_persists_all_output(monkeypatch, tmp_path) -> None:
    calls = []
    monkeypatch.setattr(full, "execute_all_checks", Mock(return_value=(0, [])))
    def record(name, command, cwd, **kwargs):
        calls.append((name, command, kwargs))
        return _pass_result(name, command, cwd, **kwargs)
    monkeypatch.setattr(full, "run_command", record)
    assert full.main(["--repo-root", str(ROOT), "--output-dir", str(tmp_path)]) == 0
    assert any("backend/tests/integration/test_p3_to_p7_integration.py" in cmd for _, cmd, _ in calls)
    saved = json.loads((tmp_path / "full_check_results.json").read_text())
    assert all(r["stdout"] == "full command output" and "command" in r and "stderr" in r for r in saved)
    evaluation = next(options for name, _, options in calls if name == "p8_code_eval_12_buggy_6_correct")
    assert evaluation["gate_category"] == "LIVE_EXTERNAL_ISOLATION"
    assert (tmp_path / "TEST_LOGS.txt").read_text().count("full command output") == len(saved)


@pytest.mark.parametrize("filename", ["FULL_PROJECT_COLAB.ipynb", "PHASE_2_COLAB.ipynb"])
def test_notebook_execution_requires_review_and_isolated_interpreter(filename: str) -> None:
    notebook = json.loads((ROOT / "cloud" / filename).read_text())
    source = "\n".join("".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code")
    ast.parse(source)
    assert "VCC_REVIEWED_MANIFEST_FILE" in source
    assert "verify_reviewed_tree(TARGET_REPO)" in source
    assert "'-I'" in source
    assert "--ignore-scripts" in source
    assert "--require-hashes" in source
    assert "--only-binary=:all:" in source
    assert "BLOCKED_EXTERNAL" in source
    assert "extractall(" not in source and "os.chdir(" not in source
    assert "'-c'" not in source  # Never execute learner text via a host interpreter.
    runner = "run_all_checks.py" if filename.startswith("FULL") else "run_phase2_checks.py"
    assert runner in source


@pytest.mark.parametrize("name", ["bundle.tar.gz", "nested.zip", "private.key", ".env", ".env.production"])
def test_packaging_excludes_archives_and_secrets(tmp_path, name: str) -> None:
    path = tmp_path / name
    path.write_text("untrusted data")
    assert not phase.is_approved_source_file(path, tmp_path)


def test_packaging_excludes_nested_venvs_and_directory_symlinks(tmp_path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    (external / "source.py").write_text("trusted = True")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "linked").symlink_to(external, target_is_directory=True)
    (repo / ".venv-takeover").mkdir()
    (repo / ".venv-takeover" / "source.py").write_text("trusted = True")
    assert not phase.is_approved_source_file(repo / "linked" / "source.py", repo)
    assert not phase.is_approved_source_file(repo / ".venv-takeover" / "source.py", repo)


def _notebook_helpers(filename: str) -> dict:
    """Load only reviewed helper definitions, not notebook top-level execution."""
    notebook = json.loads((ROOT / "cloud" / filename).read_text())
    source = "\n".join("".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code")
    tree = ast.parse(source)
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in {"safe_relative_path", "verify_reviewed_tree"}]
    from pathlib import PurePosixPath
    scope = dict(Path=Path, PurePosixPath=PurePosixPath, os=os, json=json, re=re, hashlib=hashlib)
    exec(compile(ast.Module(body=selected, type_ignores=[]), "reviewed-notebook-helpers", "exec"), scope)
    return scope


@pytest.mark.parametrize("filename", ["FULL_PROJECT_COLAB.ipynb", "PHASE_2_COLAB.ipynb"])
@pytest.mark.parametrize("value", ["../escape", "/absolute", "nested/../escape", "folder\\escape", "C:escape", "./alias", "", "newline\nname"])
def test_notebook_paths_reject_traversal_and_ambiguous_names(filename: str, value: str) -> None:
    helpers = _notebook_helpers(filename)
    with pytest.raises(ValueError):
        helpers["safe_relative_path"](value)


@pytest.mark.parametrize("filename", ["FULL_PROJECT_COLAB.ipynb", "PHASE_2_COLAB.ipynb"])
def test_notebook_manifest_blocks_missing_review_and_any_byte_change(monkeypatch, tmp_path, filename: str) -> None:
    helpers = _notebook_helpers(filename)
    staged = tmp_path / "quarantine"
    staged.mkdir()
    source = staged / "reviewed.py"
    source.write_text("# reviewed data only\n")
    monkeypatch.delenv("VCC_REVIEWED_MANIFEST_FILE", raising=False)
    with pytest.raises(RuntimeError, match="BLOCKED_EXTERNAL"):
        helpers["verify_reviewed_tree"](staged)
    manifest = tmp_path / "reviewed_manifest.json"
    manifest.write_text(json.dumps({"reviewed": True, "files": {"reviewed.py": hashlib.sha256(source.read_bytes()).hexdigest()}}))
    monkeypatch.setenv("VCC_REVIEWED_MANIFEST_FILE", str(manifest))
    helpers["verify_reviewed_tree"](staged)
    source.write_text("# altered unreviewed bytes\n")
    with pytest.raises(RuntimeError, match="BLOCKED_EXTERNAL"):
        helpers["verify_reviewed_tree"](staged)


def test_offline_commands_strip_provider_credentials(monkeypatch) -> None:
    monkeypatch.setenv("VCC_GNANI_API_KEY", "private-test-value")
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "ok", ""))
    monkeypatch.setattr(phase.subprocess, "run", run)
    phase.run_command("offline", ["tool"], ROOT)
    credential_is_present = bool(run.call_args.kwargs["env"].get("VCC_GNANI_API_KEY"))
    assert credential_is_present is False


def test_live_provider_is_explicit_and_missing_runtime_does_not_launch_acceptance(monkeypatch, tmp_path) -> None:
    calls = []
    def record(name, command, cwd, **kwargs):
        calls.append((name, command, kwargs))
        return _pass_result(name, command, cwd, **kwargs)
    monkeypatch.setattr(phase, "run_command", record)
    monkeypatch.setattr(phase, "run_archive_sentinel_self_test", Mock(return_value=(0, "", "")))
    monkeypatch.setattr(phase, "run_isolated_runner_copy_check", Mock(return_value=(0, "", "")))
    from exec_worker.worker_app import sandbox_runner
    monkeypatch.setattr(sandbox_runner, "check_runtime_preflight", Mock(return_value=SimpleNamespace(ready=False, summary="no gVisor")))
    phase.execute_all_checks(ROOT, tmp_path, run_live_gnani=True)
    live = next(command for name, command, _ in calls if name == "live_gnani_smoke")
    assert "--live" in live and "--allow-blocked" not in live
    assert not any(name == "live_gvisor_isolation_acceptance" for name, _, _ in calls)


@pytest.mark.parametrize("summary", [{}, {"overall_pass": True}, {"overall_pass": True, "buggy_total": 0, "correct_total": 0}, {"overall_pass": True, "mocked": True, "buggy_total": 12, "correct_total": 6}])
def test_code_eval_cannot_pass_with_empty_or_mocked_summary(monkeypatch, summary: dict) -> None:
    monkeypatch.setattr(phase.subprocess, "run", Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps(summary), "")))
    result = phase.run_command("p8_code_eval_12_buggy_6_correct", ["python", "evaluation/run_code_eval.py"], ROOT, gate_category="LIVE_EXTERNAL_ISOLATION")
    assert result["status"] == "FAIL"


def test_live_isolation_skipped_probes_do_not_pass(monkeypatch) -> None:
    monkeypatch.setattr(phase.subprocess, "run", Mock(return_value=subprocess.CompletedProcess([], 0, "1 passed, 9 skipped", "")))
    result = phase.run_command("isolation", ["python", "-m", "pytest", "exec_worker/tests/test_sandbox_isolation.py"], ROOT, gate_category="LIVE_EXTERNAL_ISOLATION")
    assert result["status"] == "FAIL"
