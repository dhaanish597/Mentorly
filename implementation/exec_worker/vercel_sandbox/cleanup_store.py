"""Durable, trusted cleanup obligations. Never uploaded to learner VMs."""
from __future__ import annotations

import re
from contextlib import closing, contextmanager
from typing import Callable, Protocol
from uuid import UUID, uuid4

from backend.app.db.postgres.runtime import PostgresTarget
from backend.app.db.migrations import open_connection

NAME = re.compile(r"viva-inv-[a-f0-9]{24}\Z")


class SandboxCleanupStore(Protocol):
    durable: bool
    def register(self, name: str, job_id: UUID) -> None: ...
    def acknowledge(self, name: str) -> None: ...
    def require_cleanup(self, name: str) -> None: ...
    def complete(self, name: str) -> None: ...
    def unresolved(self) -> list[str]: ...
    def blocking(self) -> list[str]: ...
    def claim_expired(self) -> list[tuple[str, bool]]: ...


class PostgresSandboxCleanupStore:
    """Use the backend's verified PostgreSQL target and private runtime schema.

    A name is committed before cloud creation and deleted only after the provider
    confirms destruction/absence. The caller must retain ambiguous creations
    until inventory confirmation, even after a 404. Apply runtime migration 0007
    before use and 0008 for execution limits; this class never mutates the schema.
    """
    durable = True

    def __init__(self, dsn_factory: Callable[[], PostgresTarget | str], connect_factory=None, *, enforce_execution_limits: bool = False, require_repository_job: bool = False):
        # A connection override must implement the shared runtime's transaction,
        # placeholder and close contracts. It exists for trusted offline doubles.
        self.dsn_factory = dsn_factory
        self.connect_factory = connect_factory
        self.owner_id = str(uuid4())
        self.enforces_execution_limits = enforce_execution_limits is True
        self.requires_repository_job = require_repository_job is True

    def _connection(self):
        if self.connect_factory is not None:
            return self.connect_factory()
        target = self.dsn_factory()
        if isinstance(target, str):
            target = PostgresTarget(target)
        if not isinstance(target, PostgresTarget):
            raise ValueError("verified PostgreSQL cleanup target is required")
        return open_connection(target)

    @contextmanager
    def _transaction(self):
        # Pooler connections receive only transaction-local schema, deadlines and
        # writer locking from the same runtime used by the rest of the backend.
        with closing(self._connection()) as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                yield connection

    @staticmethod
    def _validate(name):
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise ValueError("invalid owned Sandbox name")

    def register(self, name: str, job_id: UUID):
        self._validate(name)
        job_id = str(UUID(str(job_id)))
        with self._transaction() as connection:
            if self.enforces_execution_limits:
                if connection.execute("SELECT 1 FROM viva_sandbox_cleanup WHERE sandbox_name=?", (name,)).fetchone():
                    raise RuntimeError("Sandbox cleanup name is already registered")
                self._reserve_invocation(connection, job_id)
            changed = connection.execute("INSERT INTO viva_sandbox_cleanup (sandbox_name, job_id, owner_id) VALUES (?, ?, ?) ON CONFLICT (sandbox_name) DO NOTHING",
                                         (name, job_id, self.owner_id)).rowcount
            if changed != 1:
                raise RuntimeError("Sandbox cleanup name is already registered")

    @staticmethod
    def _recover_jobs(connection):
        # The lease outlives the 300-second function lifetime. A stale process
        # cannot create again: every registration checks its owner and expiry.
        # Unknown VM outcomes never expire into capacity, even after a restart.
        connection.execute("""UPDATE cloud_execution_jobs AS job SET active=FALSE,cancelled=TRUE
            WHERE active AND expires_at<=clock_timestamp() AND NOT EXISTS
            (SELECT 1 FROM viva_sandbox_cleanup AS cleanup WHERE cleanup.job_id::text=job.job_id)""")

    def acquire_job(self, job_id: UUID) -> bool:
        job_id = str(UUID(str(job_id)))
        with self._transaction() as connection:
            self._recover_jobs(connection)
            if connection.execute("SELECT 1 FROM cloud_execution_jobs WHERE active LIMIT 1").fetchone():
                return False
            if connection.execute("SELECT 1 FROM viva_sandbox_cleanup LIMIT 1").fetchone():
                return False
            changed = connection.execute("""INSERT INTO cloud_execution_jobs(job_id,owner_id,active,cancelled,expires_at)
                VALUES(?,?,TRUE,FALSE,clock_timestamp()+INTERVAL '360 seconds')
                ON CONFLICT(job_id) DO UPDATE SET owner_id=excluded.owner_id,active=TRUE,
                expires_at=excluded.expires_at WHERE NOT cloud_execution_jobs.cancelled AND NOT cloud_execution_jobs.active""",
                (job_id, self.owner_id)).rowcount
            return changed == 1

    def finish_job(self, job_id: UUID) -> bool:
        with self._transaction() as connection:
            changed = connection.execute("""UPDATE cloud_execution_jobs AS job SET active=FALSE
                WHERE job_id=? AND owner_id=? AND active AND NOT EXISTS
                (SELECT 1 FROM viva_sandbox_cleanup AS cleanup WHERE cleanup.job_id::text=job.job_id)""",
                (str(UUID(str(job_id))), self.owner_id)).rowcount
            return changed == 1

    def request_cancel(self, job_id: UUID):
        with self._transaction() as connection:
            connection.execute("""INSERT INTO cloud_execution_jobs(job_id,owner_id,active,cancelled,expires_at)
                VALUES(?,?,FALSE,TRUE,clock_timestamp()+INTERVAL '360 seconds')
                ON CONFLICT(job_id) DO UPDATE SET cancelled=TRUE""", (str(UUID(str(job_id))), self.owner_id))

    def job_cancelled(self, job_id: UUID) -> bool:
        job_id = str(UUID(str(job_id)))
        with self._transaction() as connection:
            return bool(connection.execute("""SELECT 1 WHERE EXISTS
                (SELECT 1 FROM cloud_execution_jobs WHERE job_id=? AND (cancelled OR (active AND expires_at<=clock_timestamp())))
                OR EXISTS (SELECT 1 FROM jobs WHERE id=? AND status NOT IN ('RUNNING','QUEUED'))""", (job_id, job_id)).fetchone())

    def cancellation_confirmed(self, job_id: UUID) -> bool:
        job_id = str(UUID(str(job_id)))
        with self._transaction() as connection:
            self._recover_jobs(connection)
            return not connection.execute("""SELECT 1 WHERE EXISTS
                (SELECT 1 FROM cloud_execution_jobs WHERE job_id=? AND active)
                OR EXISTS (SELECT 1 FROM viva_sandbox_cleanup WHERE job_id=CAST(? AS UUID))""", (job_id, job_id)).fetchone()

    def recovery_due(self, job_id: UUID) -> bool:
        with self._transaction() as connection:
            return bool(connection.execute("SELECT 1 FROM viva_sandbox_cleanup WHERE job_id=CAST(? AS UUID) AND recovery_not_before<=clock_timestamp() LIMIT 1", (str(UUID(str(job_id))),)).fetchone())

    @staticmethod
    def _periods(connection):
        row = connection.execute("SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM'),to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD')").fetchone()
        return (("MONTH", row[0], 500), ("DAY", row[1], 100))

    def quota_available(self) -> bool:
        with self._transaction() as connection:
            for kind, period, ceiling in self._periods(connection):
                row = connection.execute("SELECT invocations FROM cloud_execution_budget WHERE period_kind=? AND period=?", (kind, period)).fetchone()
                if row is not None and row[0] >= ceiling:
                    return False
            return True

    def _reserve_invocation(self, connection, job_id):
        if not connection.execute("""SELECT 1 FROM cloud_execution_jobs
            WHERE job_id=? AND owner_id=? AND active AND NOT cancelled AND expires_at>clock_timestamp()""", (job_id, self.owner_id)).fetchone():
            raise RuntimeError("Shared execution job is unavailable or cancelled")
        if self.job_cancelled_in_transaction(connection, job_id):
            raise RuntimeError("Shared execution job is cancelled")
        if self.requires_repository_job and not connection.execute("""SELECT 1 FROM jobs j
            JOIN sessions s ON s.id=j.session_id
            JOIN code_versions c ON c.session_id=s.id AND c.code_version_id=s.active_code_version_id
            WHERE j.id=? AND j.status IN ('RUNNING','QUEUED') AND s.deleted_at IS NULL AND s.state!='DELETED'
            AND CAST(s.expires_at AS TIMESTAMPTZ)>clock_timestamp()
            AND j.code_version_id=s.active_code_version_id AND j.turn_generation=s.active_turn_generation
            AND json_extract(j.revision_json,'$.exercise_id')=s.exercise_id
            AND json_extract(j.revision_json,'$.spec_version')=s.spec_version
            AND json_extract(j.revision_json,'$.code_hash')=c.code_hash""", (job_id,)).fetchone():
            raise RuntimeError('Owned execution revision was cancelled, deleted or superseded')
        if connection.execute("SELECT 1 FROM viva_sandbox_cleanup LIMIT 1").fetchone():
            raise RuntimeError("Shared Sandbox invocation capacity is occupied")
        # Registration burns quota before any SDK creation. No outcome refunds
        # it: 500 creations * 20 seconds * 1 vCPU = 2.78 CPU hours per month.
        for kind, period, ceiling in self._periods(connection):
            connection.execute("INSERT INTO cloud_execution_budget VALUES(?,?,0) ON CONFLICT DO NOTHING", (kind, period))
            changed = connection.execute("UPDATE cloud_execution_budget SET invocations=invocations+1 WHERE period_kind=? AND period=? AND invocations<?", (kind, period, ceiling)).rowcount
            if changed != 1:
                raise RuntimeError("Sandbox invocation quota exhausted")

    @staticmethod
    def job_cancelled_in_transaction(connection, job_id):
        return bool(connection.execute("SELECT 1 FROM jobs WHERE id=? AND status NOT IN ('RUNNING','QUEUED')", (job_id,)).fetchone())

    def acknowledge(self, name: str):
        self._validate(name)
        with self._transaction() as connection:
            changed = connection.execute("UPDATE viva_sandbox_cleanup SET creation_acknowledged = TRUE WHERE sandbox_name = ? AND owner_id = ? AND recovery_not_before > clock_timestamp() AND NOT cleanup_required",
                                         (name, self.owner_id)).rowcount
            if changed != 1:
                raise RuntimeError("cleanup ownership changed or expired before learner launch")

    def require_cleanup(self, name: str):
        self._validate(name)
        with self._transaction() as connection:
            changed = connection.execute("UPDATE viva_sandbox_cleanup SET cleanup_required = TRUE WHERE sandbox_name = ? AND owner_id = ?",
                                         (name, self.owner_id)).rowcount
            if changed != 1:
                raise RuntimeError("cleanup ownership changed before cleanup request")

    def complete(self, name: str):
        self._validate(name)
        with self._transaction() as connection:
            changed = connection.execute("DELETE FROM viva_sandbox_cleanup WHERE sandbox_name = ? AND owner_id = ?", (name, self.owner_id)).rowcount
            if changed != 1:
                raise RuntimeError("cleanup ownership changed before completion")

    def unresolved(self):
        with self._transaction() as connection:
            rows = connection.execute("SELECT sandbox_name FROM viva_sandbox_cleanup ORDER BY created_at, sandbox_name LIMIT 1001").fetchall()
        if len(rows) > 1000:
            raise RuntimeError("cleanup backlog exceeds recovery ceiling")
        names = [row[0] for row in rows]
        for name in names:
            self._validate(name)
        return names

    def blocking(self):
        with self._transaction() as connection:
            rows = connection.execute("SELECT sandbox_name FROM viva_sandbox_cleanup WHERE cleanup_required OR recovery_not_before <= CURRENT_TIMESTAMP ORDER BY created_at, sandbox_name LIMIT 1001").fetchall()
        if len(rows) > 1000:
            raise RuntimeError("cleanup backlog exceeds recovery ceiling")
        names = [row[0] for row in rows]
        for name in names:
            self._validate(name)
        return names

    def claim_expired(self, job_id: UUID | None = None):
        # The 120-second delay exceeds bounded SDK creation (three 5-second
        # attempts), VM lifetime (20 seconds), and cleanup. Unknown creations
        # are never cleared automatically, including after a 404.
        with self._transaction() as connection:
            job_filter = ' AND job_id=CAST(? AS UUID)' if job_id is not None else ''
            parameters = (str(UUID(str(job_id))), self.owner_id) if job_id is not None else (self.owner_id,)
            rows = connection.execute("""WITH expired AS (
                SELECT sandbox_name, creation_acknowledged FROM viva_sandbox_cleanup
                WHERE recovery_not_before <= CURRENT_TIMESTAMP""" + job_filter + """
                ORDER BY created_at, sandbox_name LIMIT 10 FOR UPDATE SKIP LOCKED
            ) UPDATE viva_sandbox_cleanup AS obligations
              SET owner_id = ?, cleanup_required = TRUE,
                  recovery_not_before = CURRENT_TIMESTAMP + INTERVAL '120 seconds'
              FROM expired WHERE obligations.sandbox_name = expired.sandbox_name
              RETURNING obligations.sandbox_name, expired.creation_acknowledged""", parameters).fetchall()
        claimed = [(row[0], row[1]) for row in rows]
        for name, _ in claimed:
            self._validate(name)
        return claimed
