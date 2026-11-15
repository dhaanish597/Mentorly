"""Build-only exact CPython driver on a free standard public Ubuntu runner."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import sysconfig


def main():
    if sys.version_info[:3] != (3, 14, 4) or platform.system() != "Linux" or platform.machine() != "x86_64":
        raise SystemExit("Exact Python 3.14.4 on Linux x86_64 is required")
    if sysconfig.get_config_var("Py_DEBUG") or sysconfig.get_config_var("Py_GIL_DISABLED"):
        raise SystemExit("Only non-debug GIL-enabled CPython is supported")
    root = Path(__file__).resolve().parent
    abi = sysconfig.get_config_var("SOABI")
    if abi != "cpython-314-x86_64-linux-gnu":
        raise SystemExit("Unexpected build SOABI")
    headers = Path(sysconfig.get_path("include"))
    if not (headers / "Python.h").is_file() or not (headers / "patchlevel.h").is_file():
        raise SystemExit("Exact installed Python development headers are missing")
    target = root / "_viva_native.so"
    flags = ["-shared", "-fPIC", "-O2", "-std=c11", "-Wall", "-Wextra", "-Werror", "-fstack-protector-strong", "-D_FORTIFY_SOURCE=2", "-Wl,-z,relro,-z,now"]
    # CPython symbols resolve from the exact guest interpreter; OpenSSL uses its
    # stable major-3 shared-library ABI. Guest loading still needs acceptance.
    command = ["gcc", *flags, f'-DVIVA_BUILD_SOABI="{abi}"', "-I", str(headers), str(root / "guard.c"), "-lcrypto", "-o", str(target)]
    subprocess.run(command, check=True)
    subprocess.run(["strip", "--strip-unneeded", str(target)], check=True)
    raw = target.read_bytes()
    if len(raw) > 131072:
        raise SystemExit("Native binary exceeds the bounded log transport allowance")
    header_digest = hashlib.sha256()
    header_count = 0
    for header in sorted(headers.rglob("*.h")):
        header_digest.update(str(header.relative_to(headers)).encode() + b"\0" + header.read_bytes() + b"\0")
        header_count += 1
    elf_dependencies = subprocess.check_output(["readelf", "--dynamic", str(target)], text=True)
    elf_versions = subprocess.check_output(["readelf", "--version-info", str(target)], text=True)
    if len(elf_dependencies) > 16384 or len(elf_versions) > 16384:
        raise SystemExit("ELF provenance exceeds bounds")
    provenance = {"schema": "viva-native-build-v1", "python": platform.python_version(),
        "soabi": abi, "architecture": platform.machine(), "gil_enabled": True, "debug": False,
        "source_sha256": hashlib.sha256((root / "guard.c").read_bytes()).hexdigest(),
        "binary_sha256": hashlib.sha256(raw).hexdigest(), "binary_bytes": len(raw),
        "compiler": subprocess.check_output(["gcc", "--version"], text=True).splitlines()[0],
        "workflow_commit": os.environ.get("GITHUB_SHA"), "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
        "headers_sha256": {name: hashlib.sha256((headers / name).read_bytes()).hexdigest() for name in ("Python.h", "patchlevel.h")},
        "installed_headers_sha256": header_digest.hexdigest(), "installed_header_count": header_count,
        "python_executable_sha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
        "build_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "libc": platform.libc_ver(), "elf_dependencies": elf_dependencies, "elf_versions": elf_versions,
        "python_config": {name: sysconfig.get_config_var(name) for name in ("SOABI", "EXT_SUFFIX", "ABIFLAGS", "Py_DEBUG", "Py_GIL_DISABLED", "WITH_PYMALLOC", "Py_ENABLE_SHARED", "PYTHON_JIT")},
        "flags": flags, "live_accepted": False}
    encoded = base64.b64encode(raw).decode("ascii")
    print("VIVA_NATIVE_PROVENANCE " + json.dumps(provenance, sort_keys=True), flush=True)
    print("VIVA_NATIVE_BINARY_BEGIN", flush=True)
    for offset in range(0, len(encoded), 2048):
        print("VIVA_NATIVE_BINARY " + encoded[offset:offset + 2048], flush=True)
    print("VIVA_NATIVE_BINARY_END", flush=True)


if __name__ == "__main__":
    main()
