"""Separately scheduled, fenced PostgreSQL maintenance ownership.

Claims use server time and a row lock. A paused owner's later database mutations
must carry the same live generation, validated inside their UOW transaction.
Background work does not run in each ASGI worker's lifespan.
"""

import asyncio
import uuid
from contextvars import ContextVar
from dataclasses import dataclass

DDL = """CREATE TABLE runtime_maintenance_owner (
 id TEXT PRIMARY KEY, owner TEXT,
 generation BIGINT NOT NULL DEFAULT 0,
 expires_at TIMESTAMPTZ NOT NULL DEFAULT '-infinity'
);"""


@dataclass(frozen=True)
class Fence:
    target_id: str
    owner: str
    generation: int


maintenance_fence: ContextVar[Fence | None] = ContextVar(
    "maintenance_fence", default=None
)


def claim(target, *, ttl_seconds=120):
    if type(ttl_seconds) is not int or not 10 <= ttl_seconds <= 300:
        raise ValueError("Invalid maintenance TTL.")
    with target.connect() as conn, conn.transaction():
        conn.execute(
            "INSERT INTO runtime_maintenance_owner(id) VALUES('retention') ON CONFLICT DO NOTHING"
        )
        row = conn.execute(
            "SELECT owner,generation,expires_at>clock_timestamp() FROM runtime_maintenance_owner WHERE id='retention' FOR UPDATE"
        ).fetchone()
        if row[0] is not None and row[2]:
            return None
        owner = str(uuid.uuid4())
        generation = conn.execute(
            "UPDATE runtime_maintenance_owner SET owner=%s,generation=generation+1,expires_at=clock_timestamp()+make_interval(secs=>%s) WHERE id='retention' RETURNING generation",
            (owner, ttl_seconds),
        ).fetchone()[0]
        return Fence(str(target), owner, generation)


def release(target, fence):
    with target.connect() as conn:
        conn.execute(
            "UPDATE runtime_maintenance_owner SET owner=NULL,expires_at='-infinity' WHERE id='retention' AND owner=%s AND generation=%s",
            (fence.owner, fence.generation),
        )


def recover_stale_imports(target):
    """Fail bounded-age passive imports; their existing publication CAS fences late workers.

    No paid provider request or code execution is reclaimed here. The source
    archive is not durably retained, so a failed import requires an explicit
    retry/upload rather than pretending to resume its missing bytes.
    """
    from contextlib import closing

    from backend.app.db.migrations import open_connection

    fence = maintenance_fence.get()
    if fence is None or fence.target_id != str(target):
        raise RuntimeError("Import recovery requires the scheduled maintenance fence.")
    with closing(open_connection(target)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        changed = conn.execute("""UPDATE repo_snapshots SET status='FAILED',failure_code='INTERRUPTED'
            WHERE id IN (SELECT id FROM repo_snapshots WHERE status IN ('QUEUED','INDEXING')
                AND CAST(created_at AS TIMESTAMPTZ)<=clock_timestamp()-interval '10 minutes'
                ORDER BY created_at LIMIT 100) AND status IN ('QUEUED','INDEXING')""").rowcount
        conn.commit()
        return changed


async def run_once(application):
    """Run one bounded sweep under a claim. Overlapping schedulers return BUSY."""
    from backend.app.db.migrations import database_target
    from backend.app.studio.retention import sweep

    target = database_target(application.state.settings)
    fence = await asyncio.to_thread(claim, target)
    if fence is None:
        return {"status": "BUSY", "errors": 0}
    token = maintenance_fence.set(fence)
    try:
        async with asyncio.timeout(90):
            recovered_imports = await asyncio.to_thread(recover_stale_imports, target)
            await asyncio.to_thread(sweep, target)
            report = await application.state.retention.run_once()
            return {
                "status": "COMPLETE" if report.errors == 0 else "RETRY_REQUIRED",
                "expired_sessions": report.expired_sessions,
                "recovered_imports": recovered_imports,
                "errors": report.errors,
                "pending_audio_cancellations": report.pending_audio_cancellations,
                "unconfirmed_broker_cancellations": report.unconfirmed_broker_cancellations,
            }
    finally:
        maintenance_fence.reset(token)
        await asyncio.to_thread(release, target, fence)
