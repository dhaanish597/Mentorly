"""Trusted microVM supervisor. Learner code runs only after chroot and exec.

This file uses only the standard library and is uploaded separately from the
guest runner. It must run as root outside the learner's namespaces/cgroup.
Failures in setup or cleanup never produce a successful execution result.
"""
from __future__ import annotations

import base64
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import selectors
import shutil
import signal
import subprocess
import sys
import sysconfig
import tempfile
import time

# Uploaded trusted sibling, outside the learner chroot.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from .native_protocol import NativeProtocolError, authenticated_runner_frame
except ImportError:  # Direct isolated script in the disposable VM.
    from native_protocol import NativeProtocolError, authenticated_runner_frame

MAX_INPUT_BYTES = 262144
MAX_WIRE_BYTES = 1048576
SCHEMA = "viva-supervisor-v1"
READY_MARKER = b"VIVA_SUPERVISOR_READY_V1\n"
CGROUP_ROOT = Path("/sys/fs/cgroup")
MS_BIND, MS_REC, MS_PRIVATE = 4096, 16384, 1 << 18
MS_RDONLY, MS_NOSUID, MS_NODEV, MS_NOEXEC, MS_REMOUNT = 1, 2, 4, 8, 32
DIAGNOSTIC_PHASES = frozenset({
    "root_permission", "input_read", "input_parse", "supervision", "runtime_identity",
    "root_create", "cgroup_controllers", "cgroup_enable", "cgroup_create", "cgroup_limits",
    "guest_stage", "native_identity", "payload_stage", "pipes", "child_start", "capture",
    "process_cleanup", "result_authentication", "cleanup_cgroup_kill", "cleanup_wait",
    "cleanup_cgroup_remove", "cleanup_fd_close", "cleanup_root_remove", "cleanup_check",
})
DIAGNOSTIC_ERROR_TYPES = frozenset({
    "OSError", "PermissionError", "FileNotFoundError", "FileExistsError", "NotADirectoryError",
    "IsADirectoryError", "RuntimeError", "ValueError", "TypeError", "KeyError", "JSONDecodeError",
    "TimeoutExpired", "MemoryError", "OverflowError", "KeyboardInterrupt", "SystemExit",
})


def _diagnostic(phase: str, error: BaseException) -> dict:
    """Only fixed stages, error categories and numeric errno leave the supervisor."""
    error_type = type(error).__name__
    number = getattr(error, "errno", None)
    return {"phase": phase if phase in DIAGNOSTIC_PHASES else "supervision",
            "error_type": error_type if error_type in DIAGNOSTIC_ERROR_TYPES else "RuntimeError",
            "errno": number if type(number) is int and 0 < number < 4096 else None}


def _mount(source, target, fs=None, flags=0, data=None):
    libc = ctypes.CDLL(None, use_errno=True)
    encode = lambda value: str(value).encode() if value is not None else None
    if libc.mount(encode(source), encode(target), encode(fs), ctypes.c_ulong(flags), encode(data)):
        raise OSError(ctypes.get_errno(), "isolation mount failed")


def _bind(source: Path, target: Path, *, device=False):
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        target.mkdir(exist_ok=True)
    elif not target.exists():
        target.touch()
    _mount(source, target, flags=MS_BIND)
    _mount(None, target, flags=MS_BIND | MS_REMOUNT | MS_RDONLY | MS_NOSUID | (0 if device else MS_NODEV))


def _runtime():
    executable = Path(sys.executable).resolve()
    stdlib = Path(sysconfig.get_path("stdlib")).resolve()
    native = Path(__file__).resolve().parent / "assets" / "native" / "_viva_native.so"
    return {
        "kernel": os.uname().release,
        "python": sys.version.split()[0],
        "python_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "executable": str(executable),
        "stdlib": str(stdlib),
        "soabi": sysconfig.get_config_var("SOABI"),
        "debug": bool(sysconfig.get_config_var("Py_DEBUG")),
        "gil_enabled": bool(sys._is_gil_enabled()) if hasattr(sys, "_is_gil_enabled") else None,
        "machine": os.uname().machine,
        "jit_enabled": bool(sys._jit.is_enabled()) if hasattr(sys, "_jit") else False,
        "native_sha256": hashlib.sha256(native.read_bytes()).hexdigest() if native.is_file() else None,
    }


def _dependencies(executable: Path, stdlib: Path, native: Path | None = None):
    # Inputs are fixed image files, never caller-selected executables.
    files = [executable, *sorted(stdlib.glob("lib-dynload/*.so"))]
    if native is not None:
        files.append(native)
    result = subprocess.run(["ldd", *map(str, files)], capture_output=True, timeout=3, check=False)
    if result.returncode != 0 or b"not found" in (result.stdout + result.stderr).lower():
        raise RuntimeError("dynamic dependency resolution failed")
    # Match dependency rows with addresses, excluding ldd's input-file headers.
    paths = set(re.findall(
        rb"(?m)^\s*(?:[^\s=>]+\s+=>\s+)?(/[^\s]+)\s+\(0x[0-9a-fA-F]+\)\s*$", result.stdout))
    libraries = {Path(path.decode()) for path in paths}
    if any(not path.is_file() for path in libraries):
        raise RuntimeError("resolved dynamic dependency is unavailable")
    if not libraries or not any("ld-linux" in str(path) for path in libraries):
        raise RuntimeError("dynamic loader unavailable")
    return sorted(libraries)


def _drop_privileges():
    libc = ctypes.CDLL(None, use_errno=True)
    # Drop every supported capability from the bounding set before changing UID.
    for capability in range(64):
        if libc.prctl(24, capability, 0, 0, 0) and ctypes.get_errno() != errno.EINVAL:
            raise OSError("capability bounding-set drop failed")
    if libc.prctl(38, 1, 0, 0, 0):
        raise OSError("no_new_privs failed")
    os.setgroups([])
    os.setresgid(65534, 65534, 65534)
    os.setresuid(65534, 65534, 65534)
    class Header(ctypes.Structure):
        _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]
    class Data(ctypes.Structure):
        _fields_ = [("effective", ctypes.c_uint32), ("permitted", ctypes.c_uint32), ("inheritable", ctypes.c_uint32)]
    if libc.capset(ctypes.byref(Header(0x20080522, 0)), (Data * 2)()):
        raise OSError("capability drop failed")
    readback = (Data * 2)()
    if libc.capget(ctypes.byref(Header(0x20080522, 0)), readback):
        raise OSError("capability readback failed")
    if any(value.effective or value.permitted or value.inheritable for value in readback) or libc.prctl(39, 0, 0, 0, 0) != 1:
        raise OSError("privilege policy readback mismatch")
    if os.getresuid() != (65534,) * 3 or os.getresgid() != (65534,) * 3:
        raise OSError("identity drop readback mismatch")


def _child(root: Path, ready_fd: int, key_fd: int, auth_fd: int, budget: dict):
    if any(not 3 <= fd < 64 for fd in (ready_fd, key_fd, auth_fd)) or len({ready_fd,key_fd,auth_fd}) != 3:
        raise RuntimeError("invalid native channel descriptors")
    _mount(None, "/", flags=MS_REC | MS_PRIVATE)
    executable = Path(sys.executable).resolve()
    stdlib = Path(sysconfig.get_path("stdlib")).resolve()
    for path in [executable, stdlib, *_dependencies(executable, stdlib, root / "runner" / "_viva_native.so")]:
        _bind(path, root / str(path).lstrip("/"))
    for name in ("null", "random", "urandom"):
        _bind(Path("/dev") / name, root / "dev" / name, device=True)
    (root / "proc").mkdir()
    (root / "tmp").mkdir(mode=0o777)
    _mount(root, root, flags=MS_BIND | MS_REC)
    _mount(None, root, flags=MS_BIND | MS_REMOUNT | MS_RDONLY | MS_NOSUID | MS_NODEV)
    _mount("tmpfs", root / "tmp", "tmpfs", MS_NOSUID | MS_NODEV | MS_NOEXEC,
           f"size={budget['tmpfs_size_mb']}m,mode=1777")
    os.chroot(root)
    os.chdir("/tmp")
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (budget["invocation_cpu_seconds"], budget["invocation_cpu_seconds"]))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_FSIZE, (budget["tmpfs_size_mb"] * 1048576,) * 2)
    _drop_privileges()
    os.write(ready_fd, b"R")
    os.close(ready_fd)
    command = f"import sys;sys.path.insert(0,'/runner');import _viva_native;_viva_native.run({key_fd},{auth_fd})"
    os.execve(str(executable), [str(executable), "-I", "-B", "-S", "-c", command],
              {"PATH": "/usr/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})


def _stats(path: Path):
    return {key: int(value) for key, value in (line.split() for line in path.read_text().splitlines())}


def _kill_and_empty(cgroup: Path):
    (cgroup / "cgroup.kill").write_text("1")
    deadline = time.monotonic() + 1
    while _stats(cgroup / "cgroup.events").get("populated", 1):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)
    return True


def supervise(payload: dict, assets: Path):
    budget = payload["budget"]
    # Host adapter already validates budgets; enforce the deployment ceiling again.
    ceilings = {"memory_limit_mb": 256, "pids_limit": 16, "tmpfs_size_mb": 8,
                "invocation_cpu_seconds": 2, "invocation_wall_ms": 2000,
                "startup_deadline_ms": 5000, "max_stdout_bytes": 65536,
                "max_stderr_bytes": 65536, "max_result_bytes": 65536,
                "max_trace_bytes": 262144, "max_trace_steps": 250, "max_trace_snapshots_work": 2000}
    if any(type(budget.get(key)) is not int or not 0 < budget[key] <= value for key, value in ceilings.items()):
        raise ValueError("unsupported invocation budget")
    start = time.monotonic()
    cgroup = CGROUP_ROOT / ("viva-" + os.urandom(12).hex())
    root = None
    proc = None
    ready_r = ready_w = key_r = key_w = auth_r = auth_w = None
    output = {"schema": SCHEMA, "runtime": None, "reason": "setup_failure",
              "returncode": None, "stdout_b64": "", "stderr_b64": "",
              "duration_ms": 0, "cleanup_verified": False, "limits": {}, "events": {},
              "cleanup_failures": []}
    phase = "runtime_identity"
    try:
        output["runtime"] = _runtime()
        if payload.get("expected_runtime") is not None and payload["expected_runtime"] != output["runtime"]:
            raise RuntimeError("runtime acceptance identity mismatch")
        phase = "root_create"
        root = Path(tempfile.mkdtemp(prefix="viva-root-"))
        os.chmod(root, 0o755)
        phase = "cgroup_controllers"
        controllers = set((CGROUP_ROOT / "cgroup.controllers").read_text().split())
        if not {"cpu", "memory", "pids"} <= controllers:
            raise RuntimeError("cgroup controllers unavailable")
        phase = "cgroup_enable"
        (CGROUP_ROOT / "cgroup.subtree_control").write_text("+cpu +memory +pids")
        phase = "cgroup_create"
        cgroup.mkdir()
        phase = "cgroup_limits"
        limits = {"memory.max": str(budget["memory_limit_mb"] * 1048576),
                  "memory.swap.max": "0", "memory.oom.group": "1",
                  "pids.max": str(budget["pids_limit"]), "cpu.max": "100000 100000"}
        for name, value in limits.items():
            (cgroup / name).write_text(value)
        output["limits"] = {name: (cgroup / name).read_text().strip() for name in limits}
        if output["limits"] != limits:
            raise RuntimeError("cgroup limit readback mismatch")
        phase = "guest_stage"
        (root / "runner").mkdir()
        shutil.copytree(assets / "exec_worker", root / "runner" / "exec_worker")
        native = assets / "native" / "_viva_native.so"
        shutil.copyfile(native, root / "runner" / "_viva_native.so")
        output["runtime"]["native_sha256"] = hashlib.sha256(native.read_bytes()).hexdigest()
        identity = output["runtime"]
        phase = "native_identity"
        if identity["python"] != "3.14.4" or identity["soabi"] != "cpython-314-x86_64-linux-gnu" or identity["debug"] or not identity["gil_enabled"] or identity["machine"] != "x86_64" or identity["jit_enabled"]:
            raise RuntimeError("unsupported native interpreter configuration")
        phase = "payload_stage"
        (root / "ipc").mkdir()
        payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        (root / "ipc" / "payload.json").write_bytes(payload_bytes)
        payload_hash = hashlib.sha256(payload_bytes).hexdigest()
        for path in (root / "runner").rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o444)
        (root / "ipc" / "payload.json").chmod(0o444)
        phase = "pipes"
        ready_r, ready_w = os.pipe()
        key_r, key_w = os.pipe()
        auth_r, auth_w = os.pipe()
        native_key = os.urandom(32)
        os.write(key_w, native_key)
        os.close(key_w)
        key_w = None
        os.set_blocking(ready_r, False)
        def join_cgroup():
            (cgroup / "cgroup.procs").write_text(str(os.getpid()))
        phase = "child_start"
        proc = subprocess.Popen(["unshare", "--mount", "--pid", "--net", "--ipc", "--uts", "--fork",
                                 str(Path(sys.executable).resolve()), "-I", str(Path(__file__).resolve()),
                                 "--child", str(root), str(ready_w), str(key_r), str(auth_w), json.dumps(budget)],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                                pass_fds=(ready_w,key_r,auth_w), preexec_fn=join_cgroup)
        os.close(ready_w)
        ready_w = None
        os.close(key_r); key_r = None
        os.close(auth_w); auth_w = None
        selector = selectors.DefaultSelector()
        stdout, stderr, authenticated = bytearray(), bytearray(), bytearray()
        caps = {"stdout": budget["max_stdout_bytes"], "stderr": budget["max_stderr_bytes"],
                "auth": (budget["max_trace_bytes"] if payload["mode"] == "trace" else budget["max_result_bytes"]) + 128}
        for stream, label in ((proc.stdout, "stdout"), (proc.stderr, "stderr")):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, label)
        selector.register(ready_r, selectors.EVENT_READ, "ready")
        os.set_blocking(auth_r, False)
        selector.register(auth_r, selectors.EVENT_READ, "auth")
        invocation_start = None
        reason = "exited"
        phase = "capture"
        while selector.get_map():
            now = time.monotonic()
            if invocation_start is None and now - start >= budget["startup_deadline_ms"] / 1000:
                reason = "startup_timeout"
                break
            if invocation_start is not None and now - invocation_start >= budget["invocation_wall_ms"] / 1000:
                reason = "wall_timeout"
                break
            if _stats(cgroup / "cpu.stat").get("usage_usec", 0) >= budget["invocation_cpu_seconds"] * 1000000:
                reason = "cpu_limit"
                break
            for key, _ in selector.select(0.01):
                fd = key.fileobj if isinstance(key.fileobj, int) else key.fileobj.fileno()
                chunk = os.read(fd, 8192)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                if key.data == "ready":
                    if chunk != b"R" or invocation_start is not None:
                        raise RuntimeError("invalid startup marker")
                    invocation_start = time.monotonic()
                    sys.stdout.buffer.write(READY_MARKER)
                    sys.stdout.buffer.flush()
                    continue
                buf = {"stdout": stdout, "stderr": stderr, "auth": authenticated}[key.data]
                remaining = caps[key.data] - len(buf)
                buf.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    reason = "stdout_limit" if key.data == "auth" else key.data + "_limit"
                    break
            if reason != "exited":
                break
        selector.close()
        phase = "process_cleanup"
        if not _kill_and_empty(cgroup):
            raise RuntimeError("process-tree cleanup failed")
        proc.wait(timeout=1)
        events = {"memory": _stats(cgroup / "memory.events"), "pids": _stats(cgroup / "pids.events"),
                  "cpu": _stats(cgroup / "cpu.stat")}
        if reason == "exited" and invocation_start is None:
            reason = "setup_failure"
        if reason == "exited" and events["memory"].get("oom_kill", 0):
            reason = "memory_limit"
        frame = b"UNAUTHENTICATED_NATIVE_RESULT"
        output["native_authenticated"] = False
        phase = "result_authentication"
        if reason == "exited":
            try:
                frame = authenticated_runner_frame(bytes(authenticated), native_key, payload_hash,
                    stdout=bytes(stdout), stderr=bytes(stderr))
                output["native_authenticated"] = True
            except NativeProtocolError:
                pass
        output.update(reason=reason, returncode=proc.returncode,
                      stdout_b64=base64.b64encode(frame).decode(), stderr_b64="",
                      duration_ms=int((time.monotonic() - (invocation_start or start)) * 1000), events=events)
    except BaseException as error:
        output["failure"] = _diagnostic(phase, error)
        output["reason"] = "setup_failure"
    finally:
        def cleanup(stage, action):
            try:
                action()
                return True
            except BaseException as error:
                output["cleanup_failures"].append(_diagnostic(stage, error))
                return False
        try:
            if cgroup.exists():
                def empty_cgroup():
                    if not _kill_and_empty(cgroup):
                        raise RuntimeError("process-tree cleanup failed")
                empty = cleanup("cleanup_cgroup_kill", empty_cgroup)
                if proc is not None:
                    cleanup("cleanup_wait", lambda: proc.wait(timeout=1))
                if empty:
                    cleanup("cleanup_cgroup_remove", cgroup.rmdir)
        except BaseException as error:
            output["cleanup_failures"].append(_diagnostic("cleanup_check", error))
        for fd in (ready_r, ready_w, key_r, key_w, auth_r, auth_w):
            if fd is not None:
                cleanup("cleanup_fd_close", lambda fd=fd: os.close(fd))
        if root is not None:
            cleanup("cleanup_root_remove", lambda: shutil.rmtree(root))
        try:
            output["cleanup_verified"] = (not output["cleanup_failures"] and not cgroup.exists()
                and (root is None or not root.exists()))
        except BaseException as error:
            output["cleanup_failures"].append(_diagnostic("cleanup_check", error))
    return output


def main():
    if len(sys.argv) == 7 and sys.argv[1] == "--child":
        _child(Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), json.loads(sys.argv[6]))
        return
    result = {"schema": SCHEMA, "reason": "setup_failure", "cleanup_verified": False}
    phase = "root_permission"
    try:
        if os.geteuid() != 0:
            raise RuntimeError("root supervisor required")
        phase = "input_read"
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError("input too large")
        phase = "input_parse"
        payload = json.loads(raw)
        phase = "supervision"
        result = supervise(payload, Path(__file__).parent / "assets")
    except BaseException as error:
        # No source, environment, SDK metadata or raw exceptions leave the VM.
        result["failure"] = _diagnostic(phase, error)
    wire = json.dumps(result, separators=(",", ":")).encode()
    if len(wire) > MAX_WIRE_BYTES:
        wire = b'{"schema":"viva-supervisor-v1","reason":"output_failure","cleanup_verified":false}'
    sys.stdout.buffer.write(wire + b"\n")


if __name__ == "__main__":
    main()
