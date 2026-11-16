> Historical workstream record. Current integration and acceptance status: [production integration checkpoint](docs/engineering/PRODUCTION_INTEGRATION_CHECKPOINT_20261115.md). This document does not certify the current candidate.

# Zero-cost deployment audit

Audit date: 2026-11-15 (Asia/Kolkata). This is an inspection of the existing checkout, not a release attestation. Live cloud and acceptance results are recorded separately in DEPLOYMENT_STATUS.md.

## Repository and preservation

The requested `/Users/dhaanish/Documents/VIVA` is absent. The open checkout `/Users/dhaanish/Desktop/VIVA` has remote `https://github.com/dhaanish597/Mentorly.git` and contains the requested `GNANI_BUILD_HANDOFF_BUNDLE/IMPLEMENTATION_PLAN.md` and its audit. No applicable AGENTS.md was found in its ancestor chain or repository. The handoff bundle is ignored by Git; do not assume a clean clone contains it. At the first inspection HEAD was `54c0a1100f5894ce70460d68ee21e32a857ba993`, branch `main`, with 81 modified/untracked entries. During this audit the branch changed externally to `engineering/full-product-integration-20261115` at the same HEAD and files continued changing. Treat counts and test runs as snapshots, not an immutable release identity. Do not reset, stash, overwrite or push this work without reconciling the concurrent work. The tree contained 571 tracked files and 17 untracked nonignored files at initial inventory. Dependencies, ignored local databases, audio, .env, build outputs, archives, virtual environments and Git metadata are not deployment inputs to publish.

## Implemented surfaces and gaps

The React 18/Vite frontend, FastAPI application, exercise registry and trusted references, versioned sessions, speech adapters, practice workflow, interview, curriculum and repository-learning modules, and existing gVisor worker are present. Presence or unit tests do not establish every acceptance criterion. The source includes REST and WebSocket speech paths and HTTP streaming paths. Real provider access, language quality, browser microphone behavior, complete end-to-end flows and isolation on the target platform require fresh live evidence. Existing status documents refer to earlier source snapshots; the authoritative handoff specifies scope, not current completion.

The existing persistence layer is SQLite throughout, including `backend/app/db/repository.py`, migrations, learning, interviews, speech usage, admission, retention and repository learning. SQL syntax, transaction semantics, backups, migration history and ownership checks require a deliberate PostgreSQL port across all modules, not an environment-variable swap. `main.py` starts retention tasks during lifespan and recovers reservations on startup; ephemeral instances cannot guarantee scheduled cleanup or safely assume all other instances stopped. Shared speech coordination, local inflight tracking and locks must be replaced with transactional distributed leases, fencing and bounded durable reservations. SQLite files and the local TTS cache cannot be treated as durable on Vercel.

Execution uses a separate local worker with a dedicated Docker/runsc trust model and identity-bound acceptance checks. Preserve it. Vercel Sandbox requires a new independently reviewed adapter and an actual target-account adversarial acceptance run; do not enable custom execution until that passes. Trusted references and comparison remain outside the untrusted sandbox. SDK documentation or a mocked test is not an isolation acceptance.

## Deployment-related files and services

- `implementation/backend/app/main.py`, `core/config.py`, `db/`, `operations/`, `speech/`, `studio/`, `learning/`, `interviews/`, and `repo_learning/`: persistence, lifecycle, concurrency, authorization and quotas need review and migration.
- `implementation/exec_worker/` and `backend/app/orchestration/worker_client.py`: retain existing worker; add a separately gated sandbox adapter and cleanup/reconciliation.
- `implementation/frontend/`, Vite proxy/API configuration, CSP, microphone and WebSocket handling: validate on the actual HTTPS origin; preserve configurable `implementation/config/branding.json`.
- `implementation/.env.example`, `implementation/docker-compose.yml`, `implementation/deployment/`, `implementation/docs/DEPLOYMENT.md`, generated OpenAPI/TypeScript contracts, operational scripts and tests: adapt only when the corresponding architecture is implemented and verified.
- Services and secrets: Vercel account/project, Supabase project and database connection, Gnani credentials and verified credit balance, optional Render service, protected internal credentials. Never publish `.env`, database dumps, provider keys, transcripts or audio.

No Vercel or Supabase CLI was found on PATH in this shell; Render CLI is present. The currently available Vercel browser session showed a login page, so Hobby entitlement, billing state and Sandbox access remain unverified for this account. Render CLI authentication was observed, but that does not establish a service or its billing configuration. Account status must be rechecked before provisioning.

## Test snapshot

See DEPLOYMENT_STATUS.md for actual commands and results. Tests during an actively changing working tree do not certify a specific immutable revision. Run complete suites again against a frozen deployment candidate.

## Blocking release gates

1. Current account authentication and verification of all selected free plans, no payment method/automatic charges, account-specific Sandbox entitlement, quotas and intended use.
2. PostgreSQL parity, migrations, ownership and distributed coordination with concurrency/failure tests; scheduled deletion and reconciliation independent of function lifetime.
3. Real disposable Sandbox security and cleanup acceptance on the target plan, including network, filesystem, resource and cross-session attacks.
4. Actual HTTPS deployment, public health, live Gnani STT/TTS, supported streaming behavior, full browser workflow, recovery, measured free-tier usage and rollback.
5. Reconcile concurrent work, inspect the exact source to be pushed, remove secrets and private data, then validate the candidate. No deployment or push has been performed as part of this audit.

## Current provider documentation (not account verification)

- [Vercel Sandbox pricing](https://vercel.com/docs/sandbox/pricing) lists Hobby allowances of 5 CPU-hours, 420 GB-hours, 5,000 creations, 20 GB transfer and 10 concurrent sandboxes, with a 45-minute maximum; exceeding the Hobby allowance pauses creation instead of charging additional usage. Actual account access and remaining balance were not established.
- [Sandbox SDK](https://github.com/vercel/sandbox/blob/main/README.md) documents OIDC and token-based credentials. Current [Sandbox documentation](https://vercel.com/docs/vercel-sandbox/concepts/firewall) must be checked against the installed SDK and actual account; deny-all networking is a requirement, not a completed test. CPU configuration alone is not evidence of an independently enforceable memory limit.
- [Vercel WebSockets documentation](https://vercel.com/docs/functions/websockets) and [beta announcement](https://vercel.com/changelog/websocket-support-is-now-in-public-beta) describe WebSocket Functions. The documented integration and runtime support must be tested for this Python app; connection lifetime and reconnection remain design constraints. [Function limits](https://vercel.com/docs/functions/limitations) list a 300-second Fluid Compute limit on Hobby.
- [Vercel terms](https://vercel.com/legal/terms) restrict Hobby to personal, noncommercial use. Applicability to this specific prize-bearing demonstration is not established; do not represent it as approved.
- [Supabase pricing](https://supabase.com/pricing) lists Free project and resource allowances; inactivity pause and backup limits require operational planning. An explicit no-card signup guarantee was not located.
- [Render Free documentation](https://render.com/docs/free) lists 750 free instance-hours per workspace and spin-down after 15 minutes idle, with approximately one-minute wakeup. A payment method can change overage exposure; confirm actual billing state. [WebSocket documentation](https://render.com/docs/websocket) describes WebSocket support.

The current account browser redirected both Vercel and Supabase dashboards to login. Render authentication was observed; no provider plan, payment method, actual usage or no-card eligibility was proven. No services were created.

## Signed-in account check, 15 November

The user provided signed-in browser sessions after the initial audit. Vercel shows the `dhaanish597s-projects` scope as Hobby and an accessible Sandbox onboarding page, but creation, isolation, quota availability and billing state were not tested. Supabase shows a Free organization and an existing healthy `Mentorly` project on Nano in Seoul; the dashboard reports no migrations or backups. Current-cycle organization usage shows 26 / 500 MB database and 0 / 5 GB egress. Do not assume the database is empty or overwrite it. No account or project changes were made during this check. This supersedes the earlier statement that browser login was unavailable.

## Read-only Supabase inventory on continuation

On 15 November, dashboard inspection and read-only catalog/aggregate SELECTs found no tables, partitioned tables, views or materialized views in the inspected non-system/non-Supabase namespaces; `public` has no tables or views and no policies. `auth.users`, `storage.buckets`, and `storage.objects` each reported zero rows. The `public` schema has one security-definer database function, `rls_auto_enable`; the Edge Functions dashboard showed no deployed functions. Managed Supabase/system namespaces were excluded from the application-table inventory, so this is not a claim that every system object is absent. Preserve the existing function and all managed objects. No remote schema/data change was made. Explicit user approval is required before applying an exact migration.
