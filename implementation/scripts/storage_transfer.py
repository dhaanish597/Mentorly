"""Explicit private offline storage transfer; does not deploy or cut over."""

import argparse
import json
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.db.postgres.runtime import PostgresTarget
from backend.app.db.postgres.transfer import export_sqlite, import_postgres


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    export = sub.add_parser("export")
    export.add_argument("--source", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    load = sub.add_parser("import")
    load.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "export":
        report = export_sqlite(args.source, args.output)
    else:
        target = get_settings().database_target
        if not isinstance(target, PostgresTarget):
            raise SystemExit(
                "Set an explicit private PostgreSQL URL via VCC_DATABASE_URL/VCC_ENV_FILE."
            )
        report = import_postgres(target, args.snapshot)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
