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
