# Voice Coding Coach

One active local app assembled from preserved Gemini imports and Codex work, then repaired/tested locally. Branding remains configurable and undecided. **Local candidate only: P0–P9 acceptance and Drive promotion are incomplete.**

Features include three exercises/four specs, immutable revision-bound prediction challenges, editable explanations, safe worker/trace interfaces, sequential hints, retained failure repair verification and fresh transfer, Monaco, English/Tanglish REST/WS and SSE/WAV paths, typed fallback, cancellation, restore/summary/export/delete and deployment preparation.

Public execution is fail-closed: fresh no-network per-invocation gVisor with real adversarial acceptance bound to runtime/image/daemon. No host learner subprocess, ordinary Docker, RestrictedPython or AST-filter fallback. Protocol mocks are tests, not execution evidence.

## Local startup from `/Users/dhaanish/Desktop/VIVA`

```bash
./.venv-takeover/bin/python -m uvicorn backend.app.main:app --app-dir implementation --host 127.0.0.1 --port 8000
```

```bash
npm --prefix implementation/frontend run dev -- --host 127.0.0.1 --port 5173
```

`.claude/launch.json` offers the same previews without secrets. Preserve any process already using the configured frontend port; use the assigned preview port instead. Typed input works without provider credentials; unavailable isolation is honest, not successful verification.

## Read-only drift and complete checks

```bash
PYTHONPATH=implementation/backend:implementation ./.venv-takeover/bin/python implementation/backend/scripts/export_openapi.py --check
```

```bash
PYTHONPATH=implementation/backend:implementation ./.venv-takeover/bin/python implementation/scripts/check_schema_drift.py --check --self-test
```

```bash
PYTHONPATH=implementation/backend:implementation ./.venv-takeover/bin/python implementation/scripts/run_all_checks.py --output-dir evidence/resume-check
```

Check drift before intentional regeneration. The runner rejects zero/skipped-only tests, persists complete redacted output and distinguishes blocked external gates. A blocked promotion is not a complete release pass.

## Current gates

Drive work is deferred by the user; nothing was uploaded or promoted. Shared Hypothesis generation/provenance and local admission, retention, cache, backup and protected-readiness controls are implemented and tested. See [operations](docs/OPERATIONS.md). One bounded Gnani TTS request returned HTTP 401; no STT/retry. Genuine Linux/runsc acceptance remains unavailable, so public execution stays disabled. Actual deployed capacity/evaluator arrangements, human speech/barge-in evaluation, coverage/wheel verification and HTTPS deployment remain outstanding.

## Handoff

[Status](docs/IMPLEMENTATION_STATUS.md), [feature coverage](docs/FEATURE_COVERAGE.md), [execution audit](docs/CODEX_TAKEOVER_AUDIT.md), [source inventory](docs/SOURCE_INVENTORY.md), [reconciliation](docs/DRIVE_RECONCILIATION.md), [account handoff](docs/ACCOUNT_HANDOFF.md), [active work](docs/ACTIVE_WORK.md), [speech evidence](docs/GNANI_CAPABILITIES.md), [deployment](docs/DEPLOYMENT.md).

Original imports/maps: workspace `imports/drive-20261113`. Latest source-only candidate/hashes and final logs: `evidence/local-completion-20261114`; the previous candidate remains preserved in `evidence/claude-takeover-20261113`. Preserve local work; no commits/pushes, sharing changes, paid provisioning or submission were performed.
