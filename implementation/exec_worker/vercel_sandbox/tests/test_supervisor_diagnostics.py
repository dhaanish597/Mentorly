"""Safe setup diagnostics preserve rejection and independently verify cleanup."""
from __future__ import annotations

import errno
import io
import json
from pathlib import Path
from types import SimpleNamespace

from backend.app.models.domain import ExecutionBudgetConfig
from exec_worker.vercel_sandbox import supervisor


def test_setup_failure_keeps_stage_and_verified_cleanup(tmp_path, monkeypatch):
    group_root = tmp_path / "cgroup"
    group_root.mkdir()
    (group_root / "cgroup.controllers").write_text("cpu memory pids")
    root = tmp_path / "learner_root"
    def make_root(**kwargs):
        root.mkdir()
        return str(root)
    original = Path.write_text
    def write(path, *args, **kwargs):
        if path.name == "cgroup.subtree_control":
            raise OSError(errno.EROFS, "private environment and source must never leave")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(supervisor, "CGROUP_ROOT", group_root)
    monkeypatch.setattr(supervisor, "_runtime", lambda: {})
    monkeypatch.setattr(supervisor.tempfile, "mkdtemp", make_root)
    monkeypatch.setattr(Path, "write_text", write)
    result = supervisor.supervise({"budget": ExecutionBudgetConfig().model_dump()}, tmp_path / "assets")
    assert result["reason"] == "setup_failure"
    assert result["failure"] == {"phase": "cgroup_enable", "error_type": "OSError", "errno": errno.EROFS}
    assert result["cleanup_verified"] is True
    assert result["cleanup_failures"] == []
    assert not root.exists()
    assert "private environment" not in json.dumps(result)


def test_cleanup_failure_keeps_original_setup_failure(tmp_path, monkeypatch):
    group_root = tmp_path / "cgroup"
    group_root.mkdir()
    (group_root / "cgroup.controllers").write_text("cpu memory pids")
    root = tmp_path / "learner_root"
    def make_root(**kwargs):
        root.mkdir()
        return str(root)
    original = Path.write_text
    def write(path, *args, **kwargs):
        if path.name == "memory.max":
            raise PermissionError(errno.EPERM, "private setup error")
        return original(path, *args, **kwargs)
    def cannot_kill(path):
        raise OSError(errno.EIO, "private cleanup error")
    monkeypatch.setattr(supervisor, "CGROUP_ROOT", group_root)
    monkeypatch.setattr(supervisor, "_runtime", lambda: {})
    monkeypatch.setattr(supervisor.tempfile, "mkdtemp", make_root)
    monkeypatch.setattr(Path, "write_text", write)
    monkeypatch.setattr(supervisor, "_kill_and_empty", cannot_kill)
    result = supervisor.supervise({"budget": ExecutionBudgetConfig().model_dump()}, tmp_path / "assets")
    assert result["failure"] == {"phase": "cgroup_limits", "error_type": "PermissionError", "errno": errno.EPERM}
    assert result["cleanup_failures"] == [{"phase": "cleanup_cgroup_kill", "error_type": "OSError", "errno": errno.EIO}]
    assert result["cleanup_verified"] is False
    assert not root.exists()
    assert "private" not in json.dumps(result)


def test_entry_failure_emits_only_safe_diagnostic(monkeypatch):
    output = io.BytesIO()
    monkeypatch.setattr(supervisor.sys, "argv", ["supervisor.py"])
    monkeypatch.setattr(supervisor.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"{}")))
    monkeypatch.setattr(supervisor.sys, "stdout", SimpleNamespace(buffer=output))
    monkeypatch.setattr(supervisor.os, "geteuid", lambda: 0)
    def unavailable(*args):
        raise OSError(errno.EIO, "secret-token/source/environment")
    monkeypatch.setattr(supervisor, "supervise", unavailable)
    supervisor.main()
    result = json.loads(output.getvalue())
    assert result["cleanup_verified"] is False
    assert result["failure"] == {"phase": "supervision", "error_type": "OSError", "errno": errno.EIO}
    assert b"secret-token" not in output.getvalue()
