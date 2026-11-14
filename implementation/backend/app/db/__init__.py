"""SQLite WAL persistence, versioned migrations, and Phase 0 repository interfaces."""

from .migrations import (
    AppliedMigration,
    MigrationError,
    apply_migrations,
    get_applied_migrations,
    open_connection,
)
from .repository import (
    CodeSaveResult,
    CodeVersionRecord,
    IdempotencyCheckResult,
    IdempotencyConflictError,
    IdempotencyRecord,
    RepositoryError,
    RevisionConflictError,
    SQLiteRepository,
    SessionDeletedError,
    SessionNotFoundError,
    SessionRecord,
    SessionRepository,
)

__all__ = [
    "AppliedMigration",
    "CodeSaveResult",
    "CodeVersionRecord",
    "IdempotencyCheckResult",
    "IdempotencyConflictError",
    "IdempotencyRecord",
    "MigrationError",
    "RepositoryError",
    "RevisionConflictError",
    "SQLiteRepository",
    "SessionDeletedError",
    "SessionNotFoundError",
    "SessionRecord",
    "SessionRepository",
    "apply_migrations",
    "get_applied_migrations",
    "open_connection",
]
