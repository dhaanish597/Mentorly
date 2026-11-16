"""The operator capability probe only reads bounded metadata from fixed roots."""
from __future__ import annotations

import json
import os

from exec_worker.vercel_sandbox.cgroup_capability_probe import MAX_CHILDREN, probe


def group(path, processes=""):
    path.mkdir(exist_ok=True)
    (path / "cgroup.controllers").write_text("cpu memory pids")
    (path / "cgroup.subtree_control").write_text("")
    (path / "cgroup.type").write_text("domain")
    (path / "cgroup.procs").write_text(processes)
    (path / "cgroup.events").write_text("populated 1\nfrozen 0\n")


def test_populated_delegated_mount_is_observable_without_changes(tmp_path):
    root, proc = tmp_path / "cgroup", tmp_path / "proc"
    group(root, f"{os.getpid()}\n123\n")
    group(root / "provider.scope", "123\n")
    (proc / "self").mkdir(parents=True)
    (proc / "self" / "cgroup").write_text("0::/provider/delegated\n")
    (proc / "self" / "mountinfo").write_text("30 21 0:29 /provider/delegated /sys/fs/cgroup rw,nosuid,nodev - cgroup2 cgroup rw\n")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    result = probe(root, proc)
    assert result["root"]["direct_process_count"] == 2
    assert result["root"]["contains_probe_process"] is True
    assert result["root"]["cgroup.subtree_control"] == []
    assert result["root"]["cgroup.controllers"] == ["cpu", "memory", "pids"]
    assert result["unified_membership"] == "/provider/delegated"
    assert result["cgroup2_mounts"] == [{"root": "/provider/delegated", "mountpoint": "/sys/fs/cgroup", "read_only": False}]
    assert result["learner_executed"] is False and result["cgroup_mutations"] is False
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}


def test_child_enumeration_is_bounded_and_ignores_symlinks(tmp_path):
    root, proc = tmp_path / "cgroup", tmp_path / "proc"
    group(root)
    for index in range(MAX_CHILDREN + 2):
        group(root / f"child-{index}")
    (root / "symlink").symlink_to(tmp_path, target_is_directory=True)
    result = probe(root, proc)
    assert len(result["children"]) == MAX_CHILDREN
    assert result["children_scan_truncated"] is True
    assert all(child["name"] != "symlink" for child in result["children"])
    assert len(json.dumps(result)) < 32768
