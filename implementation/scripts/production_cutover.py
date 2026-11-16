"""Explicit post-password-reset operator steps; never resets credentials or traffic.

This module is deliberately not an automatic deployment command. The operator
must stop admission and workers, drain external provider activity, checkpoint
the source, and obtain approval for the exact artifact before calling mutating
functions. Database credential rejection does not prove external HTTP quiescence.
No function deletes source objects or resolves uncertain provider work.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
from urllib.parse import quote, urlencode

import psycopg
from psycopg import sql

from backend.app.db.postgres.legacy_upgrade import copy_legacy_schema, frozen_legacy_schema
from backend.app.db.postgres.account_dispatch import DDL as ACCOUNT_DDL
from backend.app.db.postgres.runtime import PostgresTarget, initialize
from scripts.provision_preview_database import NAME, grant_account, verify_isolation


class CutoverError(RuntimeError):
    """A release prerequisite failed; exception text never includes credentials."""


@dataclass(frozen=True)
class Credentials:
    admin_direct: str = field(repr=False)
    admin_pool: str = field(repr=False)
    old_direct: str = field(repr=False)
    old_pool: str = field(repr=False)


def load_credentials(path: Path) -> Credentials:
    """Load operator-only local state, refusing links and group/world access."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise CutoverError('Credentials require an owner-only regular file.')
        with os.fdopen(fd, 'r') as stream:
            fd = -1
            data = json.load(stream)
        return Credentials(**data)
    finally:
        if fd >= 0:
            os.close(fd)


def _params(dsn):
    try:
        params = psycopg.conninfo.conninfo_to_dict(dsn)
    except psycopg.Error:
        raise CutoverError('Invalid connection configuration.') from None
    if (any(params.get(k) for k in ('hostaddr', 'service', 'servicefile', 'options'))
            or any(os.environ.get(k) for k in ('PGHOST', 'PGHOSTADDR', 'PGSERVICE', 'PGSERVICEFILE', 'PGOPTIONS'))
            or not params.get('host') or ',' in params['host']
            or ',' in params.get('port', '') or not params.get('user')
            or not params.get('password') or not params.get('dbname')):
        raise CutoverError('An explicit single-host connection is required.')
    local = params['host'].startswith('/') or params['host'] in ('127.0.0.1', '::1', 'localhost')
    if not local and params.get('sslmode') != 'verify-full':
        raise CutoverError('Remote connections require verified TLS.')
    return params


def validate_credentials(credentials):
    """Require direct/pool endpoint pairs that differ only by rotated secret."""
    direct = _params(credentials.admin_direct)
    pooled = _params(credentials.admin_pool)
    for new_dsn, old_dsn in ((credentials.admin_direct, credentials.old_direct),
                             (credentials.admin_pool, credentials.old_pool)):
        new, old = _params(new_dsn), _params(old_dsn)
        if new['password'] == old['password']:
            raise CutoverError('Administrator credential has not changed.')
        ignored = {'password', 'application_name', 'connect_timeout'}
        if {k:v for k,v in new.items() if k not in ignored} != {k:v for k,v in old.items() if k not in ignored}:
            raise CutoverError('Old and new credential endpoints differ.')
    if direct['dbname'] != pooled['dbname'] or direct['password'] != pooled['password']:
        raise CutoverError('Direct and pool recovery credentials differ.')
    if (direct['host'], direct.get('port', '5432')) == (pooled['host'], pooled.get('port', '5432')):
        raise CutoverError('Separate direct and pooled endpoints are required.')
    # Supabase session and transaction pool routes use the same project suffix.
    # A true direct endpoint may instead encode that suffix in its hostname.
    def remote_identity(params):
        host, user = params['host'], params['user']
        if host.endswith('.pooler.supabase.com') and '.' in user:
            login, project = user.rsplit('.', 1)
            return login, project
        if host.startswith('db.') and host.endswith('.supabase.co'):
            return user, host[len('db.'):-len('.supabase.co')]
        if host.startswith('/') or host in ('localhost', '127.0.0.1', '::1'):
            return user, 'local'
        raise CutoverError('Unrecognized database endpoint identity.')
    if remote_identity(direct) != remote_identity(pooled):
        raise CutoverError('Recovery endpoints identify different projects or roles.')


def _connect(dsn):
    try:
        return psycopg.connect(dsn, autocommit=True, connect_timeout=5,
                               application_name='mentorly_cutover_operator')
    except psycopg.Error:
        raise CutoverError('Verified operator connection is unavailable.') from None


def _old_rejected(dsn, *, verified_endpoint=False):
    """Connectivity or TLS errors cannot establish credential invalidation."""
    try:
        conn = psycopg.connect(dsn, autocommit=True, connect_timeout=5)
    except psycopg.Error as exc:
        if exc.sqlstate == '28P01':
            return
        # libpq connection-establishment failures often lose SQLSTATE. A real
        # local SCRAM rehearsal confirms this exact canonical FATAL form. Only
        # accept it after a successful replacement login to the same validated
        # endpoint; remote validation requires verify-full TLS. Never accept a
        # generic connection failure, unknown user, TLS error, or timeout.
        if verified_endpoint:
            params = _params(dsn)
            users = [params['user']]
            if params['host'].endswith('.pooler.supabase.com'):
                users.append(params['user'].rsplit('.', 1)[0])
            for user in users:
                pattern = r'(?:^|\n|failed:\s*)FATAL:\s+password authentication failed for user "' + re.escape(user) + r'"\s*$'
                if re.search(pattern, str(exc)):
                    return
        raise CutoverError('Old credential rejection is unproven.') from None
    else:
        conn.close()
        raise CutoverError('An old credential can still connect.')


def expected_history():
    directory = Path(__file__).parents[1] / 'backend/tests/fixtures/legacy_postgres_runtime'
    files = sorted(directory.glob('000*.sql'))
    if len(files) != 6:
        raise CutoverError('Exact historical fixture set is unavailable.')
    return [(p.stem.split('_', 1)[0], p.stem.split('_', 1)[1],
             hashlib.sha256(p.read_bytes()).hexdigest()) for p in files]


def verify_history(conn, source_schema='viva_app'):
    if not NAME.fullmatch(source_schema):
        raise CutoverError('Invalid source schema identity.')
    observed = conn.execute(sql.SQL('SELECT version,name,checksum FROM {}.schema_migrations ORDER BY version')
                            .format(sql.Identifier(source_schema))).fetchall()
    if observed != expected_history():
        raise CutoverError('Historical migration checksums differ.')
    return observed


def preflight(credentials, source_schema='viva_app'):
    """Read-only post-reset checks. Does not establish a maintenance window."""
    validate_credentials(credentials)
    identities = []
    for dsn in (credentials.admin_direct, credentials.admin_pool):
        with _connect(dsn) as conn, conn.transaction():
            conn.execute('SET TRANSACTION READ ONLY')
            identity = conn.execute('SELECT current_user,session_user,current_database()').fetchone()
            if identity[0] != identity[1]:
                raise CutoverError('Use an explicit operator login without SET ROLE.')
            verify_history(conn, source_schema)
            identities.append(identity)
    if identities[0] != identities[1]:
        raise CutoverError('Direct and pool operator identities differ.')
    for dsn in (credentials.old_direct, credentials.old_pool):
        _old_rejected(dsn, verified_endpoint=True)
    return identities[0]


def fence_sessions(credentials, *, admission_stopped, workers_drained, source_schema='viva_app'):
    """Terminate prior sessions only after two recovery endpoints are verified.

    Boolean arguments are explicit operator attestations, not platform proof.
    This affects every client using the shared legacy/operator login. The
    caller must separately verify immutable deployment URLs and provider work.
    """
    if admission_stopped is not True or workers_drained is not True:
        raise CutoverError('Verified maintenance and worker drain are required.')
    identity = preflight(credentials, source_schema)
    with _connect(credentials.admin_direct) as conn:
        verify_history(conn, source_schema)
        rows = conn.execute("""SELECT pid,pg_terminate_backend(pid) FROM pg_stat_activity
            WHERE usename=%s AND datname=current_database() AND pid<>pg_backend_pid()
            AND backend_type='client backend'""", (identity[0],)).fetchall()
        if any(not terminated for _, terminated in rows):
            raise CutoverError('A legacy session could not be terminated.')
        if conn.execute("""SELECT EXISTS(SELECT 1 FROM pg_stat_activity
            WHERE usename=%s AND datname=current_database() AND pid<>pg_backend_pid()
            AND backend_type='client backend')""", (identity[0],)).fetchone()[0]:
            raise CutoverError('A legacy session remains or reconnected.')
        for dsn in (credentials.old_direct, credentials.old_pool):
            _old_rejected(dsn, verified_endpoint=True)
    return {'terminated_sessions': len(rows), 'database_fence_verified': True,
            'external_provider_quiescence_verified': False}


def _prepare_coordination(conn):
    """Install RLS only on tables atomically created by this transaction."""
    if conn.execute("SELECT to_regnamespace('viva_provider_coordination') IS NOT NULL").fetchone()[0]:
        rows = conn.execute("SELECT c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='viva_provider_coordination' AND c.relname IN ('accounts','leases')").fetchall()
        if len(rows) != 2 or not all(row[0] for row in rows):
            raise CutoverError('Existing coordination RLS requires independent continuity review.')
        return
    # No IF NOT EXISTS: a concurrent creator makes this abort, rather than
    # silently enabling RLS on somebody else's already active coordination.
    conn.execute('CREATE SCHEMA viva_provider_coordination')
    conn.execute(ACCOUNT_DDL)
    for table in ('accounts', 'leases'):
        conn.execute(sql.SQL('ALTER TABLE viva_provider_coordination.{} ENABLE ROW LEVEL SECURITY').format(sql.Identifier(table)))


def provision_target(credentials, *, fence_verified, account_key,
                     schema='mentorly_prod_v100_20261116', role='mentorly_prod_v100_20261116_runtime',
                     password=None, source_schema='viva_app'):
    """Copy into fresh names; retain partial new objects on failure for diagnosis.

    No traffic is activated. Return the new runtime DSN only to a protected
    credential store, never stdout. Requires an externally maintained fence.
    """
    if fence_verified is not True or not account_key:
        raise CutoverError('A verified external fence and provider account are required.')
    if (not NAME.fullmatch(schema) or not NAME.fullmatch(role) or schema == source_schema
            or schema.startswith('pg_') or schema in ('public', 'information_schema')):
        raise CutoverError('Invalid fresh target identity.')
    preflight(credentials, source_schema)
    password = password or secrets.token_urlsafe(48)
    with _connect(credentials.admin_direct) as conn:
        history = verify_history(conn, source_schema)
        if conn.execute('SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=%s) OR EXISTS(SELECT 1 FROM pg_roles WHERE rolname=%s)', (schema, role)).fetchone()[0]:
            raise CutoverError('Target schema and role must both be fresh.')
        with conn.transaction():
            _prepare_coordination(conn)
            conn.execute(sql.SQL('CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}')
                         .format(sql.Identifier(role), sql.Literal(password)))
            # Transaction poolers can switch backends between autocommit SET
            # and the next query. Establish defaults at backend login as well.
            conn.execute(sql.SQL('ALTER ROLE {} SET search_path TO {}, pg_catalog').format(sql.Identifier(role), sql.Identifier(schema)))
            for setting, value in (('timezone', 'UTC'), ('statement_timeout', '15s'), ('lock_timeout', '5s')):
                conn.execute(sql.SQL('ALTER ROLE {} SET {} TO {}').format(sql.Identifier(role), sql.Identifier(setting), sql.Literal(value)))
    target = PostgresTarget(credentials.admin_direct, schema)
    initialize(target)
    with frozen_legacy_schema(target, source_schema) as frozen:
        result = copy_legacy_schema(target, source_schema, history, frozen_connection=frozen,
                                    legacy_speech_account_key=account_key,
                                    retain_expired_request_leases=True)
        # PostgreSQL CREATEROLE does not imply SET ROLE membership or permission
        # to transfer ownership. Keep DDL under the verified operator; runtime
        # receives only the privileges its ordinary application queries need.
        frozen.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(sql.Identifier(schema), sql.Identifier(role)))
        frozen.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA {} TO {}').format(sql.Identifier(schema), sql.Identifier(role)))
        frozen.execute(sql.SQL('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}').format(sql.Identifier(schema), sql.Identifier(role)))
        frozen.execute(sql.SQL('GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA {} TO {}').format(sql.Identifier(schema), sql.Identifier(role)))
        digest = grant_account(frozen, role, account_key)
        verify_isolation(frozen, role, schema, digest)
        for dsn in (credentials.old_direct, credentials.old_pool):
            _old_rejected(dsn, verified_endpoint=True)
    params = _params(credentials.admin_pool)
    # Hosted poolers require <runtime-role>.<project-ref>; direct/libpq users do
    # not. The runtime uses the verified pool route, avoiding IPv6-only hosts.
    suffix = params['user'].rsplit('.', 1)[1] if params['host'].endswith('.pooler.supabase.com') else None
    params.update(user=role + ('.' + suffix if suffix else ''), password=password)
    # Settings accepts PostgreSQL URLs, whereas operator input may use libpq
    # keyword strings. Preserve all verified TLS options in the runtime URL.
    user, secret = params.pop('user'), params.pop('password')
    database, host = params.pop('dbname'), params.pop('host')
    port = params.pop('port', '5432')
    if host.startswith('/'):
        params['host'] = host
        host = 'localhost'
    elif ':' in host:
        host = '[' + host + ']'
    runtime_dsn = ('postgresql://' + quote(user, safe='') + ':' + quote(secret, safe='')
                   + '@' + host + ':' + port + '/' + quote(database, safe='')
                   + ('?' + urlencode(params) if params else ''))
    # Restricted runtime startup must not require database-wide CREATE.
    initialize(PostgresTarget(runtime_dsn, schema))
    return {'schema': schema, 'role': role, 'runtime_dsn': runtime_dsn, 'copy': result}
