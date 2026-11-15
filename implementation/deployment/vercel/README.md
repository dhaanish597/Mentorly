# Vercel readiness: blocked for the coordinator

Assessed 2026-11-15. This directory contains assessment documentation only. It is not a deployable application, a frontend-only substitute, or evidence of a successful preview.

## Decision

Do not deploy the current coordinator to Vercel Functions. Native FastAPI/ASGI support solves request dispatch; it does not port this application's persistence, recovery, distributed controls, or background work. No executable Vercel configuration or shim is supplied while those blockers remain.

A protected frontend preview is meaningful only after it points to a separately verified HTTPS coordinator with all advertised features, durable storage and an isolated preview environment. Vercel deployment protection must be confirmed before sharing a URL. A frontend build alone does not satisfy that condition.

## Observed blockers

| Current source | Behavior requiring a port or durable host |
| --- | --- |
| `backend/app/main.py` | Initializes `SQLiteRepository`, recovers incomplete operations on process startup, marks reserved speech usage uncertain, and starts two retention loops in ASGI lifespan. Multiple cold starts cannot be treated as exclusive service restart/recovery. |
| `backend/app/db/migrations.py` and `backend/app/db/repository.py` | Use a local SQLite file and SQLite transactions as the authority for state, schema migrations, replay and ownership. Moving the file to temporary instance storage would lose durability and cross-instance coordination. |
| `backend/app/operations/admission.py` | Uses SQLite rate buckets and a process-local lock/inflight count. An instance-local counter is not a deployment-wide concurrency limit. |
| `backend/app/api/session_security.py` | Uses process-local asyncio locks alongside durable SQLite idempotency records. The same database and atomic reservation guarantees must hold across instances. |
| `backend/app/speech/service.py` and lifespan speech setup | Local speech cache paths and persisted usage/reservation semantics require shared durable data and bounded cleanup. |
| `frontend/vite.config.ts` | `/api` proxy is configured only for Vite development/preview; it is not embedded into the static production build. |

The references above are relative to `implementation/`.

## Required before packaging

1. Port all authoritative SQLite data and atomic operations to a shared transactional store, preserving owner checks, capability revocation, replay, revision compare-and-swap, usage budgets and deletion behavior. Verify across multiple independent processes.
2. Make recovery and cleanup durable, bounded and coordinated outside per-instance ASGI startup/background loops. Test restart while work and speech reservations are in flight.
3. Replace deployment-wide rate, inflight and budget coordination with shared atomic controls. Prove limits cannot multiply with instance count.
4. Put retained audio/artifacts in an authorized shared storage service and validate deletion, authorization and retention across instances.
5. Verify worker reachability, secret handling, cancellation and supported streaming/request durations on the selected hosting arrangement.
6. Provision a separate preview data store, storage namespace and credentials; verify deployment protection and exercise every enabled feature end to end.

## Packaging findings for a future supported deployment

Vercel's current FastAPI integration accepts an exported `app` at supported entrypoints, or an explicit `tool.vercel.entrypoint` in `pyproject.toml`. A conventional future entrypoint could import `backend.app.main:app` only after the application-level blockers above are resolved and import paths, branding/config files and migrations are staged deliberately. Avoid importing the current app merely to make a health endpoint appear ready. See [FastAPI on Vercel](https://vercel.com/docs/frameworks/backend/fastapi).

Python packaging should use runtime-only dependencies and explicit function bundle exclusions. The current backend requirements contain pytest and hypothesis, so copying that manifest unchanged is inappropriate for a minimal runtime package. Required migrations, exercises and branding/config data must survive exclusions. See [Python runtime](https://vercel.com/docs/functions/runtimes/python) and [function configuration](https://vercel.com/docs/project-configuration/vercel-json).

Use an explicit upload allowlist in the staged project rather than uploading this workspace. Exclude `.env` files, SQLite files and sidecars, local audio/caches, evidence, imports, reports, tests, virtual environments and source control metadata. Upload exclusion through `.vercelignore` is distinct from `functions.excludeFiles`, which limits the function bundle. Inspect the actual staged file inventory before any deployment. See [`.vercelignore`](https://vercel.com/docs/deployments/vercel-ignore).

For a future Vite deployment, API routes must resolve to the verified coordinator before the SPA fallback; a catch-all to `index.html` must never return HTML with status 200 for a failed API request. Test direct deep links, assets, unknown API routes, SSE, authorization and errors. Vercel documents the Vite SPA fallback, but the documented standalone catch-all is insufficient by itself for this app's same-origin `/api` contract. See [Vite SPA routing](https://vercel.com/docs/frameworks/frontend/vite#using-vite-to-make-spas).

No deployment, external resource creation or live backend validation was performed by this assessment.
