# Next-phase baseline audit

Audited 2026-11-14 in the isolated `VIVA-Codex-next-phase/implementation` copy. No source/contracts regenerated, provider requests, original database access, or live sandbox execution were performed. The coordination manifest lists 279 files; all 279 copied files matched their recorded SHA-256 and none were missing before tests. This compares the copy to the capture, not the concurrently changing original workspace. Generated build products and installed dependencies are outside that comparison.

## Architecture

- `backend/app/main.py` creates FastAPI, middleware and lifecycle services; `api/` exposes metadata/session routes, `models/` defines contracts, and `db/` owns SQLite persistence/migrations.
- `orchestration/` coordinates sessions, revisions and worker communication; `verification/`, `exercises/` and `coaching/` own generated cases, trusted oracles/catalog and teaching responses. `operations/` handles admission, retention, backup and readiness.
- `speech/` owns speech endpoints, provider adapter, normalization and cache. Its router is mounted alongside session routes when `include_session_routes` and the session router are present (`main.py`); offline HTTP/WebSocket acceptance tests exercise the mounted routes with a speech double. This does not establish a live provider call.
- `exec_worker/` contains broker, runner and isolation boundary; frontend React/Monaco code and clients are under `frontend/src/`; `evaluation/` and `scripts/` provide validation and release checks.

## Local results

Python 3.11 venv `.venv311`, installed with `pip install -e 'backend[dev]' -r exec_worker/requirements.worker.txt`; system `python3` is 3.9 and cannot satisfy project requirements. The initial `.venv` created with system Python is unusable; it was not used for the results below.

| Command | Result |
|---|---|
| `PYTHONPATH=backend:. .venv311/bin/pytest backend/tests -q` | 499 passed, one deprecation warning. This exceeds the documented 450-pass earlier snapshot; test counts are not comparable without examining changes and collection. |
| `PYTHONPATH=backend:. .venv311/bin/pytest exec_worker/tests -q -rs` | 207 passed, 9 skipped, one warning. The skips require genuine Linux/Docker/runsc acceptance, absent on this Mac. |
| `.venv311/bin/python backend/scripts/export_openapi.py --check` | Passed, committed OpenAPI matches current app. |
| `.venv311/bin/python scripts/check_schema_drift.py --check --self-test` | Passed, zero drift across 25 enums, 61 interfaces and one union; six mutation self-tests passed. |
| `.venv311/bin/python scripts/validate_catalog.py` | VALID: 31 problems, 32 specs, 173 curated, 64 transfer, 626 generated, 31 examples, 31 known-bug and 31 alternative fixtures. Fixture execution explicitly NOT_RUN_DATA_ONLY. |
| `cd frontend && npm ci` | Installed 239 packages; npm reported 10 advisories (6 moderate, 1 high, 3 critical), without assessment of exploitability. |
| `npm run typecheck` and `npm run build` | Passed; Vite warns Monaco chunk exceeds 500 kB. |
| `npm test` under Node 26.13.0 | 53 passed, 38 failed: Node's experimental global localStorage was unavailable, causing three test files to fail. |
| `NODE_OPTIONS=--no-experimental-webstorage npm test` under Node 26.13.0 | 91 passed; React `act(...)` warnings remain. CI pins Node 20; Node 26 behavior is a reproducibility issue and should be fixed or documented rather than treating the default command as passing on all Node versions. |

All Python commands above used `PYTHONPATH=backend:.`. The prior `docs/IMPLEMENTATION_STATUS.md` describes earlier evidence and outstanding release gates; these local results do not update its historical test counts or establish acceptance.

## Recommendations and boundaries

1. Pin/document supported Node and Python versions, use `npm ci` in CI, and make frontend storage test setup independent of Node's global web-storage implementation; resolve React `act` warnings.
2. Investigate dependency advisories with scope and upgrade compatibility before release; the reported count is an installation-time result, not a security assessment.
3. Keep custom execution disabled pending authorized Linux/runsc adversarial acceptance; offline protocol tests and catalog validation do not prove isolated execution or learner-code behavior.
4. Complete separately gated human speech/device evaluation, real code evaluation, accessibility/browser coverage, deployment and overall coverage requirements. No live provider/sandbox conclusions follow from this audit.
