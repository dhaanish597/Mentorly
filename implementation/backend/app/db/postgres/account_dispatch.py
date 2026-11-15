"""Account-scoped provider slots shared by all coordinators in one PostgreSQL DB.

INFLIGHT/UNCERTAIN slots are never freed merely because a clock elapsed: a paused
process could still own a provider WebSocket. Expired undispatched leases can be
reclaimed. A matching fenced completion safely releases its own slot; abandoned
dispatched work requires provider quiescence before explicit operator resolution.
The account identity is a one-way key digest, never a credential or user ID.
"""

import hashlib
import uuid
from dataclasses import dataclass

from .runtime import PostgresTarget

DDL = """
CREATE SCHEMA IF NOT EXISTS viva_provider_coordination;
CREATE TABLE IF NOT EXISTS viva_provider_coordination.accounts (
 account_hash TEXT PRIMARY KEY,
 capacity INTEGER NOT NULL CHECK(capacity BETWEEN 1 AND 32)
);
CREATE TABLE IF NOT EXISTS viva_provider_coordination.leases (
 id TEXT PRIMARY KEY,
 account_hash TEXT NOT NULL REFERENCES viva_provider_coordination.accounts(account_hash),
 fence BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
 state TEXT NOT NULL CHECK(state IN ('UNDISPATCHED','INFLIGHT','UNCERTAIN','RELEASED')),
 expires_at TIMESTAMPTZ NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS provider_account_active ON viva_provider_coordination.leases(account_hash,state);
"""


class DispatchUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Lease:
    id: str
    fence: int


class AccountDispatcher:
    def __init__(self, target: PostgresTarget, *, account_key: str, capacity: int):
        if (
            not isinstance(target, PostgresTarget)
            or not isinstance(account_key, str)
            or not account_key
        ):
            raise ValueError(
                "Explicit PostgreSQL target and provider account key required."
            )
        if type(capacity) is not int or not 1 <= capacity <= 32:
            raise ValueError("Invalid verified provider capacity.")
        self.target = target
        self.account_hash = hashlib.sha256(
            ("viva-gnani-account-v1:" + account_key).encode()
        ).hexdigest()
        self.capacity = capacity
        with target.connect() as conn, conn.transaction():
            conn.execute(
                """INSERT INTO viva_provider_coordination.accounts VALUES(%s,%s)
                ON CONFLICT(account_hash) DO NOTHING""",
                (self.account_hash, capacity),
            )
            existing = conn.execute(
                "SELECT capacity FROM viva_provider_coordination.accounts WHERE account_hash=%s FOR UPDATE",
                (self.account_hash,),
            ).fetchone()
            if existing != (capacity,):
                raise DispatchUnavailable(
                    "Provider capacity differs across coordinators."
                )

    def reserve(self, *, ttl_seconds=300):
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 3600:
            raise ValueError("Invalid lease TTL.")
        with self.target.connect() as conn, conn.transaction():
            configured = conn.execute(
                "SELECT capacity FROM viva_provider_coordination.accounts WHERE account_hash=%s FOR UPDATE",
                (self.account_hash,),
            ).fetchone()
            if configured != (self.capacity,):
                raise DispatchUnavailable(
                    "Provider capacity differs across coordinators."
                )
            conn.execute(
                "UPDATE viva_provider_coordination.leases SET state='RELEASED' WHERE account_hash=%s AND state='UNDISPATCHED' AND expires_at<=clock_timestamp()",
                (self.account_hash,),
            )
            conn.execute(
                "UPDATE viva_provider_coordination.leases SET state='UNCERTAIN' WHERE account_hash=%s AND state='INFLIGHT' AND expires_at<=clock_timestamp()",
                (self.account_hash,),
            )
            active = conn.execute(
                "SELECT count(*) FROM viva_provider_coordination.leases WHERE account_hash=%s AND state IN ('UNDISPATCHED','INFLIGHT','UNCERTAIN')",
                (self.account_hash,),
            ).fetchone()[0]
            if active >= self.capacity:
                return None
            identity = str(uuid.uuid4())
            fence = conn.execute(
                "INSERT INTO viva_provider_coordination.leases(id,account_hash,state,expires_at) VALUES(%s,%s,'UNDISPATCHED',clock_timestamp()+make_interval(secs=>%s)) RETURNING fence",
                (identity, self.account_hash, ttl_seconds),
            ).fetchone()[0]
            return Lease(identity, fence)

    def reconfigure_capacity(self, capacity: int):
        """Operator-only capacity change after all account work is quiescent.

        Callers must stop coordinators and verify the provider entitlement first.
        The database rejects active/uncertain leases; stale workers subsequently
        reject admission rather than dispatching under their previous capacity.
        """
        if type(capacity) is not int or not 1 <= capacity <= 32:
            raise ValueError("Invalid verified provider capacity.")
        with self.target.connect() as conn, conn.transaction():
            current = conn.execute(
                "SELECT capacity FROM viva_provider_coordination.accounts WHERE account_hash=%s FOR UPDATE",
                (self.account_hash,),
            ).fetchone()
            if current != (self.capacity,):
                raise DispatchUnavailable(
                    "Provider capacity differs across coordinators."
                )
            active = conn.execute(
                "SELECT EXISTS(SELECT 1 FROM viva_provider_coordination.leases WHERE account_hash=%s AND state IN ('UNDISPATCHED','INFLIGHT','UNCERTAIN'))",
                (self.account_hash,),
            ).fetchone()[0]
            if active:
                raise DispatchUnavailable(
                    "Provider capacity cannot change while account work is active or uncertain."
                )
            conn.execute(
                "UPDATE viva_provider_coordination.accounts SET capacity=%s WHERE account_hash=%s",
                (capacity, self.account_hash),
            )
        self.capacity = capacity

    def start(self, lease):
        with self.target.connect() as conn:
            changed = conn.execute(
                "UPDATE viva_provider_coordination.leases SET state='INFLIGHT' WHERE id=%s AND fence=%s AND account_hash=%s AND state='UNDISPATCHED' AND expires_at>clock_timestamp()",
                (lease.id, lease.fence, self.account_hash),
            ).rowcount
            if changed != 1:
                raise DispatchUnavailable(
                    "Provider lease was superseded or expired before dispatch."
                )

    def finish(self, lease, *, uncertain=False):
        with self.target.connect() as conn:
            changed = conn.execute(
                "UPDATE viva_provider_coordination.leases SET state=%s WHERE id=%s AND fence=%s AND account_hash=%s AND state IN ('UNDISPATCHED','INFLIGHT','UNCERTAIN')",
                (
                    "UNCERTAIN" if uncertain else "RELEASED",
                    lease.id,
                    lease.fence,
                    self.account_hash,
                ),
            ).rowcount
            if changed != 1:
                raise DispatchUnavailable("Provider lease completion was stale.")
