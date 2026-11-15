"""Explicit scheduled PostgreSQL retention job; no provider calls or learner execution."""

import asyncio
import json

from backend.app.core.config import get_settings
from backend.app.db.postgres.maintenance import run_once
from backend.app.db.postgres.runtime import PostgresTarget
from backend.app.main import create_app


async def main():
    settings = get_settings()
    if not isinstance(settings.database_target, PostgresTarget):
        raise SystemExit("This scheduled job requires an explicit PostgreSQL target.")
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        report = await run_once(application)
        print(json.dumps(report))
        return 0 if report["status"] in {"COMPLETE", "BUSY"} else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
