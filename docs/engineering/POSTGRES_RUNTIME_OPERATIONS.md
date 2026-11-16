# PostgreSQL runtime, transfer and maintenance

15 November 2026. This is the isolated remediation implementation. No remote
migration, live provider test, production cutover or deployment was performed.

## Runtime selection and installation

Install the backend with its optional PostgreSQL driver:

```sh
python -m pip install './implementation/backend[postgres]'
```

Supply `VCC_DATABASE_URL` through the deployment's secret manager or an explicit
private `VCC_ENV_FILE`; it must be a PostgreSQL URL. `VCC_DATABASE_SCHEMA` defaults
to `viva_app` and must name a dedicated schema. Do not put a connection URL on a
command line, in source control, in screenshots or in logs. `DATABASE_URL` is not
an ambient alias; the application consistently uses the explicit `VCC_` setting.
The cloud runtime rejects a missing shared database rather than creating SQLite.

The application now selects PostgreSQL in FastAPI startup, repository methods,
learning/interview/repository/Studio services, workspace recovery, speech and
model accounting, admission counters and retention. Existing SQL contracts use
an audited PostgreSQL dialect adapter. Bound parameters remain bound, exception
messages omit private SQL values, and aggregate numeric values preserve API
number types. SQLite is still the local backend when no URL is selected.

`runtime_schema.sql` is checked into the backend package and migrates as version
100 with checksum verification. Its offline generator initializes a pristine
temporary SQLite schema including the speech ledger's legacy columns; it does
not read learner data or call a provider. Once this migration has been deployed,
freeze it and append later PostgreSQL migrations. Never regenerate a published
migration in place.

PostgreSQL `BEGIN IMMEDIATE` operations take a schema-scoped advisory transaction
lock. This preserves current serialized write semantics and cross-process
accounting. Selecting PostgreSQL does not establish higher write throughput.
Direct database writers must obey the same transaction and ownership rules.

## Private SQLite export, cutover and rollback

The transfer commands are private operator tools, not public import endpoints.
Use a source database migrated by this exact source revision, with its runtime
speech columns initialized. The target application schema must be empty and its
schema must exactly match the export. Incompatible or nonempty targets are
rejected without overwriting data.

1. Stop writes and provider dispatch on every source coordinator. Resolve or
   retain outstanding jobs and provider uncertainty; never refund an unknown
   paid request. Keep the original SQLite database, WAL and verified backup.
2. Export using SQLite's online backup API. It captures a coherent WAL snapshot,
   checks integrity and foreign keys, and writes an atomic private file with mode
   `0600`. Treat this file as private learner data, even though capabilities are
   stored as hashes.
3. Provision the dedicated PostgreSQL target using an already authorized
   deployment account. Supply its URL via a private explicit environment file.
4. Import while target coordinators are stopped. All authoritative rows, quota
   history, tombstones, cleanup obligations and hashed recovery capabilities are
   preserved. Search indexes are rebuilt. Counts and SHA-256 hashes reconcile
   every table before the import transaction commits. A rerun accepts the same
   import only if all data still reconciles; a changed target is rejected.
5. Start the exact verified revision against PostgreSQL, configure scheduled
   retention, verify ownership/recovery and product HTTP acceptance, then switch
   traffic. Keep dispatch and custom execution closed until their acceptance
   gates pass.

From the repository root:

```sh
PYTHONPATH=implementation python implementation/scripts/storage_transfer.py export \
  --source /private/source/vcc.db --output /private/backups/viva-transfer.json

VCC_ENV_FILE=/private/postgres.env PYTHONPATH=implementation \
  python implementation/scripts/storage_transfer.py import \
  --snapshot /private/backups/viva-transfer.json
```

The tool never performs cutover. Before PostgreSQL accepts new writes, rollback
is a routing/configuration change back to the preserved SQLite source revision
and database. After PostgreSQL has accepted new writes, the frozen SQLite source
is stale: stop traffic and reconcile those new records before rollback. This
implementation does not provide a lossless reverse transfer, so do not switch
back blindly. PostgreSQL disaster recovery must use the hosting provider's
private backup/PITR facilities and an independently tested restore procedure.
The legacy `operations.backup` helper remains specifically a SQLite tool.

## Separately scheduled retention

PostgreSQL ASGI startup deliberately does not start one retention loop per
worker, recover another worker's imports, or refund another worker's active
reservations. Schedule the following command separately at the retention cadence
required by the deployment policy (the previous interval was 60 seconds):

```sh
VCC_ENV_FILE=/private/postgres.env PYTHONPATH=implementation \
  python implementation/scripts/run_retention.py
```

The job takes a PostgreSQL server-time lease with a generation fence, bounds its
sweep to 90 seconds and returns `COMPLETE`, `BUSY` or `RETRY_REQUIRED`. Overlapping
runs return `BUSY`; expired owners cannot mutate data after another owner claims
the lease. Monitor nonzero exit status, errors, pending audio cancellation and
unconfirmed broker cancellation counts. Retry unresolved cleanup; do not mark it
complete merely because a timeout elapsed. Imported cleanup obligations survive
process restarts.

The scheduled owner also marks passive repository imports older than ten minutes
as `FAILED`/`INTERRUPTED` in bounded batches. It reports `recovered_imports`.
The existing status comparison at every progress update and final transaction
prevents a paused parser from publishing after recovery; indexed rows roll back
if the final state is obsolete. This is a total import age deadline, including
time spent waiting or paused. It does not stop a parser's physical thread.
Fresh imports are left alone. The source ZIP bytes are not retained durably, so
the user must retry or upload again after interruption; no missing source is
invented. Paid provider reservations are never freed by this recovery step.

## Shared provider account admission and recovery

All coordinators using the same Gnani credential and PostgreSQL database share
`viva_provider_coordination` account slots. The account ID is a one-way credential
digest. Agreed capacity starts at one and is the minimum of configured requested
and verified concurrency. A differing coordinator configuration fails closed.
Other machines, chats or deployments using the account must share this same
dispatcher; independent databases cannot coordinate an account-wide limit.

Undispatched expired leases may be reclaimed. A dispatched or uncertain lease
stays occupied until matching fenced completion confirms it is finished. TTL
alone never establishes that a paused worker or remote WebSocket is quiescent.
This can deliberately leave speech busy after a crash. Retained usage remains
counted; resolving an infrastructure slot never refunds the usage ledger.

Private inventory, without provider calls:

```sh
VCC_ENV_FILE=/private/postgres.env PYTHONPATH=implementation \
  python implementation/scripts/provider_lease_admin.py list
```

To change verified capacity: stop every coordinator using this account, close
provider sockets and verify entitlement and quiescence. Resolve outstanding
leases only after observing completion. Then update capacity atomically using
the expected previous value:

```sh
VCC_ENV_FILE=/private/postgres.env PYTHONPATH=implementation \
  python implementation/scripts/provider_lease_admin.py capacity --current 1 --new 2 \
  --workers-stopped-and-entitlement-verified
```

The database rejects a capacity change with any active or uncertain lease. Old
workers reject admission under their obsolete capacity. Update requested and
verified settings consistently on every worker before restarting them.

For a stranded lease, independently establish that its provider work has ended
and its original worker cannot resume dispatch. Use the inventory's exact ID and
fence; the command refuses stale or foreign completion:

```sh
VCC_ENV_FILE=/private/postgres.env PYTHONPATH=implementation \
  python implementation/scripts/provider_lease_admin.py resolve \
  --lease-id VERIFIED_LEASE_ID --fence VERIFIED_FENCE --provider-quiescence-confirmed
```

These acknowledgements require operator evidence; they are not evidence by
themselves. Never use resolution to bypass the provider's entitlement.

## Acceptance boundary

Disposable PostgreSQL 16 with a private Unix socket passed 105 integration cases
after the final source changes, including real HTTP learning,
interview, repository and recovery assertions; process-shared admission and
provider caps; generation-fenced maintenance and interrupted import recovery;
and private export/import with reconciliation and rollback on conflict or a
rejected private row. Two offline SQL dialect regression tests passed. Ruff and
the reviewed diff passed. The backend wheel contains the checked-in SQL schema
and optional PostgreSQL driver metadata. Aggregate command results are recorded
in `/tmp/viva-remediation-pg-complete-final.log`; the parent remediation evidence
bundle should preserve that log with the final source delta.

Mock audio verifies accounting and ownership without assessing actual speech
quality. Live Gnani/Groq entitlement, provider cleanup, Linux/gVisor execution,
distributed job lifecycle, restart/kill acceptance on the deployment hosts,
backups, restore and externally scheduled retention remain deployment gates.
HTTP inflight capacity still has a per-process component although durable rate
counters are atomic. Multiple workers must not be declared fully accepted from
these selected parity cases alone.
