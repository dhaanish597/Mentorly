"""Experimental PostgreSQL-only speech coordination; not wired to the product.

All cooperating coordinators must share this database and use these primitives.
An expired lease remains occupied and charged indefinitely. Safely reclaiming
it requires externally enforced worker termination or fencing *and* provider
quiescence; no recovery API is provided here. Database fencing cannot prevent
a paused worker from subsequently dispatching an external provider call. This is not an
implementation of the existing SQLite speech APIs or complete quota policy.
Each lease permits exactly one provider call; STT duration and TTS character
reservations must be trusted upper bounds. Expiry is recorded lazily during a
successful operation. A rejected transaction rolls that update back, but both
expired RESERVED/STARTED and UNCERTAIN remain occupied and fully charged.
"""
from dataclasses import dataclass
import uuid

from .migrations import Migration

SPEECH_MIGRATION = Migration(2, "speech_coordination", """
CREATE TABLE viva_speech_limits (
 singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
 max_slots INTEGER NOT NULL CHECK (max_slots > 0),
 max_stt_ms BIGINT NOT NULL CHECK (max_stt_ms >= 0),
 max_tts_chars BIGINT NOT NULL CHECK (max_tts_chars >= 0),
 max_calls BIGINT NOT NULL CHECK (max_calls >= 0)
);
CREATE TABLE viva_speech_reservations (
 id UUID PRIMARY KEY, fence BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
 state TEXT NOT NULL CHECK (state IN ('RESERVED','STARTED','UNCERTAIN','COMMITTED','RELEASED')),
 stt_ms BIGINT NOT NULL CHECK (stt_ms >= 0),
 tts_chars BIGINT NOT NULL CHECK (tts_chars >= 0),
 calls BIGINT NOT NULL CHECK (calls = 1),
 expires_at TIMESTAMPTZ NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX viva_speech_reservations_state ON viva_speech_reservations(state);
""")


class CoordinationError(RuntimeError):
    """The lease, quota, or coordination configuration prevents the action."""


@dataclass(frozen=True)
class Lease:
    reservation_id: str
    fence: int


def _idle(conn):
    if getattr(getattr(conn, "info", None), "transaction_status", None) != 0:
        raise CoordinationError("An idle PostgreSQL connection is required")


def _lock(conn):
    conn.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
    row = conn.execute("SELECT max_slots,max_stt_ms,max_tts_chars,max_calls FROM viva_speech_limits WHERE singleton=TRUE FOR UPDATE").fetchone()
    if not isinstance(row, tuple) or len(row) != 4:
        raise CoordinationError("Speech limits missing or incompatible row factory")
    # Never reclaim a slot solely because the clock elapsed: the upstream call
    # could still be running. The uncertainty also remains fully budgeted.
    conn.execute("UPDATE viva_speech_reservations SET state='UNCERTAIN',updated_at=clock_timestamp() WHERE state IN ('RESERVED','STARTED') AND expires_at <= clock_timestamp()")
    return row


def configure(conn, *, max_slots: int, max_stt_ms: int, max_tts_chars: int, max_calls: int):
    """Initialize immutable lifetime limits, or verify an identical configuration."""
    values = (max_slots, max_stt_ms, max_tts_chars, max_calls)
    if any(type(x) is not int for x in values) or max_slots < 1 or any(x < 0 for x in values[1:]):
        raise ValueError("Invalid speech limits")
    _idle(conn)
    with conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        conn.execute("INSERT INTO viva_speech_limits (singleton,max_slots,max_stt_ms,max_tts_chars,max_calls) VALUES (TRUE,%s,%s,%s,%s) ON CONFLICT DO NOTHING", values)
        row = conn.execute("SELECT max_slots,max_stt_ms,max_tts_chars,max_calls FROM viva_speech_limits WHERE singleton=TRUE FOR UPDATE").fetchone()
        if not isinstance(row, tuple) or row != values:
            raise CoordinationError("Speech limits differ from existing configuration")


def reserve(conn, *, stt_ms: int, tts_chars: int, calls: int, lease_seconds: int) -> Lease:
    values = (stt_ms, tts_chars, calls, lease_seconds)
    if any(type(x) is not int for x in values) or stt_ms < 0 or tts_chars < 0 or calls != 1 or not 1 <= lease_seconds <= 3600:
        raise ValueError("Invalid speech reservation")
    _idle(conn)
    with conn.transaction():
        max_slots, max_stt, max_tts, max_calls = _lock(conn)
        totals = conn.execute("""SELECT count(*) FILTER (WHERE state IN ('RESERVED','STARTED','UNCERTAIN')),
            COALESCE(sum(stt_ms),0),COALESCE(sum(tts_chars),0),COALESCE(sum(calls),0)
            FROM viva_speech_reservations WHERE state IN ('RESERVED','STARTED','UNCERTAIN','COMMITTED')""").fetchone()
        if not isinstance(totals, tuple) or len(totals) != 4:
            raise CoordinationError("Incompatible row factory")
        slots, used_stt, used_tts, used_calls = totals
        if slots >= max_slots or used_stt + stt_ms > max_stt or used_tts + tts_chars > max_tts or used_calls + calls > max_calls:
            raise CoordinationError("Speech capacity or budget exhausted")
        reservation_id = str(uuid.uuid4())
        row = conn.execute("""INSERT INTO viva_speech_reservations(id,state,stt_ms,tts_chars,calls,expires_at)
            VALUES (%s,'RESERVED',%s,%s,%s,clock_timestamp()+make_interval(secs => %s)) RETURNING fence""",
            (reservation_id, stt_ms, tts_chars, calls, lease_seconds)).fetchone()
        return Lease(reservation_id, row[0])


def _transition(conn, lease: Lease, before: str, after: str):
    _idle(conn)
    with conn.transaction():
        _lock(conn)
        changed = conn.execute("""UPDATE viva_speech_reservations SET state=%s,updated_at=clock_timestamp()
            WHERE id=%s AND fence=%s AND state=%s AND expires_at > clock_timestamp() RETURNING id""",
            (after, lease.reservation_id, lease.fence, before)).fetchone()
        if changed is None:
            raise CoordinationError("Lease expired, fenced, or already finalized")


def start(conn, lease: Lease):
    """Record intent before dispatch. The caller must stop if this fails."""
    _transition(conn, lease, "RESERVED", "STARTED")


def release_unstarted(conn, lease: Lease):
    """Release only when no provider call was dispatched."""
    _transition(conn, lease, "RESERVED", "RELEASED")


def complete(conn, lease: Lease):
    """Retain the full reserved budget after a known completed provider call."""
    _transition(conn, lease, "STARTED", "COMMITTED")


