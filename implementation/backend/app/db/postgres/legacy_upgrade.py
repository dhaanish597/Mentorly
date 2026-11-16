"""Offline rehearsal of a legacy PostgreSQL copy into a separate new schema.

This tool does not switch traffic. Source writers must remain stopped from before
invocation until cutover; a one-transaction lock is not a maintenance window.
"""
from __future__ import annotations
from contextlib import contextmanager, nullcontext
import hashlib
import uuid

from psycopg import sql
from .transfer import _order, _target_columns


class UpgradeError(RuntimeError):
    pass


@contextmanager
def frozen_legacy_schema(target, source_schema: str):
    """Hold write-blocking locks through copy and operator-controlled cutover.

    All writes must use ordinary PostgreSQL table permissions. The transaction
    must remain open; termination rolls back the copy and releases its locks.
    An external traffic freeze remains necessary after this context exits.
    """
    import re
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', source_schema) or source_schema == target.schema:
        raise UpgradeError('Source and target must be distinct private schemas.')
    with target.connect() as conn, conn.transaction():
        conn.execute("SET LOCAL lock_timeout = '2s'")
        tables = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename", (source_schema,)).fetchall()
        if not tables:
            raise UpgradeError('Legacy schema is empty or missing.')
        for (table,) in tables:
            conn.execute(sql.SQL('LOCK TABLE {}.{} IN SHARE ROW EXCLUSIVE MODE NOWAIT').format(sql.Identifier(source_schema), sql.Identifier(table)))
        yield conn


def _retain_uncertain_speech_leases(conn, source_schema, destination, account_key):
    """Retain unknown dispatches and occupy the real account's single slot.

    This is not reconciliation. No expired or unknown provider work is released,
    retried, or declared completed. The original rows remain intact in both the
    source and an exact target archive; the coordinator bridge remains UNCERTAIN.
    """
    source = sql.Identifier(source_schema)
    rows = conn.execute(sql.SQL(
        'SELECT id,kind,owner,state,expires_at,created_at FROM {}.cloud_leases ORDER BY id'
    ).format(source)).fetchall()
    if not rows:
        return []
    if not isinstance(account_key, str) or not account_key:
        raise UpgradeError('Legacy provider leases must be reconciled or explicitly retained for their verified account.')
    now = conn.execute('SELECT extract(epoch FROM clock_timestamp())').fetchone()[0]
    if any(kind != 'speech' or state != 'UNCERTAIN' or not expires_at <= now
           for _, kind, _, state, expires_at, _ in rows):
        raise UpgradeError('Only expired UNCERTAIN speech leases may be retained; other legacy work must be reconciled.')
    digest = hashlib.sha256(('viva-gnani-account-v1:' + account_key).encode()).hexdigest()
    conn.execute('INSERT INTO viva_provider_coordination.accounts VALUES(%s,1) ON CONFLICT(account_hash) DO NOTHING', (digest,))
    capacity = conn.execute('SELECT capacity FROM viva_provider_coordination.accounts WHERE account_hash=%s FOR UPDATE', (digest,)).fetchone()
    if capacity != (1,):
        raise UpgradeError('Legacy uncertain speech requires the verified single-slot provider account.')
    conn.execute(sql.SQL('CREATE TABLE {}.legacy_cloud_leases (LIKE {}.cloud_leases INCLUDING ALL)').format(destination, source))
    conn.execute(sql.SQL('INSERT INTO {}.legacy_cloud_leases SELECT * FROM {}.cloud_leases').format(destination, source))
    mismatch = conn.execute(sql.SQL(
        'SELECT EXISTS((SELECT * FROM {}.cloud_leases EXCEPT ALL SELECT * FROM {}.legacy_cloud_leases) '
        'UNION ALL (SELECT * FROM {}.legacy_cloud_leases EXCEPT ALL SELECT * FROM {}.cloud_leases))'
    ).format(source, destination, destination, source)).fetchone()[0]
    if mismatch:
        raise UpgradeError('Legacy provider leases failed reconciliation.')
    retained = []
    for identifier, _, _, _, expires_at, created_at in rows:
        bridge_id = 'legacy:' + str(uuid.uuid5(uuid.NAMESPACE_URL, source_schema + ':' + identifier))
        conn.execute("""INSERT INTO viva_provider_coordination.leases
            (id,account_hash,state,expires_at,created_at)
            VALUES(%s,%s,'UNCERTAIN',to_timestamp(%s),to_timestamp(%s))
            ON CONFLICT(id) DO NOTHING""", (bridge_id,digest,expires_at,created_at))
        matches = conn.execute("""SELECT account_hash=%s AND state='UNCERTAIN'
            AND expires_at=to_timestamp(%s) AND created_at=to_timestamp(%s)
            FROM viva_provider_coordination.leases WHERE id=%s""",
            (digest,expires_at,created_at,bridge_id)).fetchone()
        if matches != (True,):
            raise UpgradeError('Legacy provider lease bridge conflicts with existing accounting.')
        retained.append(bridge_id)
    return retained


def copy_legacy_schema(target, source_schema: str, expected_history, *, frozen_connection=None,
                       legacy_speech_account_key=None):
    """Copy a validated legacy schema to an initialized empty target atomically.

    Original tables remain untouched. Callers must retain backups and establish
    and verify an external write freeze before cutover. By default every legacy
    provider lease is rejected. An explicit verified speech account key permits
    exact retention of expired UNCERTAIN speech leases, occupying that account's
    single shared provider slot indefinitely until separately reconciled. The
    operator must independently verify that this key identifies the legacy
    Gnani account and all old workers/provider activity have quiesced; the copy
    cannot establish either fact. Retained uncertainty prevents voice calls.
    """
    import re
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', source_schema) or source_schema == target.schema:
        raise UpgradeError('Source and target must be distinct private schemas.')
    if len(expected_history) != 6:
        raise UpgradeError('Exact six-entry legacy migration history required.')
    with (target.connect() if frozen_connection is None else nullcontext(frozen_connection)) as conn, conn.transaction():
        conn.execute("SET LOCAL lock_timeout = '2s'")
        source = sql.Identifier(source_schema)
        destination = sql.Identifier(target.schema)
        rows = conn.execute('SELECT table_name,column_name FROM information_schema.columns WHERE table_schema=%s ORDER BY table_name,ordinal_position', (source_schema,)).fetchall()
        columns = {}
        for table, column in rows:
            columns.setdefault(table, []).append(column)
        excluded = {'cloud_audio', 'cloud_leases', 'sqlite_master', 'repo_chunks_fts'}
        if not excluded <= columns.keys():
            raise UpgradeError('Legacy schema is incomplete.')
        target_columns = _target_columns(conn, target.schema)
        source_columns = {k: v for k, v in columns.items() if k not in excluded}
        if any(target_columns.get(k) != v for k, v in source_columns.items()):
            raise UpgradeError('Legacy columns differ from the target contract.')
        # Metadata views (notably sqlite_master over information_schema.tables)
        # do not contain source rows and must not be locked: PostgreSQL expands
        # a view lock to its underlying objects, outside this private schema.
        tables = [row[0] for row in conn.execute('SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename', (source_schema,)).fetchall()]
        for table in tables:
            conn.execute(sql.SQL('LOCK TABLE {}.{} IN SHARE ROW EXCLUSIVE MODE NOWAIT').format(source, sql.Identifier(table)))
        history = conn.execute(sql.SQL('SELECT version,name,checksum FROM {}.schema_migrations ORDER BY version').format(source)).fetchall()
        if history != list(expected_history):
            raise UpgradeError('Legacy migration history differs from the verified release.')
        for table in target_columns:
            if conn.execute(sql.SQL('SELECT EXISTS(SELECT 1 FROM {}.{})').format(destination, sql.Identifier(table))).fetchone()[0]:
                raise UpgradeError('Target is not empty.')
        retained_leases = _retain_uncertain_speech_leases(
            conn, source_schema, destination, legacy_speech_account_key)
        copied = 0
        for table in _order(conn, target.schema, source_columns):
            names = sql.SQL(',').join(map(sql.Identifier, source_columns[table]))
            src = sql.SQL('{}.{}').format(source, sql.Identifier(table))
            dst = sql.SQL('{}.{}').format(destination, sql.Identifier(table))
            primary = [row[0] for row in conn.execute('''SELECT a.attname FROM pg_index i
                JOIN pg_class c ON c.oid=i.indrelid JOIN pg_namespace n ON n.oid=c.relnamespace
                CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum,position)
                JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=k.attnum
                WHERE n.nspname=%s AND c.relname=%s AND i.indisprimary ORDER BY k.position''', (source_schema, table))]
            if not primary:
                raise UpgradeError('Historical ordering requires a declared primary key.')
            # Old PostgreSQL has no persisted SQLite rowid. Establish a stable
            # timestamp/key tie-break; do not invent chronology for tied records.
            ordering = (['created_at'] if 'created_at' in source_columns[table] else []) + [key for key in primary if key != 'created_at']
            order = sql.SQL(',').join(map(sql.Identifier, ordering))
            conn.execute(sql.SQL('INSERT INTO {} ({}) SELECT {} FROM {} ORDER BY {}').format(dst, names, names, src, order))
            mismatch = conn.execute(sql.SQL('SELECT EXISTS((SELECT {} FROM {} EXCEPT ALL SELECT {} FROM {}) UNION ALL (SELECT {} FROM {} EXCEPT ALL SELECT {} FROM {}))').format(names, src, names, dst, names, dst, names, src)).fetchone()[0]
            if mismatch:
                raise UpgradeError('A source table failed reconciliation.')
            copied += conn.execute(sql.SQL('SELECT count(*) FROM {}').format(src)).fetchone()[0]
        conn.execute(sql.SQL('INSERT INTO {}.repo_chunks_fts(chunk_id,snapshot_id,text) SELECT id,snapshot_id,text FROM {}.repo_chunks').format(destination, destination))
        # Preserve historical audio for the authenticated PostgreSQL cache bridge.
        conn.execute(sql.SQL('CREATE TABLE {}.legacy_cloud_audio (LIKE {}.cloud_audio INCLUDING ALL)').format(destination, source))
        conn.execute(sql.SQL('INSERT INTO {}.legacy_cloud_audio SELECT * FROM {}.cloud_audio').format(destination, source))
        mismatch = conn.execute(sql.SQL('SELECT EXISTS((SELECT * FROM {}.cloud_audio EXCEPT ALL SELECT * FROM {}.legacy_cloud_audio) UNION ALL (SELECT * FROM {}.legacy_cloud_audio EXCEPT ALL SELECT * FROM {}.cloud_audio))').format(source, destination, destination, source)).fetchone()[0]
        if mismatch:
            raise UpgradeError('Legacy audio failed reconciliation.')
        audio_count = conn.execute(sql.SQL('SELECT count(*) FROM {}.legacy_cloud_audio').format(destination)).fetchone()[0]
    return {'tables': len(source_columns), 'rows': copied, 'retained_audio': audio_count,
            'retained_leases': len(retained_leases), 'retained_lease_ids': retained_leases}
