"""Explicit learning-flow availability errors."""
from backend.app.db.repository import RevisionConflictError


class TransferUnavailableError(RevisionConflictError):
    """The session has exhausted its unseen transfer-case pool."""
