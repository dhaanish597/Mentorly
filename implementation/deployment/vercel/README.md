# Vercel upload package

Prepared 2026-11-15 for the zero-cost deployment port. These files package the real
FastAPI coordinator and the existing Vite frontend. They do not deploy, configure
remote credentials, migrate a database or establish live acceptance.

## Layout and routing

`stage.py` copies only the paths in `allowlist.json` into a new upload directory.
The backend keeps its `backend.app` imports and sibling `config/branding.json`.
Python, JSON and SQL runtime assets include exercise cases, authored scenarios,
repository golden packages and PostgreSQL migration manifests. The trusted
Sandbox adapter, supervisor, native authentication protocol, native source,
build script, verified binary/provenance and guest runner are staged explicitly. Trusted
worker broker modules are included because their package initializes those
imports; they are never guest uploads. The Node smoke SDK and tests are excluded,
and no separate worker service is configured.

When the complete live Sandbox supervisor suite passes, the worker creates
`exec_worker/vercel_sandbox/accepted-runtime.json`. The exact nonsecret file is
allowlisted when present. The operator must configure
`VCC_VERCEL_SANDBOX_ACCEPTANCE_PATH=exec_worker/vercel_sandbox/accepted-runtime.json`
and the independently recorded `VCC_VERCEL_SANDBOX_ACCEPTANCE_SHA256`. An absent
or mismatched artifact keeps execution disabled; packaging never fabricates it.

The built frontend is copied to `public/`, which Vercel serves from its CDN.
`api/index.py` imports the complete coordinator and appends the navigation fallback
after all existing routes. Existing HTTP and WebSocket routes keep their original
paths. Unknown `/api`, `/ws`, `/assets`, file-like paths and non-navigation
requests receive a real 404 or 405. The fallback serves HTML only for GET/HEAD
requests accepting HTML at an extensionless browser route. `frontend-index.html`
is the sole frontend file retained in the Python bundle; other static files are
excluded from the function bundle.

The accepted live layout uses framework `null`, `outputDirectory: public`, and
one `/(.*)` rewrite to `/api`; the ASGI runtime preserves original request paths.
The root FastAPI preset failed in the actual Vercel build. The file-based layout
passed live API, CDN, deep-link and private-path checks. Python is fixed to 3.12. Dependencies are
pinned in `runtime-requirements.txt`; staging renders the same pins into both
`requirements.txt` and `pyproject.toml`. Hypothesis remains because live
verification imports it; pytest and frontend build dependencies are excluded.

The function uses Seoul (`icn1`) alongside the inspected Supabase Seoul project
and a 300-second maximum duration. Native WebSockets require Fluid Compute and
close at that duration, so deployed reconnection behavior must be verified.

## Stage locally

Build the frontend from the isolated source with its installed dependencies:

```bash
cd /Users/dhaanish/.codex/worktrees/viva-zero-cost-deploy/VIVA/implementation/frontend
npm run build
```

Then use the project's Python 3.12 interpreter to stage into a new sibling
directory, keeping the generated inventory outside the upload:

```bash
python implementation/deployment/vercel/stage.py \
  --output /Users/dhaanish/.codex/worktrees/viva-zero-cost-deploy/upload-20261115 \
  --manifest /Users/dhaanish/.codex/worktrees/viva-zero-cost-deploy/upload-20261115.manifest.json
```

The script refuses to overwrite files, follows no permitted source symlinks,
rejects private/cache/database/audio paths, validates required assets and
detects source changes during the copy. It also enforces conservative source
limits of 95 MiB and 14,000 files. The inventory records every staged file's
size and SHA-256 hash. Review this exact package, secret hygiene and acceptance
results before uploading it. A frontend build should be repeated if its source
changes before staging; the script does not certify frontend build provenance.

## Deploy only the staged directory

The release operator must first finish PostgreSQL, durable coordination/audio,
Sandbox isolation and feature acceptance, and verify the actual Hobby/Free
accounts, spend cap, remaining quotas and no payment method. Configure server
credentials through Vercel's protected environment settings, never a staged
`.env` file or frontend variable. Production and preview must use explicitly
authorized storage namespaces and credentials. The application settings and
integration runbook define the final variable names.

The operator may link the staged directory to the existing `mentorly` project
and deploy the reviewed package through the Vercel CLI. CLI project metadata
must be local only and contain no credentials. Deployment protection and the
selected `mentorly-coach.vercel.app` domain require live verification. Avoid
temporary deployments, new projects, paid products and unverified upgrades.

After deployment, verify root/deep links and CDN assets in the built-in browser,
then test genuine unknown API errors, authorization, database persistence across
instances, SSE, WebSockets, provider voice and Sandbox execution. Capture the
deployment ID, package manifest and actual results. Revert to an accepted
deployment if validation fails; database compatibility must be checked before
rollback. This packaging work alone provides no accepted production baseline.

## Official platform references

Documentation was inspected on 2026-11-15:

- [FastAPI runtime, `public/` CDN, lifespan and custom entrypoints](https://vercel.com/docs/frameworks/backend/fastapi)
- [Python versions, dependencies and bundle exclusions](https://vercel.com/docs/functions/runtimes/python)
- [Native ASGI WebSockets and duration limits](https://vercel.com/docs/functions/websockets)
- [Function configuration and regions](https://vercel.com/docs/project-configuration/vercel-json)
- [Hobby upload, file and compute limits](https://vercel.com/docs/limits)

Current documentation supports ASGI WebSockets on all plans with Fluid Compute,
and a 300-second Hobby function limit. Account eligibility and application
behavior still depend on the operator's live checks.
