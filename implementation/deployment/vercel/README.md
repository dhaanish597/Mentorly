# Mentorly Vercel release packaging

Current release acceptance is recorded only in [the integration checkpoint](../../../docs/engineering/PRODUCTION_INTEGRATION_CHECKPOINT_20261115.md). The templates here are executable packaging inputs; their presence does not certify a deployment.

Build and validate the frontend from a clean dependency installation. From the repository root, `python implementation/scripts/build_vercel_release.py --output /private/new-release-directory` creates an allowlisted upload plus a SHA-256 manifest. The default requires committed inputs. `--allow-dirty` is for diagnostic artifacts only and explicitly prevents an exact-commit production claim. Never upload the working checkout directly.

The package uses a Python 3.12 ASGI entry point, CDN frontend files, preserved API routes and guarded browser navigation fallback. Runtime configuration must select a shared PostgreSQL database; remote PostgreSQL requires `sslmode=verify-full` and a trusted CA. Supply credentials through the deployment environment only. Preview must use an independently verified restricted role with no access to production tables, sequences, privileged functions or provider coordination records. A different schema/search path with an administrator credential does not establish isolation.

The daily maintenance cron calls `/api/v1/ops/maintenance`. Set protected `CRON_SECRET` equal to `VCC_OPERATIONS_TOKEN`; the handler authenticates before resolving storage. Daily cron activation is production-only on Vercel. Preview must exercise the handler explicitly with synthetic data, including expiry and repeated runs. The daily schedule means physical expiration cleanup may lag logical expiry by one day; expired audio retrieval is denied immediately.

Keep `VCC_ALLOW_PUBLIC_CUSTOM_CODE=false`. Restored Sandbox sources are retained for independent acceptance; missing compatible cleanup/runtime migrations and real adversarial isolation acceptance make public activation unavailable. Genuine execution is never replaced with an unsandboxed fallback.

Before any deployment, bind source, generated contracts, dependency locks and package manifest to the reviewed commit. Before production database changes, write freeze, promotion or hostname/traffic changes, obtain the user's explicit approval of the exact artifact and cutover/recovery plan. Historical production remains on its existing hostname until separately approved.
