# Current production checkpoint — 16 November 2026

See [the authoritative release report](docs/engineering/PRODUCTION_RELEASE_20261116.md).

- [x] Reviewed integration committed and pushed; exact immutable artifact deployed.
- [x] Password reset verified; legacy workers drained and operational database fence checked.
- [x] Protected checkpoint restored locally; exact lineage, shared rows, ownership and source preservation verified.
- [x] Restricted target runtime, durable audio, retained uncertainty and expired request archives verified.
- [x] Existing production hostname promoted and public API/frontend hashes checked.
- [x] Final backend1764/skip41 and frontend945 results recorded; affected tests and independent reviews passed.
- [x] Idempotency, capability denial, deployed persistence and synthetic audio delivery checked.
- [x] Authenticated maintenance and daily scheduling configured; temporary acceptance token revoked.
- [ ] Observe the next scheduled maintenance invocation.
- [x] Retire the fenced legacy concurrency bridge with uncertain usage retained; pass the bounded real TTS/STT acceptance.
- [ ] Obtain provider evidence of the historical request outcome; it remains charged and unknown.
- [ ] Run genuine Linux/gVisor/Sandbox acceptance before enabling public custom-code execution.
- [ ] Complete full feature acceptance before merging integration into main.

## Historical checklist

> Historical workstream record. Current integration and acceptance status: [production integration checkpoint](docs/engineering/PRODUCTION_INTEGRATION_CHECKPOINT_20261115.md). This document does not certify the current candidate.

# Zero-cost release checklist

All unchecked until supported by current evidence.

- [ ] Reconcile concurrent working-tree changes and identify the exact reviewed candidate.
- [ ] Validate no secrets or private data in candidate; complete source and dependency checks.
- [ ] Verify Vercel Hobby, Supabase Free and any Render Free account, intended-use terms, quotas, payment status and automatic-charge behavior.
- [ ] Verify real Sandbox account entitlement, SDK, deny-all network and resource controls.
- [ ] Implement PostgreSQL migration for every module; verify durability, concurrency, session ownership, idempotency, deletion and rollback.
- [ ] Verify global Gnani coordination, conservative usage reservations, limits, stale-result handling and crash recovery across instances.
- [ ] Run target-platform adversarial execution and orphan cleanup acceptance; keep public execution disabled until passed.
- [ ] Verify live Gnani STT and TTS, English/Tanglish, REST, streaming, corrections, acknowledgements and interruptions.
- [ ] Verify HTTPS, permissions, previews, full Explain → Predict → Execute → Inspect → Repair → fresh case workflow, refresh and reconnect.
- [ ] Verify abuse controls, dependency failures, concurrent users, quota exhaustion and scheduled expiry.
- [ ] Record actual URLs, health, test evidence, usage and limits; verify no paid resource enabled.
- [ ] Rehearse and document rollback and operational ownership.
