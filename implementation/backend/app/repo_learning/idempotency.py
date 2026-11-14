"""Atomic owner-scoped retries; stored responses cascade with their private data."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3

MAX_OWNER_RECORDS = 2000
MAX_GLOBAL_RECORDS = 10000
MAX_OWNER_BYTES = 16 * 1024 * 1024
MAX_GLOBAL_BYTES = 64 * 1024 * 1024
KEY_PATTERN = re.compile(r'[A-Za-z0-9._:-]{8,128}')


class IdempotencyConflict(ValueError):
    """A client key was already used for different input."""


class RetryQuotaExceeded(ValueError):
    """Retry state is bounded independently of snapshot and evidence storage."""


def encode(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def fingerprint(value: object) -> str:
    return hashlib.sha256(encode(value).encode('utf-8')).hexdigest()


def key_for(key: str | None, input_hash: str) -> str:
    if key is None:
        return 'derived:' + input_hash
    if not KEY_PATTERN.fullmatch(key):
        raise ValueError('invalid idempotency key')
    return key


def replay(db: sqlite3.Connection, workspace: str, operation: str, key: str, input_hash: str) -> dict | None:
    row = db.execute('SELECT input_hash,response_json FROM repo_idempotency WHERE workspace_id=? AND operation=? AND key=?',
                     (workspace, operation, key)).fetchone()
    if row:
        if row['input_hash'] != input_hash:
            raise IdempotencyConflict('idempotency input conflict')
        return json.loads(row['response_json'])
    if db.execute('SELECT count(*) FROM repo_idempotency WHERE workspace_id=?', (workspace,)).fetchone()[0] >= MAX_OWNER_RECORDS or db.execute('SELECT count(*) FROM repo_idempotency').fetchone()[0] >= MAX_GLOBAL_RECORDS:
        raise RetryQuotaExceeded('repository retry storage limit exceeded')
    return None


def remember(db: sqlite3.Connection, workspace: str, operation: str, key: str, input_hash: str,
             snapshot_id: str, response: dict, *, studio_session_id: str | None = None,
             defense_id: str | None = None, evidence_card_id: str | None = None,
             decision_id: str | None = None) -> None:
    # Call only inside the same write transaction as the underlying mutation.
    if not db.in_transaction:
        raise RuntimeError('retry record requires a transaction')
    response_json = encode(response)
    charge = len(response_json.encode('utf-8')) + len(operation) + len(key) + 1024
    usage = db.execute('SELECT COALESCE(SUM(length(CAST(response_json AS BLOB))+length(operation)+length(key)+1024),0) AS total, COALESCE(SUM(CASE WHEN workspace_id=? THEN length(CAST(response_json AS BLOB))+length(operation)+length(key)+1024 ELSE 0 END),0) AS owned FROM repo_idempotency', (workspace,)).fetchone()
    if usage['total'] + charge > MAX_GLOBAL_BYTES or usage['owned'] + charge > MAX_OWNER_BYTES:
        raise RetryQuotaExceeded('repository retry byte limit exceeded')
    db.execute('INSERT INTO repo_idempotency VALUES (?,?,?,?,?,?,?,?,?,?,?)',
               (workspace, operation, key, input_hash, snapshot_id, studio_session_id, defense_id,
                evidence_card_id, decision_id, response_json, datetime.now(timezone.utc).isoformat()))
