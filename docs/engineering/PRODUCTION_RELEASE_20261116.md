# Mentorly production release — 16 November 2026

**Live:** https://mentorly-coach.vercel.app  
**Application commit:** `6075e994b5df328d1626efd408d75f910b98cada`  
**Deployment:** `dpl_5Z7VWaG86oqX4rsKGrmTBRjUjsrz` (`READY`, promoted; alias independently verified).  
**Integration branch:** `codex/integrate-snapshots-20261115`; pushed. Subsequent documentation commits do not change the deployed application artifact. Git main is preserved pending complete feature acceptance.

## Practice and voice incident follow-up — 16 November 2026

The exact `ex4_sum_even?spec=v1_typed_bounded` page reproduced an internal error. Live SQL tracing found PostgreSQL42P01 on an unqualified sessions query: transaction pooling did not retain the adapter's autocommit SET search_path. The dedicated runtime role now has startup defaults for the application schema, UTC and bounded statement/lock timeouts. Raw pooled connections resolve the schema without SET. Provisioning now installs these defaults; 13 focused operator regressions passed and independent review approved the change. Application bytes remain6075e99; operator fix5bab970 is pushed.

A fresh deployment `dpl_7GBxTS3qUxqa2CR2YF26us7PteTe` serves the existing hostname, replacing cached application connections. The deployed voice endpoint returned200 and176444 WAVbytes matching real provider audio. The exact browser page's Test voice action removed the internal-error banner and displayed Voice playing with the correct spoken transcript.

The imported legacy concurrency bridge was explicitly retired as an operator risk decision after old worker/transport shutdown. This was not automatic TTL recovery or proof that the provider completed the old request. Its unknown183-character/one-call charge and original archives remain unchanged. Only that precisely matched legacy bridge was released; account capacity remains one.

Bounded real acceptance used one64-character TTS request and one4.0-second REST STT request, with retries disabled. Both passed. STT transcript: “Voice is ready, you can change the volume or continue with text.”. The browser/deployed Test voice replay used the resulting shared cache. These results establish the bounded real voice path, not every microphone/device/language combination. The original blocked-voice state described below is historical; public custom-code execution is still disabled.

## Delivered behavior

The complete integrated frontend and PostgreSQL coordinator now serve the existing hostname. The old `ADMISSION_UNAVAILABLE` / “Service is busy; retry shortly.” response was traced to unavailable legacy database authentication after the authorized reset. Public health, catalog, persisted lessons and frontend assets now return successfully. Browser validation loaded the dashboard and its existing saved practice drafts.

Repository publication now stages bounded rows before its write lock and pipelines file, chunk, FTS and optional evidence-card batches. Named prepared statements are disabled for Supabase transaction-pool compatibility. This avoids serial remote round trips while holding the application write lock. A synthetic 10-file ZIP imported through the deployed API reached READY in 2.06 seconds; public health returned 200 after READY. This is one small acceptance fixture, not a large-repository or concurrent-load benchmark. An earlier full-corpus operator-side synthetic check held the global lock and was explicitly interrupted/rolled back; its owned import was marked INTERRUPTED. No production user record was removed by that intervention.

The existing shared admission-lock protocol was retained. A proposed lock split was rejected after an independent mixed-version test demonstrated two admissions against a limit of one. Old and new same-schema deployments therefore keep coordinating through the same lock during promotion.

## Production data and cutover

The user waived staging, approved direct production and maintenance, and personally submitted Supabase's supported password reset. The replacement administrator worked on session and transaction pool routes; old credentials were rejected on both. The true IPv6 direct endpoint was unreachable from the operator machine, so no direct-route acceptance is claimed.

Legacy Vercel functions were drained beyond their 300-second maximum. Prior database sessions were terminated. Supavisor recreated one pristine idle pool backend: an independently reviewed operational classifier allowed only post-cutoff, never-queried Supavisor prewarm connections with null transaction/query start times; seven classifier checks passed. This relies on the inventoried legacy worker shutdown and is not a universal revocation proof for arbitrary preauthenticated pooler frontends. Authenticated access to the old immutable deployment failed, and the public old app returned ADMISSION_UNAVAILABLE. Unknown upstream speech remained reserved throughout.

A protected pg_dump was restored locally and all 74 initial source-table counts and full-precision row multisets matched. A final readable custom-format checkpoint was taken after drain. Original `viva_app` remains intact. The fresh target is `mentorly_prod_v100_20261116`; application objects remain administrator-owned and `mentorly_prod_v100_20261116_runtime` has restricted application/account privileges, without database or schema CREATE or ownership. Shared coordination RLS was installed atomically only on freshly created objects; existing PUBLIC permissions were not revoked globally.

The copy verified the exact six historical checksums and full shared-row multiset equality inside source locks. Copy-time result: **71 shared tables, 95 rows, 1 retained legacy WAV, 1 uncertain speech lease, and 2 expired HELD request leases**. All lease fields were retained exactly in `legacy_cloud_leases`; source rows were unchanged. Only the speech lease occupies provider capacity. Pre-HTTP integrity fingerprints cover all 96 target tables.

The initial checkpoint contained three audio cache entries; two were absent from the final live source before copying, both older than the legacy 24-hour TTL. The migration copied the one still present. Original bytes of all three remain in the protected initial backup; no source audio deletion was performed by the migration. This distinction is recorded rather than claiming all three remained live.

Native schema SQL checksums:
- `runtime_schema.sql`: `cad8d52e59e742c06a9df7d870d72a7fb8a212d0aeaa17754c2e938d1315a5a2`
- `shared_tts_audio.sql`: `996e7048414fc72a49387658dcfb032b926023002259244fa3ee1377ee51fc01`

## Artifact and verification

The immutable upload has 255 allowlisted files. Manifest SHA-256: `dbf34585a41fa523de240c6fef6d932e1dcde50f5630613ceb3c78eb14a8abb0`. Secrets, production data, tests and private operator artifacts are outside the upload. Vercel's includeFiles expression was shortened to its supported limit and checked by a packaging regression.

- Final backend, worker and Sandbox-source suite: **1,764 passed, 41 skipped, 2 warnings**, 121.77 seconds. Exact application source; log `/tmp/mentorly-final-batched-production-suite-20261116.log`.
- Frontend: **945 passed in 60 files**, typecheck/lint/build passed; frontend bytes are unchanged by the backend fixes. Verified Node24 with experimental WebStorage disabled; system Node26's incompatible test default was not treated as an application defect. Monaco large-chunk warning remains.
- Independent batch/publication review: 19 focused tests passed. Additional migration/retention, role and packaging regressions passed in their recorded workstreams.
- Public HTTPS health/catalog/dashboard and exact JS/CSS asset hashes passed. Unknown API/private source paths returned404. Unauthorized maintenance returned403; authenticated maintenance returned200/complete.
- Workspace creation replay was idempotent. A foreign capability was denied. An owned lesson persisted across two distinct deployed applications using the target database.
- A valid **synthetic silent WAV**, seeded only into the owned acceptance workspace without provider calls, was served byte-for-byte from two distinct deployments. A foreign token received401. This proves deployed durable/private audio delivery, not real Gnani synthesis or human listening acceptance.
- Daily maintenance is configured at `0 2 * * *` (07:30 India time). Platform configuration and manual authenticated execution were verified; the next scheduled invocation has not yet been observed.
- Production project variables now use the restricted target URL/schema and CRON_SECRET. The temporary deployment-protection acceptance token was revoked after testing. Existing deployment protection remains enabled.

## Remaining limitations

One historical Gnani TTS request remains uncertain: **183 characters / one call**, charged conservatively. There is no saved provider request ID or matching WAV proving completion. Its shared single-account reservation remains occupied; no refund, automatic retry or paid acceptance call was made. Real STT/TTS acceptance is therefore still blocked pending provider-log reconciliation. The previously approved bounded STT/TTS test remains unused. Official Gnani batch-STT status endpoints are not evidence about this TTS call.

Public custom-code execution remains **DISABLED**. The 41 skips include external Linux/gVisor acceptance and unreconciled legacy Sandbox cleanup/limit tests; offline passes do not establish genuine sandbox isolation. Hosting uses the existing Vercel Hobby and Supabase Free resources, with no paid upgrade or duplicate cloud project. Database size was approximately29MB after cutover; future usage and provider credits still require normal monitoring.

Core deployment is live and verified. Full voice/Sandbox acceptance and the associated merge-to-main gate remain incomplete; this report does not claim every feature is accepted.

## Recovery

After target writes, preserve this target schema and recover forward with a reviewed schema-compatible artifact. Distinct deployed applications have read post-cutover lessons/audio successfully, but arbitrary code-defect recovery and an old-schema downgrade are not proven. Never promote the original `viva_app` application over the new target, recopy source over target writes, or resolve the uncertain provider reservation based only on age.

Protected backup, fence, reconciliation, HTTP and token-revocation evidence remains locally outside Git in `mentorly-cutover-private-20261116`. The original worktrees and previous deployments remain available.
