"""Standalone PostgreSQL migration primitives; not wired to the application.

These APIs require a psycopg 3-style connection supplied by the caller. They do
not translate or apply the existing SQLite schema.
"""

from .migrations import Migration, MigrationError, apply_migrations

__all__ = ["Migration", "MigrationError", "apply_migrations"]
