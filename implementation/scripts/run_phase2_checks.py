"""Reproducible Local & Cloud Phase 2 Verification Runner (`scripts/run_phase2_checks.py`).

Implements Repair Prompt §4 & §5:
- Runs all trusted offline checks against an existing repository checkout without requiring Colab.
- Executes read-only OpenAPI (`export_openapi.py --check`) and TypeScript contract drift
  (`check_schema_drift.py --check --self-test`) gates BEFORE any regeneration.
- Verifies clean minimal runner COPY layout (`exec_worker/__init__.py` + `exec_worker/runner/*.py`)
  in an isolated `-I -B` import-only subprocess (`P2-03` & `R1`).
- Runs the non-recursive archive sentinel self-test (`R6`).
- Runs all real supplied test suites (`backend/tests`, `exec_worker/tests`,
  `test_r1_to_r9_regressions.py`, `test_speech_foundation.py`, and frontend `typecheck`,
  `test`, and `build`).
- Persists each command result (`check_results.json`) and partial logs (`TEST_LOGS.txt`)
  even after failures, aggregates required failures, and exits nonzero on any required failure.
- Keeps `LIVE_GNANI_SMOKE` and `LIVE_GVISOR_ISOLATION` visibly separate (never reporting
  skipped external checks as `PASS`).
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
# Direct invocation with -I deliberately imports only this reviewed checkout.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

COMMAND_TIMEOUT_SECONDS = 600
NOTEBOOK_NAMES = ("FULL_PROJECT_COLAB.ipynb", "PHASE_2_COLAB.ipynb")

EXCLUDED_DIR_NAMES = {
    ".git",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "dist",
    "build",
    "artifacts",
    ".tts_cache",
    "tts_cache", "data", "runtime", "recordings", "private_recordings",
    "coverage", ".hypothesis", ".cache", "keys", "credentials", "backups",
}
EXCLUDED_SUFFIXES = {
    ".pyc", ".pyo", ".sqlite", ".sqlite3", ".db", ".pem", ".key",
    ".db-wal", ".db-shm", ".db-journal", ".sqlite-wal", ".sqlite-shm", ".sqlite-journal", ".sqlite3-wal", ".sqlite3-shm", ".sqlite3-journal",
    ".wav", ".pcm", ".mp3", ".webm", ".ogg", ".m4a", ".flac", ".aac", ".mp4",
    ".tar", ".gz", ".zip", ".bz2", ".xz", ".7z", ".whl", ".egg",
}


def is_approved_source_file(path: Path, root: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    rel = path.relative_to(root)
    if any(part in EXCLUDED_DIR_NAMES or part.startswith(".venv") for part in rel.parts):
        return False
    if root.is_symlink() or any((root / parent).is_symlink() for parent in rel.parents):
        return False
    if path.name == ".DS_Store" or any(part.endswith(".egg-info") for part in rel.parts):
        return False
    if (path.name.startswith(".env") and path.name != ".env.example") or path.suffix in EXCLUDED_SUFFIXES:
        return False
    with path.open("rb") as file:
        if file.read(16) == b"SQLite format 3\x00":
            return False
    return True


def build_verified_source_archive(src_root: Path, out_tar_gz: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    with tarfile.open(out_tar_gz, "w:gz") as tar:
        for p in sorted(src_root.rglob("*")):
            if not is_approved_source_file(p, src_root):
                continue
            rel_str = p.relative_to(src_root).as_posix()
            tar.add(p, arcname=rel_str, recursive=False)
            manifest[rel_str] = hashlib.sha256(p.read_bytes()).hexdigest()
    return manifest


def run_archive_sentinel_self_test() -> tuple[int, str, str]:
    with tempfile.TemporaryDirectory(prefix="vcc_r6_sentinel_") as tmp:
        tmp_root = Path(tmp) / "repo"
        (tmp_root / "backend" / "app").mkdir(parents=True)
        (tmp_root / "backend" / "app" / "main.py").write_text("print('ok')\n", encoding="utf-8")
        (tmp_root / "nested" / "node_modules" / "pkg").mkdir(parents=True)
        (tmp_root / "nested" / "node_modules" / "pkg" / "sentinel.js").write_text(
            "SECRET_DEP", encoding="utf-8"
        )
        (tmp_root / "nested" / ".env").write_text("VCC_GNANI_API_KEY=leak\n", encoding="utf-8")
        (tmp_root / "nested" / "state.sqlite3").write_text("db", encoding="utf-8")

        tar_path = Path(tmp) / "test.tar.gz"
        manifest = build_verified_source_archive(tmp_root, tar_path)
        with tarfile.open(tar_path, "r:gz") as tar:
            names = tar.getnames()
        if names != ["backend/app/main.py"] or list(manifest.keys()) != ["backend/app/main.py"]:
            return (1, "", f"Sentinel leak in archive members: {names}")
    return (0, "PASS: Archive exclusion sentinel self-test verified (recursive=False).\n", "")


def run_isolated_runner_copy_check(repo_root: Path) -> tuple[int, str, str]:
    with tempfile.TemporaryDirectory(prefix="vcc_runner_copy_") as tmp:
        staged = Path(tmp) / "app"
        (staged / "exec_worker" / "runner").mkdir(parents=True)
        shutil.copy2(
            repo_root / "exec_worker" / "__init__.py",
            staged / "exec_worker" / "__init__.py",
        )
        for py_file in sorted((repo_root / "exec_worker" / "runner").glob("*.py")):
            shutil.copy2(py_file, staged / "exec_worker" / "runner" / py_file.name)

        code = (
            f"import sys; sys.path.insert(0, {str(staged)!r}); "
            "import exec_worker.runner; "
            "import exec_worker.runner.run_invocation; "
            "import exec_worker.runner.in_sandbox_tracer; "
            "import exec_worker.runner.safe_serializer; "
            "assert 'backend' not in sys.modules; "
            "assert 'exec_worker.worker_app' not in sys.modules; "
            "print('PASS: Minimal runner COPY layout imported; execution requires gVisor acceptance.')"
        )
        proc = subprocess.run(
            [sys.executable, "-I", "-B", "-c", code],
            cwd=tmp,
            env={"PATH": os.environ.get("PATH", "")},
            timeout=30,
            capture_output=True,
            text=True,
            check=False,
        )
        return (proc.returncode, proc.stdout, proc.stderr)


def _redact(text: str, env: dict[str, str] | None = None) -> str:
    for key, value in (env or dict(os.environ)).items():
        if value and re.search(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", key, re.I):
            text = text.replace(value, "[REDACTED]")
    return text


def _text(value: str | bytes | None) -> str:
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else (value or "")


def _result(
    name: str, cmd: list[str], cwd: Path, code: int, stdout: str, stderr: str,
    started: float, required: bool = True, gate_category: str = "OFFLINE_REQUIRED",
    *, env: dict[str, str] | None = None,
) -> dict[str, Any]:
    status = "PASS" if code == 0 else "FAIL"
    if code in (0, 2) and gate_category in {
        "LIVE_EXTERNAL_PROVIDER", "LIVE_EXTERNAL_ISOLATION", "OFFLINE_PROVIDER_PREFLIGHT"
    }:
        try:
            summary = json.loads(stdout)
        except (ValueError, TypeError):
            summary = None
        if isinstance(summary, dict) and summary.get("status") == "BLOCKED_EXTERNAL":
            status = "BLOCKED_EXTERNAL"
    return {
        "name": name, "command": [_redact(arg, env) for arg in cmd], "cwd": str(cwd),
        "exit_code": code, "duration_s": round(time.monotonic() - started, 4),
        "required": required, "gate_category": gate_category, "status": status,
        "stdout": _redact(stdout, env), "stderr": _redact(stderr, env),
    }


def run_internal_check(
    name: str, check: Callable[[], tuple[int, str, str]], cwd: Path,
    *, gate_category: str = "OFFLINE_REQUIRED",
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        code, stdout, stderr = check()
    except Exception as exc:
        code, stdout, stderr = 1, "", f"{type(exc).__name__}: {exc}"
    return _result(name, [f"internal:{name}"], cwd, code, stdout, stderr,
                   started, gate_category=gate_category)


def validate_notebooks(repo_root: Path) -> tuple[int, str, str]:
    """Parse Python cells only; notebook validation must never execute their code."""
    try:
        for name in NOTEBOOK_NAMES:
            notebook = json.loads((repo_root / "cloud" / name).read_text(encoding="utf-8"))
            if notebook.get("nbformat") != 4:
                raise ValueError(f"{name}: expected notebook format 4")
            code_cells = [c for c in notebook["cells"] if c["cell_type"] == "code"]
            if not code_cells:
                raise ValueError(f"{name}: missing Python code cells")
            for index, cell in enumerate(code_cells):
                ast.parse("".join(cell["source"]), filename=f"{name}:cell-{index}")
    except (OSError, ValueError, KeyError, TypeError, SyntaxError) as exc:
        return 1, "", f"{type(exc).__name__}: {exc}"
    return 0, "PASS: Both Colab notebooks contain syntactically valid Python (parse-only).\n", ""


def _check_test_output(cmd: list[str], code: int, stdout: str, stderr: str) -> tuple[int, str, int | None]:
    is_pytest = "pytest" in cmd
    is_vitest = Path(cmd[0]).name == "npm" and ("test" in cmd or "test:coverage" in cmd)
    if not (is_pytest or is_vitest):
        return code, stderr, None
    output = re.sub(r"\x1b\[[0-9;]*m", "", stdout + "\n" + stderr)
    pattern = r"\b(\d+) passed\b" if is_pytest else r"(?m)^\s*Tests\s+(\d+) passed\b"
    matches = re.findall(pattern, output)
    passed = int(matches[-1]) if matches else 0
    if code == 0 and passed == 0:
        return 1, stderr + "\nRequired test gate executed no passing tests; empty/skipped-only suites cannot pass.", passed
    if code == 0 and "test_sandbox_isolation.py" in " ".join(cmd) and re.search(r"\b\d+ skipped\b", output):
        return 1, stderr + "\nLive isolation acceptance cannot pass with skipped probes.", passed
    return code, stderr, passed


def run_command(
    name: str, cmd: list[str], cwd: Path, *,
    env_overrides: dict[str, str] | None = None, required: bool = True,
    gate_category: str = "OFFLINE_REQUIRED",
) -> dict[str, Any]:
    reporting_env = {**os.environ, **(env_overrides or {})}
    env = {key: value for key, value in reporting_env.items()
           if not re.search(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", key, re.I)}
    if gate_category == "LIVE_EXTERNAL_PROVIDER":
        env["VCC_GNANI_API_KEY"] = reporting_env.get("VCC_GNANI_API_KEY", "")
    else:
        # Secret values are not the only credential source: never inherit a live file.
        env.pop("VCC_ENV_FILE", None)
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True,
                              text=True, errors="replace", check=False,
                              timeout=COMMAND_TIMEOUT_SECONDS)
        code, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        code, stdout = 1, _text(getattr(exc, "stdout", None))
        stderr = _text(getattr(exc, "stderr", None)) + f"\n{type(exc).__name__}: {exc}"
    code, stderr, passed = _check_test_output(cmd, code, stdout, stderr)
    result = _result(name, cmd, cwd, code, stdout, stderr, started, required, gate_category, env=reporting_env)
    if name == "p8_code_eval_12_buggy_6_correct" and result["status"] == "PASS":
        try:
            summary = json.loads(stdout)
            buggy = summary["buggy_results"]
            correct = summary["correct_results"]
            valid = (
                summary["overall_pass"] is True and not summary.get("mocked")
                and summary["buggy_total"] == summary["buggy_detected_count"] == len(buggy) == 12
                and summary["correct_total"] == summary["correct_passed_count"] == len(correct) >= 6
                and all(item["detected"] is True and item["status"] in {"COUNTEREXAMPLE_CONFIRMED", "EXECUTION_ERROR"} for item in buggy)
                and all(item["passed"] is True and item["status"] == "NO_FAILURE_FOUND" for item in correct)
            )
        except (ValueError, KeyError, TypeError):
            valid = False
        if not valid:
            result = {**result, "status": "FAIL", "exit_code": 1,
                      "stderr": result["stderr"] + "\nCode evaluation requires complete real 12-buggy/6-correct results, never empty or mocked success."}
    return {**result, **({"tests_passed": passed} if passed is not None else {})}


def execute_all_checks(
    repo_root: Path,
    output_dir: Path,
    *,
    run_live_gnani: bool = False,
    env_file: Path | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    py_path = f"{repo_root / 'backend'}{os.pathsep}{repo_root}"
    base_py_env = {
        "PYTHONPATH": py_path,
        "CI": "true",
        "VCC_ALLOW_PUBLIC_CUSTOM_CODE": "false",
    }

    results: list[dict[str, Any]] = []

    def _record(item: dict[str, Any]) -> None:
        results.append(item)
        status_label = item["status"]
        print(f"[{status_label}] {item['name']} (exit={item['exit_code']}, {item['duration_s']}s)")
        # Persist incrementally after every step so partial logs survive any crash
        _persist_outputs(output_dir, results)

    # 1. Compileall gate (must run first)
    _record(
        run_command(
            "compileall",
            [sys.executable, "-m", "compileall", "-q", "backend", "exec_worker", "scripts"],
            repo_root,
            env_overrides=base_py_env,
        )
    )

    # 2. Archive sentinel self-test (R6)
    _record(run_internal_check("archive_sentinel_self_test", run_archive_sentinel_self_test, repo_root))
    _record(run_internal_check("notebook_syntax", lambda: validate_notebooks(repo_root), repo_root))

    # 3. Import trusted modules only; this is not learner execution or an isolation proof.
    _record(run_internal_check(
        "runner_image_isolated_import", lambda: run_isolated_runner_copy_check(repo_root),
        repo_root, gate_category="OFFLINE_IMPORT_ONLY",
    ))

    # 4. Read-only OpenAPI check BEFORE any regeneration (R9)
    _record(
        run_command(
            "openapi_drift",
            [sys.executable, "backend/scripts/export_openapi.py", "--check"],
            repo_root,
            env_overrides=base_py_env,
        )
    )

    # 5. Read-only TypeScript contract drift + 6-mutation self-test (R7 & P2-02)
    _record(
        run_command(
            "schema_drift",
            [sys.executable, "scripts/check_schema_drift.py", "--check", "--self-test"],
            repo_root,
            env_overrides=base_py_env,
        )
    )

    # 6. Secret scanner check
    _record(
        run_command(
            "secrets",
            [sys.executable, "scripts/check_secrets.py"],
            repo_root,
            env_overrides=base_py_env,
        )
    )

    # 7. Integrated backend pytest suite
    _record(
        run_command(
            "backend_pytest",
            [sys.executable, "-m", "pytest", "backend/tests", "-v"],
            repo_root,
            env_overrides=base_py_env,
        )
    )

    # 8. P1 execution broker & runner pytest suite
    _record(
        run_command(
            "p1_pytest",
            [sys.executable, "-m", "pytest", "exec_worker/tests", "-v", "-rs"],
            repo_root,
            env_overrides=base_py_env,
        )
    )

    # 9. Dedicated R1-R9 regression suite
    _record(
        run_command(
            "r1_r9_regressions",
            [sys.executable, "-m", "pytest", "backend/tests/unit/test_r1_to_r9_regressions.py", "-v"],
            repo_root,
            env_overrides=base_py_env,
        )
    )

    # 10. Dedicated Phase 2 speech foundation suite
    _record(
        run_command(
            "p2_speech",
            [sys.executable, "-m", "pytest", "backend/tests/unit/test_speech_foundation.py", "-v"],
            repo_root,
            env_overrides=base_py_env,
        )
    )

    # 11. Offline smoke script gate with key deliberately absent
    offline_smoke_env = dict(base_py_env)
    offline_smoke_env["VCC_GNANI_API_KEY"] = ""
    _record(
        run_command(
            "smoke_without_key",
            [sys.executable, "scripts/smoke_gnani.py", "--allow-blocked"],
            repo_root,
            env_overrides=offline_smoke_env,
            required=False,
            gate_category="OFFLINE_PROVIDER_PREFLIGHT",
        )
    )

    # 12-14. Frontend typecheck, Vitest, and production build
    frontend_dir = repo_root / "frontend"
    npm_bin = shutil.which("npm") or "npm"
    _record(run_command("frontend_typecheck", [npm_bin, "run", "typecheck"], frontend_dir))
    _record(run_command("frontend_vitest", [npm_bin, "test"], frontend_dir))
    _record(run_command("frontend_build", [npm_bin, "run", "build"], frontend_dir))

    # Optional separate live Gnani smoke gate (never conflated with offline checks)
    if run_live_gnani:
        smoke_cmd = [sys.executable, "scripts/smoke_gnani.py", "--live"]
        if env_file is not None:
            smoke_cmd.extend(["--env-file", str(env_file)])
        _record(
            run_command(
                "live_gnani_smoke",
                smoke_cmd,
                repo_root,
                env_overrides=base_py_env,
                required=False,
                gate_category="LIVE_EXTERNAL_PROVIDER",
            )
        )

    else:
        _record(_result(
            "live_gnani_smoke", ["not-requested:--run-live-gnani"], repo_root, 2,
            json.dumps({"status": "BLOCKED_EXTERNAL", "reason": "Live provider smoke not requested; no network calls made."}),
            "", time.monotonic(), False, "LIVE_EXTERNAL_PROVIDER",
        ))

    try:
        from exec_worker.worker_app.sandbox_runner import check_runtime_preflight
        preflight = check_runtime_preflight()
    except Exception as exc:
        _record(_result(
            "live_gvisor_isolation_acceptance", ["internal:check_runtime_preflight"], repo_root,
            1, "", f"{type(exc).__name__}: {exc}", time.monotonic(),
            gate_category="LIVE_EXTERNAL_ISOLATION",
        ))
    else:
        if preflight.ready:
            acceptance_env = {**base_py_env, "VCC_RUN_LIVE_GVISOR_ACCEPTANCE": "1"}
            _record(run_command(
                "live_gvisor_isolation_acceptance",
                [sys.executable, "-m", "pytest", "exec_worker/tests/test_sandbox_isolation.py", "-v", "-rs"],
                repo_root, env_overrides=acceptance_env, required=True,
                gate_category="LIVE_EXTERNAL_ISOLATION",
            ))
        else:
            _record(_result(
                "live_gvisor_isolation_acceptance", ["internal:check_runtime_preflight"], repo_root, 2,
                json.dumps({"status": "BLOCKED_EXTERNAL", "reason": preflight.summary}),
                "", time.monotonic(), gate_category="LIVE_EXTERNAL_ISOLATION",
            ))

    required_failures = [r for r in results if r["status"] == "FAIL" or (r["required"] and r["status"] != "PASS")]
    overall_rc = 1 if required_failures else 0
    return overall_rc, results


def _persist_outputs(output_dir: Path, results: list[dict[str, Any]]) -> None:
    sanitized_results = [
        {**r, "stdout": _redact(r.get("stdout", "")), "stderr": _redact(r.get("stderr", "")),
         "command": [_redact(arg) for arg in r["command"]]}
        for r in results
    ]
    (output_dir / "check_results.json").write_text(
        json.dumps(sanitized_results, indent=2) + "\n",
        encoding="utf-8",
    )
    log_chunks: list[str] = []
    for r in sanitized_results:
        log_chunks.append(f"===== {r['name']} (exit={r['exit_code']}, status={r['status']}) =====")
        if r.get("stdout"):
            log_chunks.append(r["stdout"].rstrip())
        if r.get("stderr"):
            log_chunks.append("--- STDERR ---")
            log_chunks.append(r["stderr"].rstrip())
        log_chunks.append("")
    (output_dir / "TEST_LOGS.txt").write_text("\n".join(log_chunks), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run reproducible Phase 2 offline and optional live verification checks."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Path to the Voice Coding Coach implementation root.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "artifacts" / "phase2_local_check",
        help="Directory to write check_results.json and TEST_LOGS.txt.",
    )
    parser.add_argument(
        "--run-live-gnani",
        action="store_true",
        help="Also run the separate live Gnani STT/TTS smoke check if credentials are available.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Optional local .env file path for live Gnani smoke (never copied or logged).",
    )
    args = parser.parse_args(argv)

    overall_rc, results = execute_all_checks(
        args.repo_root.resolve(),
        args.output_dir.resolve(),
        run_live_gnani=args.run_live_gnani,
        env_file=args.env_file,
    )
    offline = [r for r in results if r["required"] and r["gate_category"].startswith("OFFLINE")]
    passed_req = sum(r["status"] == "PASS" for r in offline)
    offline_str = "PASS" if passed_req == len(offline) else "FAIL"
    blocked = sum(r["status"] == "BLOCKED_EXTERNAL" for r in results)
    print(f"\n=== REQUIRED OFFLINE GATES: {offline_str} ({passed_req}/{len(offline)} passed) ===")
    print(f"Overall promotion: {'PASS' if overall_rc == 0 else 'NOT READY'}; externally blocked gates: {blocked}")
    return overall_rc


if __name__ == "__main__":
    raise SystemExit(main())
