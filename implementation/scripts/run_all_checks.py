"""Complete P0–P9 Offline & Optional Live Verification Runner (`scripts/run_all_checks.py`).

Executes all required Phase 0–Phase 9 verification gates in order:
1. `compileall` across `backend`, `exec_worker`, `scripts`, and `evaluation`
2. Archive exclusion sentinel self-test (`R6`)
3. Isolated minimal `Dockerfile.runner` COPY layout import-only check (`R1`, `P2-03`); not a trace or sandbox proof
4. Read-only OpenAPI 3.1 drift gate (`export_openapi.py --check`, `R9`)
5. Read-only TypeScript contract drift + 6-mutation self-test (`check_schema_drift.py --check --self-test`, `R7`, `P2-02`)
6. Secret scanner (`check_secrets.py`)
7. Backend unit & integration test suite (`pytest backend/tests -v`)
8. Execution worker & broker suite (`pytest exec_worker/tests -v -rs`)
9. Codex `R1–R9` regression suite (`pytest backend/tests/unit/test_r1_to_r9_regressions.py -v`)
10. Phase 2 speech foundation suite (`pytest backend/tests/unit/test_speech_foundation.py -v`)
11. Phase 3–Phase 7 coaching loop & epistemic boundary integration suite (`pytest backend/tests/integration/test_p3_to_p7_integration.py -v`)
12. Phase 8 code evaluation harness (12 buggy + 6 correct implementations: `python3 evaluation/run_code_eval.py`)
13. Phase 8 speech normalization & AST latency ablation (`python3 evaluation/speech_ablation/run_speech_ablation.py`)
14. Offline Gnani smoke gate (`python3 scripts/smoke_gnani.py --allow-blocked`)
15. Frontend TypeScript typecheck (`npm run typecheck`), Vitest suite (`npm test`), and production build (`npm run build`).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_phase2_checks import _persist_outputs, execute_all_checks, run_command  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run all P0-P9 verification and evaluation gates.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--output-dir", type=Path, default=REPO_ROOT / "artifacts" / "full_project_check"
    )
    parser.add_argument("--run-live-gnani", action="store_true")
    parser.add_argument("--env-file", type=Path, default=None)
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    out_dir = args.output_dir.resolve()
    rc, results = execute_all_checks(
        repo_root,
        out_dir,
        run_live_gnani=args.run_live_gnani,
        env_file=args.env_file,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    py_env = {
        "PYTHONPATH": f"{repo_root / 'backend'}{os.pathsep}{repo_root}",
        "CI": "true",
        "VCC_ALLOW_PUBLIC_CUSTOM_CODE": "false",
    }

    extra_checks = [
        ("evaluation_compileall", [sys.executable, "-m", "compileall", "-q", "evaluation"], "OFFLINE_REQUIRED"),
        ("p3_p7_integration", [sys.executable, "-m", "pytest", "backend/tests/integration/test_p3_to_p7_integration.py", "-v"], "OFFLINE_REQUIRED"),
        ("p8_code_eval_12_buggy_6_correct", [sys.executable, "evaluation/run_code_eval.py"], "LIVE_EXTERNAL_ISOLATION"),
        ("p8_speech_ablation_and_ast_latency", [sys.executable, "evaluation/speech_ablation/run_speech_ablation.py"], "OFFLINE_REQUIRED"),
    ]
    _persist_outputs(out_dir, results)
    (out_dir / "full_check_results.json").write_bytes((out_dir / "check_results.json").read_bytes())
    for name, cmd, category in extra_checks:
        res = run_command(name, cmd, repo_root, env_overrides=py_env, required=True, gate_category=category)
        results = [*results, res]
        _persist_outputs(out_dir, results)
        (out_dir / "full_check_results.json").write_bytes((out_dir / "check_results.json").read_bytes())
        print(f"[{res['status']}] {name} (exit={res['exit_code']}, {res['duration_s']}s)")

    failures = [r for r in results if r["status"] == "FAIL" or (r["required"] and r["status"] != "PASS")]
    return 1 if (rc != 0 or failures) else 0


if __name__ == "__main__":
    raise SystemExit(main())
