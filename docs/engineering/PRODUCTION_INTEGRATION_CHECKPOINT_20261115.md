# Mentorly production integration checkpoint — 16 November 2026

Authoritative worktree: `/Users/dhaanish/.codex/worktrees/viva-integration-20261115`; branch `codex/integrate-snapshots-20261115`. The exact release identity is recorded by the immutable sibling artifact manifest, avoiding a self-referential commit hash in this document. Original worktrees and main are preserved; origin/main remains included in the candidate. No merge to main before release acceptance.

## Authorization and live state

The user waived staging, selected direct production, and authorized maintenance and a controlled Supabase database-password reset. Existing hostname remains `https://mentorly-coach.vercel.app`. No billing upgrade or paid infrastructure is authorized. Browser credential changes require user entry and submission. No production reset, role creation, schema creation, fence, migration, deployment or promotion has occurred in this integration continuation.

Fresh read-only production inventory matched the exact six historical migration checksums: 74 source tables, 11 sessions, 9 workspaces, 3 cloud audio objects, zero cleanup obligations and one expired UNCERTAIN speech lease. Vercel project remains mentorly/Hobby; Supabase is the existing Free project. These account checks are snapshots, not future usage guarantees. The legacy login owns the schema and bypasses RLS. Both reachable session-pool5432 and transaction-pool6543 logins were verified; the true IPv6 direct route is unreachable from this operator machine.

## Implemented integration and cutover

- Product/remediation snapshots retain drafts, workspace capabilities, ownership before provider contact, canonical contracts, creation idempotency, retry identity, cancellation and stale-result fencing.
- Model/STT/TTS use durable shared accounting. Unknown dispatch outcomes remain reserved; no automatic paid reissue or refund. Database markers do not stop external HTTP from paused workers; platform drain remains required.
- Mentor audio is authenticated PostgreSQL persistence with clip/global bounds and expiration. General TTS preserves and serves retained legacy bytes, subject to session lifetime. Daily authenticated cleanup is packaged but not deployed.
- Version100/101 initialize in a separate schema. The copy verifies exact legacy lineage, complete shared-table multiset equality and audio bytes; original tables remain intact. Stable timestamp/key ordering is deterministic and does not invent original chronology.
- New explicit uncertain-lease retention preserves all source fields and atomically occupies the actual Gnani single-slot account. The default still rejects outstanding leases; only expired UNCERTAIN speech can be explicitly retained. Voice stays blocked until external reconciliation. The prior bounded approval of one STT<=5seconds and one TTS<=200characters remains unused and cannot bypass that reservation.
- New operator preflight verifies rotated recovery credentials and old-password rejection on both pool routes before session termination, then uses fresh restricted target/runtime names and strict isolation checks. Global coordination namespace, DDL and RLS are created atomically; competing creation or existing unreviewed coordination aborts. No production credentials enter uploads.
- Public custom-code execution stays disabled. Retained Sandbox source and offline tests are not real Linux/gVisor acceptance.
- Packaging is allowlisted, rejects private files/symlink ancestors and records exact source/output hashes. Prior fb5ccf5 immutable artifact passed seven sanitized packaged-ASGI smoke checks. The changed migration/operator source requires a fresh committed artifact before cutover.

## Verification and protected checkpoint

A protected 2,893,111-byte pg_dump was restored into an owned local database. All 74 live-source table counts and full-precision typed row multisets matched. The original dump is unchanged; the PG18 dump header's transaction_timeout SET was omitted only from the PG16 local restore stream. No source SQL/data was changed.

The restored real-production snapshot migrated locally: 71 shared tables, 123 rows, 3 retained WAV objects and 1 retained uncertain lease. Two independent actual AccountDispatcher instances refused new reservations. This is local real-data preservation evidence, not a deployed migration or provider acceptance. Backups and comparison reports are owner-only files in sibling `mentorly-cutover-private-20261116`, outside Git and release uploads.

- Complete backend/worker/Sandbox-source run: 1738passed,41skipped,2warnings. Final operator/isolation checks after the last capability-classification adjustment:36passed. Exact artifact verification is recorded in the sibling release status file.
- Current frontend: 945passed across60files; typecheck, lint and production build pass. System Node26 has an incompatible experimental WebStorage default; verified run uses Node24 with `--no-experimental-webstorage`. Monaco large-chunk warning remains.
- New focused legacy/account tests:21passed; new operator tests:13passed, plus a real isolated local SCRAM rejection rehearsal. Independent reviews examined lease preservation, RLS creation race, runtime isolation and narrow libpq rejection handling.
- Secret hygiene:0violations. No new provider calls, production mutations or password resets occurred.

## Next execution boundary

Bind the reviewed source to a committed, pushed exact-commit immutable artifact and record its final verification in the sibling release status file. Use the direct-production procedure in `PRODUCTION_LEGACY_MIGRATION_RUNBOOK.md`. The user must personally enter and submit the protected planned password through Supabase's reset control. Then verify recovery and old credential rejection, establish/drain the actual platform fence, take a final frozen checkpoint, copy and reconcile, configure restricted runtime, deploy and verify before reopening the unchanged hostname.

After target writes, recover forward using the same schema and a reviewed compatible artifact. Reverting to the old-schema app is unsafe; reverse reconciliation is not implemented. Still pending: live reset/fence and provider quiescence, production migration/deployment, deployed workflow/audio/ownership/cron checks, real voice reconciliation/acceptance and actual sandbox acceptance. Do not label production deployed or complete before those occur.
