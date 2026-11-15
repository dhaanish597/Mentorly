"""Experimental, credential-checked repository search, not wired to the API.

Requires migrations 4, 5, 6 and 7, an idle psycopg connection using tuple rows,
and a trusted database role. This does not replace role-based access controls.
The token hash is bearer-equivalent: the server must hash the raw capability
itself, never accept a digest from a client or expose/log the stored digest.
Enforce this boundary before wiring this helper to any endpoint.
PostgreSQL simple dictionary lexing and ts_rank differ from SQLite unicode61 and
BM25, especially for identifiers, Unicode, and ranking. Search is OR across the
first 12 word-like terms, with a hard cap of 20 results. It is not an FTS5 clone.
"""
from datetime import datetime, timezone
import hmac
import re

from .migrations import Migration

REPOSITORY_SEARCH_MIGRATION = Migration(7, "repository_search", """
ALTER TABLE repo_chunks ADD COLUMN search_vector tsvector GENERATED ALWAYS AS
 (to_tsvector('pg_catalog.simple'::regconfig, text)) STORED;
CREATE INDEX repo_chunks_search_vector_idx ON repo_chunks USING gin(search_vector);
""")


class SearchAuthorizationError(LookupError):
    """Capability or snapshot is unavailable."""


def search_repository(conn, *, workspace_id: str, token_hash: str, snapshot_id: str,
                      query: str, limit: int = 20) -> list[dict]:
    """Authorize the workspace capability, then search only its specified snapshot.

    token_hash is the hex SHA-256 digest of a bearer token, never the raw token.
    A share lock serializes with cooperating workspace and snapshot deletion.
    """
    if getattr(getattr(conn, 'info', None), 'transaction_status', None) != 0:
        raise ValueError('An idle PostgreSQL connection is required')
    if type(limit) is not int or not 1 <= limit <= 20 or not isinstance(query, str) or len(query) > 200:
        raise ValueError('Invalid search bounds')
    valid = isinstance(token_hash, str) and re.fullmatch(r'[0-9a-f]{64}', token_hash) is not None
    terms = re.findall(r'\w+', query, flags=re.UNICODE)[:12]
    with conn.transaction():
        conn.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        row = conn.execute('SELECT token_hash,expires_at,deleted_at FROM studio_workspaces WHERE id=%s FOR SHARE', (workspace_id,)).fetchone()
        if row is not None and (not isinstance(row, tuple) or len(row) != 3):
            raise ValueError('PostgreSQL connection must use tuple rows')
        stored = row[0] if row else ''
        stored_valid = isinstance(stored, str) and re.fullmatch(r'[0-9a-f]{64}', stored) is not None
        matches = hmac.compare_digest(stored if stored_valid else '0'*64, token_hash if valid else '0'*64)
        try:
            expires = datetime.fromisoformat(row[1]) if row else None
            unexpired = expires is not None and expires.utcoffset() is not None and expires > datetime.now(timezone.utc)
        except (TypeError, ValueError, OverflowError):
            unexpired = False
        if not (row and valid and stored_valid and matches and unexpired and row[2] is None):
            raise SearchAuthorizationError('Workspace or snapshot unavailable')
        snapshot = conn.execute('SELECT id FROM repo_snapshots WHERE id=%s AND workspace_id=%s FOR SHARE', (snapshot_id, workspace_id)).fetchone()
        if snapshot is None:
            raise SearchAuthorizationError('Workspace or snapshot unavailable')
        if not terms:
            return []
        rows = conn.execute("""WITH q AS (SELECT to_tsquery('pg_catalog.simple', COALESCE(string_agg('(' || term::text || ')', ' | '), '')) AS value FROM (SELECT plainto_tsquery('pg_catalog.simple', word) AS term FROM unnest(%s::text[]) AS words(word)) parsed WHERE numnode(term)>0)
          SELECT c.path,c.symbol,c.start_line,c.end_line,c.chunk_hash,c.text
          FROM repo_chunks c CROSS JOIN q
          WHERE c.snapshot_id=%s AND c.search_vector @@ q.value
          ORDER BY ts_rank(c.search_vector,q.value) DESC,c.id LIMIT %s""",
          (terms, snapshot_id, limit)).fetchall()
        if any(not isinstance(r, tuple) or len(r) != 6 for r in rows):
            raise ValueError('PostgreSQL connection must use tuple rows')
        keys = ('path','symbol','start_line','end_line','chunk_hash','text')
        return [dict(zip(keys, row)) for row in rows]
