# PostgreSQL runtime

The deployed application uses `PostgresTarget` from `runtime.py`. Existing
repository and service logic passes this target to `db.migrations.open_connection`
and `apply_migrations`; local paths continue to use the original SQLite driver.

Remote targets require `sslmode=verify-full`. If no CA bundle is explicitly
configured, the runtime uses `certifi.where()`. Credentials never appear in the
target's string representation or database errors. `target.identity` distinguishes
database/schema pairs without including or hashing passwords.

The private `viva_app` schema contains the full migrated application schema,
native evidence and privacy triggers, PostgreSQL full-text search, cloud leases
and audio cache, and the DSA conversation cache/model-call ledger. Public and
Supabase anonymous/authenticated roles receive no schema access. Curated quiz,
mission, and achievement definitions are seeded; fabricated learner scores are
excluded.

Every explicit application transaction takes a schema-specific PostgreSQL
transaction advisory lock. Single-statement mutations also take the lock.
`search_path`, UTC timezone, statement/lock deadlines, and idle transaction
deadlines are transaction-local, and prepared statements are disabled. This
supports transaction poolers while retaining the application's serialized
read-modify-write behavior.

The adapter explicitly supports the application's trusted SQLite JSON/date
queries, metadata checks, UTF-8 byte accounting, conflict clauses and FTS query.
Unsupported SQLite syntax fails closed. Trusted `INSERT OR REPLACE` statements
are restricted to the three existing repository tables and explicit transactions;
their delete cascades and rollback behavior are preserved. PostgreSQL search uses
native `simple` tokenization and relevance ranking; ranking is not byte-for-byte
SQLite FTS5 parity.

`runtime_migrations` is an authored PostgreSQL manifest, separate from the local
SQLite upgrade history. All pending migrations and history writes commit in one
transaction under the writer lock. Existing history must match the manifest's
names and checksums. `sqlite_source_manifest.json` records the source SQLite
migration checksums and forces review when that source schema changes. The
runtime does not import an existing learner SQLite database.

`probe_runtime(target)` performs a read-only connection/history/checksum probe
and verifies the expected tables, functions and triggers exist. It does not run
migrations or claim provider/cloud deployment acceptance.

Acceptance tests are `backend/tests/integration/test_postgres_runtime.py` with
`VIVA_POSTGRES_RUNTIME_TEST_DSN` set to a disposable **local** PostgreSQL cluster.
Each test creates and removes a random schema. They cover schema parity, migration
rollback/drift, cross-process locking, CAS/idempotency, actual repository import
and search, actual learning/interview persistence, evidence/privacy guards,
speech deletion accounting and DSA reply/model-call retention. The SQLite DSA
contract also runs independently in `tests/unit/test_dsa_conversation_db.py`.

## Cloud speech and admission wiring

`cloud.py` supplies shared request capacity and a single shared Gnani provider
slot. Request leases recover after the 300-second Vercel function lifetime plus
a 60-second guard. Speech leases are marked STARTED before provider contact;
known completion or rejection releases the lease. Indeterminate outcomes retain
an UNCERTAIN lease, which never expires into automatic redispatch. An operator
must reconcile these records before further provider calls. Session deletion
reports outstanding shared provider leases instead of claiming remote work has
stopped. The existing local semaphore remains a local queue bound.

`SpeechGatekeeper` opens the actual PostgreSQL target and uses the shared schema,
rather than opening SQLite with the target's redacted string. Migration `0006`
adds the speech fields normally created dynamically by the local gatekeeper and
the native Julian-day function needed by retention. Cloud startup recovery only
marks reservations/imports older than 600 seconds; it cannot mark another live
Vercel instance's fresh work as interrupted. Usage settlement is idempotent.

`PostgresTTSCache` keeps completed, validated WAV bytes in `cloud_audio`. Cache
keys and public-versus-session scopes match the local cache contract. Writes,
age/size/count eviction and session liveness checks use the same transaction
writer lock as deletion. A late synthesis cannot reinsert private audio after a
session is tombstoned. Cloud mode creates no persistent audio directory. Expired
sessions cannot read cached audio even before a retention sweep runs.

`tests/integration/test_cloud_runtime_wiring.py` exercises real ASGI startup,
competing instance capacity, provider unknown-outcome fencing, private audio
across instances/deletion, stale recovery and schema upgrade in a disposable
local PostgreSQL cluster. Its provider errors are mocked, so these results do
not attest deployed voice, remote transport cancellation, Sandbox execution or
the Supabase/Vercel account's quotas.
