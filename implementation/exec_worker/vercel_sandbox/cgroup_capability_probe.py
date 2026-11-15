"""Fixed read-only operator probe. Never evaluates learner source or mutates cgroups."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re

MAX_READ = 65536
MAX_CHILDREN = 16
MAX_SCAN = 128
CONTROLLERS = frozenset({"cpu", "memory", "pids", "io", "cpuset", "rdma", "hugetlb", "misc", "dmem"})


def _read(path: Path) -> tuple[str, bool]:
    with path.open("rb") as handle:
        raw = handle.read(MAX_READ + 1)
    return raw[:MAX_READ].decode("ascii", errors="replace"), len(raw) <= MAX_READ


def _error(error: OSError) -> dict:
    number = error.errno
    return {"error_type": "OSError", "errno": number if type(number) is int and 0 < number < 4096 else None}


def _path(value: str) -> str | None:
    if len(value) <= 512 and re.fullmatch(r"/[A-Za-z0-9_./:@-]*", value):
        return value
    return None


def _group(path: Path) -> dict:
    result = {}
    for field in ("cgroup.controllers", "cgroup.subtree_control"):
        try:
            raw, complete = _read(path / field)
            result[field] = sorted(set(raw.split()) & CONTROLLERS)
            result[field + "_complete"] = complete
        except OSError as error:
            result[field] = _error(error)
    try:
        raw, complete = _read(path / "cgroup.type")
        kind = raw.strip()
        result["cgroup.type"] = kind if complete and kind in {"domain", "domain threaded", "threaded", "domain invalid"} else None
    except OSError as error:
        result["cgroup.type"] = _error(error)
    try:
        raw, complete = _read(path / "cgroup.procs")
        pids = raw.split()
        result["direct_process_count"] = len(pids)
        result["process_count_complete"] = complete
        result["contains_probe_process"] = str(os.getpid()) in pids
    except OSError as error:
        result["processes"] = _error(error)
    try:
        raw, complete = _read(path / "cgroup.events")
        events = {}
        for line in raw.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0] in {"populated", "frozen"} and parts[1] in {"0", "1"}:
                events[parts[0]] = int(parts[1])
        result["events"], result["events_complete"] = events, complete
    except OSError as error:
        result["events"] = _error(error)
    return result


def probe(cgroup_root: Path = Path("/sys/fs/cgroup"), proc_root: Path = Path("/proc")) -> dict:
    result = {"schema": "viva-cgroup-capability-v1", "learner_executed": False,
              "cgroup_mutations": False, "root": _group(cgroup_root), "children": []}
    try:
        raw, complete = _read(proc_root / "self" / "cgroup")
        result["membership_complete"] = complete
        result["unified_membership"] = next((_path(line[3:]) for line in raw.splitlines() if line.startswith("0::")), None)
    except OSError as error:
        result["membership"] = _error(error)
    try:
        raw, complete = _read(proc_root / "self" / "mountinfo")
        mounts = []
        for line in raw.splitlines():
            fields = line.split()
            if "-" not in fields:
                continue
            split = fields.index("-")
            if len(fields) > split + 3 and split >= 6 and fields[split + 1] == "cgroup2":
                mounts.append({"root": _path(fields[3]), "mountpoint": _path(fields[4]),
                               "read_only": "ro" in fields[5].split(",")})
                if len(mounts) == 4:
                    break
        result["cgroup2_mounts"], result["mountinfo_complete"] = mounts, complete
    except OSError as error:
        result["mountinfo"] = _error(error)
    result["same_namespace_as_pid1"] = {}
    for kind in ("cgroup", "mnt", "pid", "user"):
        try:
            result["same_namespace_as_pid1"][kind] = (os.readlink(proc_root / "self" / "ns" / kind)
                == os.readlink(proc_root / "1" / "ns" / kind))
        except OSError as error:
            result["same_namespace_as_pid1"][kind] = _error(error)
    try:
        truncated = False
        with os.scandir(cgroup_root) as entries:
            for index, entry in enumerate(entries):
                if index >= MAX_SCAN:
                    truncated = True
                    break
                if not entry.is_dir(follow_symlinks=False):
                    continue
                if len(result["children"]) >= MAX_CHILDREN:
                    truncated = True
                    break
                name = entry.name
                if len(name) <= 128 and re.fullmatch(r"[A-Za-z0-9_.:@-]+", name):
                    result["children"].append({"name": name, "group": _group(Path(entry.path))})
        result["children_scan_truncated"] = truncated
    except OSError as error:
        result["children_scan"] = _error(error)
    return result


def main():
    wire = json.dumps(probe(), separators=(",", ":")).encode()
    if len(wire) > 32768:
        wire = b'{"schema":"viva-cgroup-capability-v1","learner_executed":false,"cgroup_mutations":false,"output_exceeded":true}'
    print(wire.decode())


if __name__ == "__main__":
    main()
