"""Bounded, private mentor audio stored alongside the owning session."""
from datetime import datetime, timedelta, timezone
import hashlib
from uuid import uuid4

MAX_AUDIO_BYTES = 5 * 1024 * 1024
MAX_TOTAL_AUDIO_BYTES = 64 * 1024 * 1024
CLEANUP_BATCH_SIZE = 1000
AUDIO_TTL = timedelta(hours=24)
AUDIO_PREFIX = "/api/v1/codebase-learning/audio/"


def cleanup_expired_audio(conn, now=None):
    """Delete expired blobs; callers control transaction and scheduling."""
    now = now or datetime.now(timezone.utc)
    return conn.execute(
        "DELETE FROM codebase_learning_audio WHERE id IN "
        "(SELECT id FROM codebase_learning_audio WHERE expires_at <= ? ORDER BY expires_at LIMIT ?)",
        (now.isoformat(), CLEANUP_BATCH_SIZE),
    ).rowcount


def store_audio(conn, session_id, audio_bytes):
    """Persist audio in the caller's session transaction and return its opaque URL."""
    if not audio_bytes or len(audio_bytes) > MAX_AUDIO_BYTES:
        raise ValueError("Audio must be nonempty and at most 5 MiB")
    now = datetime.now(timezone.utc)
    # BEGIN IMMEDIATE serializes quota checks across SQLite processes and maps to
    # a schema-scoped PostgreSQL advisory transaction lock in the DB adapter.
    own_transaction = not conn.in_transaction
    if own_transaction:
        conn.execute("BEGIN IMMEDIATE")
    elif hasattr(conn, "target"):
        # A repeatable-read snapshot may predate acquisition of the lock and
        # would make the global quota check stale even after serialization.
        isolation = conn.execute("SHOW transaction_isolation").fetchone()[0]
        if isolation.lower() != "read committed":
            raise ValueError("Audio storage requires read committed isolation")
        # Existing PostgreSQL transactions may have been opened with plain BEGIN.
        # Take the same schema-wide advisory lock as BEGIN IMMEDIATE before the
        # quota read; transaction-scoped locks are safely reentrant.
        lock = int.from_bytes(
            hashlib.sha256(("viva-write:" + conn.target.schema).encode()).digest()[:8],
            "big", signed=True,
        )
        conn.execute("SELECT pg_advisory_xact_lock(?)", (lock,))
    try:
        cleanup_expired_audio(conn, now)
        used = conn.execute("SELECT COALESCE(SUM(length(wav)), 0) FROM codebase_learning_audio").fetchone()[0]
        if used + len(audio_bytes) > MAX_TOTAL_AUDIO_BYTES:
            raise ValueError("Mentor audio storage is full")
        audio_id = uuid4().hex + ".wav"
        conn.execute(
            "INSERT INTO codebase_learning_audio (id, session_id, wav, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (audio_id, session_id, audio_bytes, now.isoformat(), (now + AUDIO_TTL).isoformat()),
        )
        if own_transaction:
            conn.commit()
        return AUDIO_PREFIX + audio_id
    except BaseException:
        if own_transaction:
            conn.rollback()
        raise



def get_audio(conn, workspace_id, filename):
    """Return unexpired audio only when linked to a live, owned message."""
    row = conn.execute(
        "SELECT a.wav FROM codebase_learning_audio a "
        "JOIN codebase_learning_sessions s ON s.id=a.session_id "
        "JOIN codebase_learning_messages m ON m.session_id=s.id AND m.audio_path=? "
        "WHERE a.id=? AND s.workspace_id=? AND s.deleted_at IS NULL AND a.expires_at>?",
        (AUDIO_PREFIX + filename, filename, workspace_id, datetime.now(timezone.utc).isoformat()),
    ).fetchone()
    return bytes(row[0]) if row else None


def maintenance():
    """Operator entry point: remove at most one batch per invocation."""
    from contextlib import closing
    from backend.app.core.config import get_settings
    from backend.app.db.migrations import database_target, open_connection

    with closing(open_connection(database_target(get_settings()))) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            removed = cleanup_expired_audio(conn)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    return removed


if __name__ == "__main__":
    print(f"Removed {maintenance()} expired mentor audio blobs")
