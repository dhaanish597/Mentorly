"""Dependency checks fail before any learner process can be launched."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from exec_worker.vercel_sandbox import supervisor


@pytest.fixture
def runtime_files(tmp_path):
    executable = tmp_path / "python"
    stdlib = tmp_path / "stdlib"
    dynamic = stdlib / "lib-dynload"
    dynamic.mkdir(parents=True)
    extension = dynamic / "_socket.so"
    native = tmp_path / "_viva_native.so"
    libc = tmp_path / "libc.so.6"
    crypto = tmp_path / "libcrypto.so.3"
    loader = tmp_path / "ld-linux-x86-64.so.2"
    for path in (executable, extension, native, libc, crypto, loader):
        path.touch()
    output = (f"{native}:\n\tlinux-vdso.so.1 (0x1234)\n"
              f"\tlibc.so.6 => {libc} (0x2345)\n"
              f"\tlibcrypto.so.3 => {crypto} (0x3456)\n"
              f"\t{loader} (0x4567)\n").encode()
    return SimpleNamespace(executable=executable, stdlib=stdlib, extension=extension,
                           native=native, libc=libc, crypto=crypto, loader=loader, output=output)


def test_native_dependencies_are_verified_and_returned(runtime_files, monkeypatch):
    files = runtime_files
    calls = []

    def ldd(command, **options):
        calls.append((command, options))
        return SimpleNamespace(stdout=files.output, stderr=b"", returncode=0)

    monkeypatch.setattr(supervisor.subprocess, "run", ldd)
    assert supervisor._dependencies(files.executable, files.stdlib, files.native) == sorted(
        [files.libc, files.crypto, files.loader])
    assert calls == [(["ldd", str(files.executable), str(files.extension), str(files.native)],
                     {"capture_output": True, "timeout": 3, "check": False})]


@pytest.mark.parametrize("failure", ["nonzero", "not_found_stdout", "not_found_stderr", "missing_path"])
def test_bad_dependencies_stop_before_learner_setup(runtime_files, tmp_path, monkeypatch, failure):
    files = runtime_files
    stdout, stderr, returncode = files.output, b"", 0
    if failure == "nonzero":
        returncode = 1
    elif failure == "not_found_stdout":
        stdout += b"\tlibmissing.so.1 => not found\n"
    elif failure == "not_found_stderr":
        stderr = b"required symbol version not found\n"
    else:
        files.crypto.unlink()
    monkeypatch.setattr(supervisor.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        stdout=stdout, stderr=stderr, returncode=returncode))
    monkeypatch.setattr(supervisor.sys, "executable", str(files.executable))
    monkeypatch.setattr(supervisor.sysconfig, "get_path", lambda name: str(files.stdlib))
    monkeypatch.setattr(supervisor, "_mount", lambda *args, **kwargs: None)
    monkeypatch.setattr(supervisor, "_bind", lambda *args, **kwargs: pytest.fail("bound incomplete runtime"))
    monkeypatch.setattr(supervisor, "_drop_privileges", lambda: pytest.fail("continued learner setup"))
    monkeypatch.setattr(supervisor.os, "execve", lambda *args: pytest.fail("launched learner process"))
    with pytest.raises(RuntimeError, match="dynamic dependency"):
        supervisor._child(tmp_path / "root", 3, 4, 5, {})
