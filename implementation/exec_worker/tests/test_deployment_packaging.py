"""Read-only packaging checks and mocked preflight tests; no Docker daemon needed."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest import mock

import pytest

from exec_worker.worker_app import sandbox_runner

ROOT = Path(__file__).resolve().parents[2]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_worker_image_contains_verifier_dependencies_and_runtime_path() -> None:
    dockerfile = text("exec_worker/Dockerfile.worker")
    for package in ("models", "exercises", "verification"):
        assert f"COPY backend/app/{package} /workspace/backend/app/{package}" in dockerfile
        assert (ROOT / "backend/app" / package).is_dir()
    assert "COPY exec_worker/worker_app" in dockerfile
    assert "COPY exec_worker/runner" in dockerfile
    assert "/opt/vcc/gvisor" in dockerfile
    assert "COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker" in dockerfile
    assert "docker.io" not in dockerfile
    assert "COPY exec_worker /" not in dockerfile


def test_compose_uses_identical_absolute_ipc_paths_and_readonly_evidence() -> None:
    compose = text("docker-compose.yml")
    assert "VCC_IPC_PARENT_DIR: ${VCC_IPC_PARENT_DIR:-/var/lib/vcc/ipc}" in compose
    assert "source: ${VCC_IPC_PARENT_DIR:-/var/lib/vcc/ipc}" in compose
    assert "target: ${VCC_IPC_PARENT_DIR:-/var/lib/vcc/ipc}" in compose
    assert "source: /opt/vcc/gvisor" in compose
    assert "target: /opt/vcc/gvisor" in compose
    assert "target: /etc/vcc/acceptance" in compose
    assert compose.count("read_only: true") >= 3
    assert "create_host_path: false" in compose
    assert "VCC_ALLOW_PUBLIC_CUSTOM_CODE: ${VCC_ALLOW_PUBLIC_CUSTOM_CODE:-false}" in compose
    assert "127.0.0.1:" in compose
    assert "VCC_ISOLATION_ACCEPTANCE_FILE" in compose


def test_coordinator_image_copies_only_runtime_sources() -> None:
    dockerfile = text("backend/Dockerfile.coordinator")
    assert "COPY backend/app /app/backend/app" in dockerfile
    assert "COPY backend /app/backend" not in dockerfile
    assert "USER 10001:10001" in dockerfile


def test_frontend_build_and_proxy_are_same_origin_and_blob_compatible() -> None:
    dockerfile = text("deployment/frontend/Dockerfile")
    nginx = text("deployment/frontend/nginx.conf")
    assert "npm ci" in dockerfile and "npm run build" in dockerfile
    assert "COPY frontend/src" in dockerfile
    assert "location /api/" in nginx
    assert "proxy_pass http://coordinator:8000;" in nginx
    assert "proxy_set_header Upgrade $http_upgrade;" in nginx
    assert "proxy_buffering off;" in nginx
    assert "worker-src 'self' blob:" in nginx
    assert "media-src 'self' blob:" in nginx
    assert "object-src 'none'" in nginx
    assert "connect-src 'self'" in nginx
    assert "https://" not in nginx


def test_example_keeps_public_execution_disabled_and_credentials_blank() -> None:
    template = text(".env.example")
    assert "VCC_ALLOW_PUBLIC_CUSTOM_CODE=false" in template
    assert "VCC_IPC_PARENT_DIR=/var/lib/vcc/ipc" in template
    for key in ("VCC_INTERNAL_WORKER_SECRET", "VCC_GNANI_API_KEY", "VCC_GROQ_API_KEY"):
        assert f"\n{key}=\n" in template


def test_ipc_parent_rejects_relative_missing_world_accessible_and_symlink(tmp_path: Path) -> None:
    validate = sandbox_runner.validate_ipc_parent_dir
    with pytest.raises(ValueError):
        validate(Path("relative"))
    with pytest.raises(ValueError):
        validate(tmp_path / "missing")
    private = tmp_path / "ipc"
    private.mkdir(mode=0o700)
    assert validate(private) == private
    private.chmod(0o755)
    with pytest.raises(ValueError):
        validate(private)
    private.chmod(0o700)
    link = tmp_path / "link"
    link.symlink_to(private, target_is_directory=True)
    with pytest.raises(ValueError):
        validate(link)


def test_runner_reads_ipc_path_from_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VCC_IPC_PARENT_DIR", str(tmp_path))
    assert sandbox_runner.GVisorSandboxRunner()._ipc_parent_dir == tmp_path


def test_acceptance_marker_alone_cannot_enable_execution() -> None:
    with mock.patch.object(sandbox_runner, "_read_acceptance_evidence", return_value={"passed": True}):
        reasons = sandbox_runner.acceptance_failure_reasons(
            "vcc-runner:phase1", "runsc version test", lambda *_: subprocess.CompletedProcess([], 1, "", ""), 1.0
        )
    assert reasons


def test_acceptance_binds_image_runtime_binary_and_daemon(tmp_path: Path) -> None:
    binary = tmp_path / "runsc"
    binary.write_bytes(b"verified-runtime")
    runtime = {"path": str(binary), "runtimeArgs": []}
    evidence = {
        "passed": True,
        "runner_image_id": "sha256:" + "a" * 64,
        "runsc_sha256": sandbox_runner.hashlib.sha256(binary.read_bytes()).hexdigest(),
        "runtime_bundle_sha256": sandbox_runner.runtime_bundle_sha256(binary),
        "runtime_version": "runsc version test",
        "docker_daemon_id": "accepted-host",
        "runtime_config": runtime,
    }

    def probe(cmd: list[str], _: float) -> subprocess.CompletedProcess[str]:
        output = evidence["runner_image_id"] if cmd[1:3] == ["image", "inspect"] else json.dumps(
            {"ID": "accepted-host", "OSType": "linux", "Runtimes": {"runsc": runtime}}
        )
        return subprocess.CompletedProcess(cmd, 0, output, "")

    with mock.patch.object(sandbox_runner, "_read_acceptance_evidence", return_value=evidence), mock.patch.object(
        sandbox_runner.shutil, "which", return_value=str(binary)
    ):
        assert sandbox_runner.acceptance_failure_reasons("vcc-runner:phase1", "runsc version test", probe, 1.0) == ()
        for field, stale in (
            ("runner_image_id", "sha256:" + "b" * 64),
            ("docker_daemon_id", "other-host"),
            ("runtime_config", {"path": "/usr/bin/runc"}),
            ("runtime_bundle_sha256", "b" * 64),
        ):
            with mock.patch.object(sandbox_runner, "_read_acceptance_evidence", return_value={**evidence, field: stale}):
                assert sandbox_runner.acceptance_failure_reasons("vcc-runner:phase1", "runsc version test", probe, 1.0)
        assert sandbox_runner.acceptance_failure_reasons("vcc-runner:phase1", "different", probe, 1.0)
        binary.write_bytes(b"changed-runtime")
        assert sandbox_runner.acceptance_failure_reasons("vcc-runner:phase1", "runsc version test", probe, 1.0)


def test_marker_requires_readonly_mount_and_genuine_provenance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    marker = tmp_path / "accepted.json"
    marker.write_text(json.dumps({"passed": True}), encoding="utf-8")
    monkeypatch.setenv("VCC_ISOLATION_ACCEPTANCE_FILE", str(marker))
    with mock.patch.object(sandbox_runner.os, "statvfs", return_value=SimpleNamespace(f_flag=0)):
        with pytest.raises(ValueError, match="read-only"):
            sandbox_runner._read_acceptance_evidence()
    with mock.patch.object(sandbox_runner.os, "statvfs", return_value=SimpleNamespace(f_flag=sandbox_runner.os.ST_RDONLY)):
        with pytest.raises(ValueError, match="provenance"):
            sandbox_runner._read_acceptance_evidence()


def test_public_optin_degrades_preflight_without_accepted_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VCC_ALLOW_PUBLIC_CUSTOM_CODE", "true")
    monkeypatch.delenv("VCC_IPC_PARENT_DIR", raising=False)
    monkeypatch.delenv("VCC_ENV", raising=False)
    preflight = sandbox_runner.SandboxRuntimePreflight(
        ready=True, platform_system="Linux", docker_available=True,
        runsc_registered=True, runsc_binary_available=True, runner_image_present=True,
        runner_image="vcc-runner:phase1", runtime_version="runsc version test",
    )
    runner = sandbox_runner.GVisorSandboxRunner(preflight_fn=lambda: preflight)
    with mock.patch.object(sandbox_runner, "acceptance_failure_reasons", return_value=("not accepted",)):
        result = runner.check_preflight()
    assert not result.ready and not result.acceptance_verified
    assert "not accepted" in result.failure_reasons


def test_production_refuses_private_tmp_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VCC_ENV", "production")
    monkeypatch.setenv("VCC_ALLOW_PUBLIC_CUSTOM_CODE", "false")
    monkeypatch.delenv("VCC_IPC_PARENT_DIR", raising=False)
    preflight = sandbox_runner.SandboxRuntimePreflight(
        ready=True, platform_system="Linux", docker_available=True,
        runsc_registered=True, runsc_binary_available=True, runner_image_present=True,
        runner_image="vcc-runner:phase1",
    )
    result = sandbox_runner.GVisorSandboxRunner(preflight_fn=lambda: preflight).check_preflight()
    assert not result.ready
    assert any("shared VCC_IPC_PARENT_DIR" in reason for reason in result.failure_reasons)


def test_runtime_bundle_binds_sidecars_and_rejects_symlink(tmp_path: Path) -> None:
    binary = tmp_path / "runsc"
    binary.write_bytes(b"runtime")
    sidecars = tmp_path / "gvisor-bin"
    sidecars.mkdir()
    sentry = sidecars / "sentry"
    sentry.write_bytes(b"accepted")
    original = sandbox_runner.runtime_bundle_sha256(binary)
    sentry.write_bytes(b"different")
    assert sandbox_runner.runtime_bundle_sha256(binary) != original
    sentry.unlink()
    sidecars.rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sidecars.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic link"):
        sandbox_runner.runtime_bundle_sha256(binary)
