"""Disposable rehearsal primitive for a persistent legacy write fence.

Requires privileged operator DDL. Not a substitute for traffic isolation or an
independent audit of every credential and database object in production.
"""
from psycopg import sql

from .legacy_upgrade import UpgradeError, frozen_legacy_schema


def install_legacy_fence(target, source_schema, writer_role):
    """Install transactional write-rejection triggers for one restricted role.

    Locks cover installation; triggers persist after commit. The role must not
    own objects, inherit their owners, have CREATE on the schema, or be able to
    assume a superuser. Every actual writer role must be validated separately.
    """
    with frozen_legacy_schema(target, source_schema) as conn:
        role = conn.execute('SELECT oid FROM pg_roles WHERE rolname=%s', (writer_role,)).fetchone()
        if not role:
            raise UpgradeError('Writer role does not exist.')
        unsafe = conn.execute('''SELECT EXISTS (
            SELECT 1 FROM pg_roles r WHERE r.rolsuper AND pg_has_role(%s, r.oid, 'MEMBER')
        ) OR has_schema_privilege(%s, %s, 'CREATE') OR EXISTS (
            SELECT 1 FROM pg_namespace n WHERE n.nspname=%s AND pg_has_role(%s,n.nspowner,'MEMBER')
        ) OR EXISTS (
            SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=%s AND c.relkind IN ('r','p') AND pg_has_role(%s,c.relowner,'MEMBER')
        )''', (role[0], role[0], source_schema, source_schema, role[0], source_schema, role[0])).fetchone()[0]
        if unsafe:
            raise UpgradeError('Writer role can bypass or alter the fence.')
        tables = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename", (source_schema,)).fetchall()
        schema = sql.Identifier(source_schema)
        conn.execute(sql.SQL("""CREATE FUNCTION {}.viva_reject_legacy_writes() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'legacy schema write fence active'; END $$""").format(schema))
        for (table,) in tables:
            conn.execute(sql.SQL('CREATE TRIGGER viva_legacy_write_fence BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON {}.{} FOR EACH STATEMENT EXECUTE FUNCTION {}.viva_reject_legacy_writes()').format(schema, sql.Identifier(table), schema))
