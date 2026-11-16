> **Live release, 16 November 2026:** [current production report](docs/engineering/PRODUCTION_RELEASE_20261116.md). The integrated application is live at https://mentorly-coach.vercel.app. Historical plans and evidence follow; real voice acceptance passed in the follow-up; genuine Sandbox acceptance remains incomplete.

> Historical workstream record. Current integration and acceptance status: [production integration checkpoint](docs/engineering/PRODUCTION_INTEGRATION_CHECKPOINT_20261115.md). This document does not certify the current candidate.

# Deployment runbook (preparation only)

No deployment is currently approved by technical acceptance, and no commands here assert one exists. Do not enable paid billing, supply payment details, or expose custom execution before the gates below pass.

1. Confirm the exact source revision and preserve concurrent uncommitted work. Run the existing repository checks and secret scan on that exact candidate. Never commit `.env`, keys, databases, user data, audio, or private artifacts.
2. Authenticate to Vercel and Supabase without sending credentials to chat. Inspect actual organization, project, plan, spending/usage and enabled features. Stop before any payment, trial or automatic charge. Record evidence of zero-cost eligibility; do not infer it from documentation.
3. Complete and verify the PostgreSQL migration, atomic cross-instance coordination, ownership and retention. Back up and rehearse rollback; do not point existing SQLite code at an ephemeral disk and call it persistent.
4. Test the proposed Sandbox implementation on the selected account. Keep public custom-code execution disabled until the real deployed adversarial isolation suite, cleanup and reconciliation pass against the exact candidate and configuration.
5. Configure Vercel project root, protected environment variables, frontend build, API, exact origins and HTTPS only after the implementation exists. Determine whether the actual streaming runtime works; otherwise assess an authenticated Render Free bridge without upgrading the account. Do not expose provider or service-role credentials to the browser.
6. Run live production checks for health, persistence, ownership, expiry, versioning, all coaching steps, microphone, Gnani STT/TTS and stream, concurrency, quota exhaustion, cancellation, restart and isolation. Record source revision, platform identities, commands, results, times and measured usage. A mocked provider is not a live acceptance test.
7. If anything fails, disable public execution, stop traffic where possible and revert to the last known accepted frontend/API and compatible database version. Restore only from a verified private backup into a separate target after confirming migration compatibility. No rollback has yet been rehearsed on this architecture.
