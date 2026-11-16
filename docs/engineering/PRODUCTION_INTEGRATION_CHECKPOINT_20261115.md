# Mentorly production integration checkpoint — 15 November 2026

Authoritative integration worktree: `/Users/dhaanish/.codex/worktrees/viva-integration-20261115`, branch `codex/integrate-snapshots-20261115`. HEAD remains `4152299eee61e11ff57dba241400f71e78b37cf2`; substantial reviewed changes are uncommitted, so this is not an exact-commit release. Original worktrees and Git main are preserved. A 740-file source/hash checkpoint was saved before the expanded directive in sibling `viva-integration-checkpoint-20261115-user-directive`.

## Authorization and release state

The user's complete directive is the governing release scope. Production database changes, write freeze, hostname changes, promotion and traffic redirection require explicit approval of the final artifact and cutover plan. None has occurred. One bounded staging Gnani test is authorized: at most one STT request up to five seconds and one TTS request up to 200 characters, after isolation and quota checks. It has not been consumed.

Production continues using the legacy six-migration schema. Read-only checks matched all six checksums. Its credential owns the application schema and bypasses RLS; it must never be used by Preview. The existing Vercel project is `mentorly` on Hobby. Existing production hostname is retained; preferred `mentorly.vercel.app` is not authorized as a hostname change.

## Implemented integration

- Product/remediation source reconciled with persisted drafts, workspace capabilities, foreign-session checks before provider contact, hook-order and accessibility fixes, canonical contracts and explicit environment selection.
- Codebase model/STT/TTS use shared durable quota accounting, serialized request identity, stable creation retries and durable dispatch fences. PREPARED work can be fenced safely. Possibly dispatched or lost completed work retains uncertain accounting and blocks automatic paid reissue. A marker cannot stop an already-running worker from initiating external HTTP; operator reconciliation requires verified shutdown/provider outcome. Legacy unfenced requests remain a manual investigation case.
- Mentor audio is database-backed, authenticated, bounded per clip and globally, expires after 24 hours, and participates in fenced maintenance. PostgreSQL general TTS caching replays retained legacy WAV through an independently created application instance, enforces new cache bounds, and retains historical bytes until session deletion/expiry. Scheduled maintenance endpoint and daily Vercel cron template are implemented; scheduling is not deployed.
- Migration prototype verifies legacy checksums and shared rows, preserves opaque legacy audio, rejects outstanding provider leases, and supports restricted-role persistent fencing. Forward rehearsal hashes all ordinary-table row multisets across application instances and verifies HTTP workflows. It is not an arbitrary code-defect recovery or downgrade proof. See `PRODUCTION_LEGACY_MIGRATION_RUNBOOK.md` for exact limitations.
- Deployment snapshot sandbox source/tests are retained. Acceptance CLI fails closed for unreconciled cleanup/runtime schema. Public custom-code execution remains disabled. Offline tests and skipped tests do not establish real isolation.
- Packaging builder rejects private inputs and symlink ancestors, records actual source hashes/dirty status, and retains native source. Diagnostic artifacts are explicitly nonproduction. A real sanitized package startup test found an omitted required defaults file; packaging correction and repeat smoke are in progress.

## Evidence (candidate runs, not final release acceptance)

- Latest complete backend/worker/Sandbox run: 1,682 passed, 41 skipped, two warnings, disposable local PostgreSQL. Log `/tmp/mentorly-release-backend-final2.log`. Skips include genuine Linux/gVisor acceptance and unreconciled legacy Sandbox cleanup/limit tests; execution stays disabled.
- Clean frontend installation: npm ci --ignore-scripts; audit reported zero vulnerabilities. Full suite: 945 passed in 60 files, followed by passing typecheck, lint and production build. Large Monaco chunk warning remains.
- Additional forward-recovery/legacy rehearsal: 11 passed; dispatch subprocess tests: 13 SQLite tests and three PostgreSQL tests; scheduled maintenance: three PostgreSQL tests; TLS fail-closed regressions: five passed.
- OpenAPI check, canonical TypeScript drift check, six mutation probes, secret hygiene and uv pip compatibility check passed before the final packaging/config edits.
- Old test socket55449 disappeared; release now owns an independent disposable PostgreSQL cluster on socket `/Users/dhaanish/.codex/worktrees/mentorly-release-pg-u0fwhww7/socket`, port55459. Its DSN and root are in `/tmp/mentorly-release-test-pg.json`. Never substitute production credentials.

## Remaining acceptance

Finish immutable package startup/configuration validation; finish restricted staging role provisioning/verification without production-capable credentials; bind exact source to a reviewed commit and artifact; rerun affected checks; provision/deploy isolated Preview only within the user's live-database approval boundary; exercise deployed workflows, scheduling, persistence, cancellation and bounded authorized Gnani test; verify actual free-tier usage. Produce the reviewed cutover/forward-recovery proposal. Do not label READY FOR PRODUCTION APPROVAL until every required gate is demonstrated. No staging URL is verified yet.
