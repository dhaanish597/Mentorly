"""Authenticated scheduled maintenance entry point for shared PostgreSQL."""
from fastapi import APIRouter, Header, Request

from backend.app.core.errors import ApiAppException
from backend.app.db.migrations import database_target
from backend.app.db.postgres.maintenance import run_once
from backend.app.db.postgres.runtime import PostgresTarget
from backend.app.operations.readiness import _require_operator

router = APIRouter(prefix="/ops", tags=["operations"])


@router.get("/maintenance", include_in_schema=False)
async def scheduled_maintenance(
    request: Request, authorization: str | None = Header(default=None)
) -> dict[str, str]:
    """Run one fenced sweep without exposing tenant or retention details."""
    _require_operator(request, authorization)
    if not isinstance(database_target(request.app.state.settings), PostgresTarget):
        raise ApiAppException(status_code=503, code="MAINTENANCE_UNAVAILABLE", message="Maintenance is unavailable.")
    result = await run_once(request.app)
    if result.get("status") != "COMPLETE":
        raise ApiAppException(status_code=503, code="MAINTENANCE_INCOMPLETE", message="Maintenance did not complete.")
    return {"status": "complete"}
