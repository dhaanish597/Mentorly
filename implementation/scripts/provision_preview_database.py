"""Prepare protected staging credentials; apply only to a disposable LOCAL DB.

Remote DDL is deliberately unavailable. After review and explicit authorization,
use the reviewed provision() procedure from an approved operator environment.
The privileged DSN must never enter Vercel Preview configuration.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
from urllib.parse import quote, urlencode

import psycopg
from psycopg import sql
from backend.app.db.postgres.runtime import PostgresTarget, initialize

NAME = re.compile(r'[a-z][a-z0-9_]{0,62}\Z')
SCHEMA = 'mentorly_preview_20261115'
ROLE = SCHEMA + '_runtime'


def verify_isolation(conn, role, schema, account_hash=None):
    """Fail closed on inherited/PUBLIC privileges, including privileged functions."""
    unsafe = conn.execute('''SELECT n.nspname,c.relname FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname<>%s AND n.nspname NOT IN ('pg_catalog','information_schema')
        AND n.nspname NOT LIKE 'pg_toast%%' AND c.relkind IN ('r','p','v','m','f')
        AND ((has_schema_privilege(%s,n.oid,'USAGE')
              AND (has_table_privilege(%s,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
                   OR has_any_column_privilege(%s,c.oid,'SELECT,INSERT,UPDATE,REFERENCES')))
             OR pg_has_role(%s,c.relowner,'MEMBER'))''', (schema,role,role,role,role)).fetchall()
    schemas = conn.execute('''SELECT nspname FROM pg_namespace WHERE nspname<>%s
        AND nspname NOT LIKE 'pg_%%' AND nspname<>'information_schema'
        AND has_schema_privilege(%s,oid,'CREATE')''',(schema,role)).fetchall()
    sequences = conn.execute('''SELECT n.nspname,c.relname FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname<>%s
        AND n.nspname NOT LIKE 'pg_%%' AND c.relkind='S'
        AND CASE WHEN c.relkind='S' THEN has_sequence_privilege(%s,c.oid,'USAGE,SELECT,UPDATE') ELSE false END''',(schema,role)).fetchall()
    # The built-in PL/pgSQL handler rejects event_trigger functions outside an
    # event-trigger invocation before executing their body. PUBLIC EXECUTE on
    # these functions is not direct-call access. This does not approve attached
    # event-trigger behavior; operators must separately inspect installed DDL
    # handlers. Ordinary SECURITY DEFINER functions remain a hard failure.
    functions = conn.execute('''SELECT p.oid::regprocedure::text FROM pg_proc p
        JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname<>%s AND p.prosecdef
        AND NOT (p.prokind='f' AND p.prorettype='pg_catalog.event_trigger'::regtype
                 AND p.prolang=(SELECT oid FROM pg_catalog.pg_language WHERE lanname='plpgsql'))
        AND has_schema_privilege(%s,n.oid,'USAGE') AND has_function_privilege(%s,p.oid,'EXECUTE')''',
        (schema,role,role)).fetchall()
    flags = conn.execute('SELECT rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=%s',(role,)).fetchone()
    if account_hash is not None:
        allowed = {('viva_provider_coordination', 'accounts'), ('viva_provider_coordination', 'leases')}
        unsafe = [item for item in unsafe if item not in allowed]
        sequences = [item for item in sequences if item != ('viva_provider_coordination', 'leases_fence_seq')]
        verify_account_grants(conn, role, account_hash)
    if unsafe or schemas or sequences or functions or flags != (False,False,False,False,False,False):
        raise ValueError('Staging role isolation failed; existing grants or privileged functions require separate review')


def account_digest(key):
    return hashlib.sha256(('viva-gnani-account-v1:' + key).encode()).hexdigest()


def grant_account(conn, role, key, capacity=1):
    """Local rehearsal only; requires separately reviewed, preinstalled RLS.

    Runtime role is trusted application code: its own lease updates are not
    constrained by a database-enforced state machine.
    """
    if capacity != 1 or not key:
        raise ValueError('Only an explicitly identified single-slot account is supported')
    # This helper must never enable RLS on shared tables: doing so could
    # silently deny existing production coordinators. The operator must have
    # separately reviewed and installed RLS with policies for every existing role.
    rls = conn.execute("SELECT c.relname,c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='viva_provider_coordination' AND c.relname IN ('accounts','leases')").fetchall()
    if len(rls) != 2 or not all(enabled for _, enabled in rls):
        raise ValueError('Provider coordination RLS must be preinstalled and existing role continuity independently reviewed')
    digest = account_digest(key)
    conn.execute("INSERT INTO viva_provider_coordination.accounts VALUES(%s,%s) ON CONFLICT (account_hash) DO NOTHING", (digest, capacity))
    if conn.execute('SELECT capacity FROM viva_provider_coordination.accounts WHERE account_hash=%s', (digest,)).fetchone() != (capacity,):
        raise ValueError('Provider account capacity mismatch')
    for table in ('accounts', 'leases'):
        policy = 'preview_' + role + '_' + table
        conn.execute(sql.SQL('CREATE POLICY {} ON viva_provider_coordination.{} TO {} USING (account_hash = {}) WITH CHECK (account_hash = {})').format(sql.Identifier(policy), sql.Identifier(table), sql.Identifier(role), sql.Literal(digest), sql.Literal(digest)))
    conn.execute(sql.SQL('GRANT USAGE ON SCHEMA viva_provider_coordination TO {}').format(sql.Identifier(role)))
    conn.execute(sql.SQL('GRANT SELECT, INSERT ON viva_provider_coordination.accounts TO {}').format(sql.Identifier(role)))
    conn.execute(sql.SQL('GRANT UPDATE(account_hash) ON viva_provider_coordination.accounts TO {}').format(sql.Identifier(role)))
    conn.execute(sql.SQL('GRANT SELECT, INSERT, UPDATE ON viva_provider_coordination.leases TO {}').format(sql.Identifier(role)))
    conn.execute(sql.SQL('GRANT USAGE ON SEQUENCE viva_provider_coordination.leases_fence_seq TO {}').format(sql.Identifier(role)))
    return digest


def verify_account_grants(conn, role, digest):
    """Reject policy widening, ownership, role membership, and capacity updates."""
    rows = conn.execute("""SELECT c.relname, c.relrowsecurity, pg_has_role(%s,c.relowner,'MEMBER'),
        p.polname, p.polpermissive, pg_get_expr(p.polqual,p.polrelid), pg_get_expr(p.polwithcheck,p.polrelid),
        p.polroles FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        LEFT JOIN pg_policy p ON p.polrelid=c.oid
        WHERE n.nspname='viva_provider_coordination' AND c.relname IN ('accounts','leases')""", (role,)).fetchall()
    role_oid = conn.execute('SELECT oid FROM pg_roles WHERE rolname=%s', (role,)).fetchone()[0]
    expected = f"(account_hash = '{digest}'::text)"
    for table in ('accounts', 'leases'):
        applicable = [r for r in rows if r[0] == table and r[3] is not None and (0 in r[7] or role_oid in r[7])]
        if len(applicable) != 1:
            raise ValueError('Staging role isolation failed; unsafe provider policies')
        row = applicable[0]
        if not row[1] or row[2] or not row[4] or row[5] != expected or row[6] != expected or row[7] != [role_oid]:
            raise ValueError('Staging role isolation failed; unsafe provider policy')
    dangerous = conn.execute("SELECT has_table_privilege(%s,'viva_provider_coordination.accounts','DELETE,TRUNCATE,REFERENCES,TRIGGER') OR has_table_privilege(%s,'viva_provider_coordination.leases','DELETE,TRUNCATE,REFERENCES,TRIGGER') OR has_sequence_privilege(%s,'viva_provider_coordination.leases_fence_seq','UPDATE')", (role,role,role)).fetchone()[0]
    if dangerous:
        raise ValueError('Staging role isolation failed; excessive provider privileges')
    if conn.execute("SELECT has_column_privilege(%s,'viva_provider_coordination.accounts','capacity','UPDATE')", (role,)).fetchone()[0]:
        raise ValueError('Staging role isolation failed; provider capacity writable')
    if conn.execute('SELECT EXISTS(SELECT 1 FROM pg_auth_members WHERE member=%s)', (role_oid,)).fetchone()[0]:
        raise ValueError('Staging role isolation failed; role membership')


def provision(admin_dsn, schema=SCHEMA, role=ROLE, password=None, account_key=None):
    """Local rehearsal only. Creates fresh objects; existing names are rejected."""
    if not NAME.fullmatch(schema) or not NAME.fullmatch(role):
        raise ValueError('Invalid resource identity')
    params = psycopg.conninfo.conninfo_to_dict(admin_dsn)
    host = params.get('host','')
    # libpq overrides can redirect an apparently local DSN. Reject them before
    # the first connection; accept only a Unix socket or numeric loopback,
    # avoiding hostname resolution and multiple-host failover entirely.
    overrides = ('hostaddr','service','servicefile','options')
    environment_overrides = ('PGHOST','PGHOSTADDR','PGSERVICE','PGSERVICEFILE','PGOPTIONS')
    if (any(key in params for key in overrides)
            or any(os.environ.get(key) for key in environment_overrides)
            or ',' in host or ',' in params.get('port','')
            or not (host.startswith('/') or host in ('127.0.0.1','::1'))
            or not NAME.fullmatch(params.get('dbname','postgres'))):
        raise ValueError('Remote provisioning is disabled; explicit production/staging DDL approval required')
    password = password or secrets.token_urlsafe(48)
    with psycopg.connect(admin_dsn,autocommit=True) as conn:
        if conn.execute('SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=%s) OR EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=%s)',(role,schema)).fetchone()[0]:
            raise ValueError('Use fresh staging resource names')
        # Admin applies migrations before handing schema ownership to the
        # restricted runtime. Failure cleanup touches only these fresh names;
        # privileged global coordination remains admin owned and ungranted.
        conn.execute(sql.SQL('CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}').format(sql.Identifier(role),sql.Literal(password)))
        try:
            initialize(PostgresTarget(admin_dsn,schema))
            with conn.transaction():
                conn.execute(sql.SQL('ALTER SCHEMA {} OWNER TO {}').format(sql.Identifier(schema),sql.Identifier(role)))
                objects = conn.execute("SELECT c.relname,c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relkind IN ('r','p','S','v','m')",(schema,)).fetchall()
                # Tables before their owned identity sequences; table ownership
                # transfers identity sequences automatically.
                for name,kind in sorted(objects,key=lambda row:row[1]=='S'):
                    noun = 'SEQUENCE' if kind=='S' else ('VIEW' if kind=='v' else ('MATERIALIZED VIEW' if kind=='m' else 'TABLE'))
                    conn.execute(sql.SQL('ALTER '+noun+' {}.{} OWNER TO {}').format(sql.Identifier(schema),sql.Identifier(name),sql.Identifier(role)))
                functions = conn.execute('SELECT p.oid::regprocedure::text FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=%s',(schema,)).fetchall()
                for (signature,) in functions:
                    conn.execute(sql.SQL('ALTER FUNCTION {} OWNER TO {}').format(sql.SQL(signature),sql.Identifier(role)))
                digest = grant_account(conn, role, account_key) if account_key else None
                verify_isolation(conn,role,schema,digest)
        except BaseException:
            conn.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(schema)))
            conn.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
            raise
    params.update(user=role,password=password)
    username = params.pop('user')
    secret = params.pop('password')
    database = params.pop('dbname', 'postgres')
    return 'postgresql://' + quote(username,safe='') + ':' + quote(secret,safe='') + '@localhost/' + quote(database,safe='') + '?' + urlencode(params)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-output',type=Path,required=True)
    parser.add_argument('--apply-local-rehearsal',action='store_true')
    args = parser.parse_args()
    password = secrets.token_urlsafe(48)
    output = {'schema':SCHEMA,'role':ROLE,'password':password,'remote_ddl_authorized':False}
    if args.apply_local_rehearsal:
        output['runtime_dsn'] = provision(os.environ['VIVA_POSTGRES_TEST_DSN'],password=password)
    fd = os.open(args.private_output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump(output,stream)
    print('Protected staging preparation written; no remote DDL performed.')


if __name__ == '__main__':
    main()
