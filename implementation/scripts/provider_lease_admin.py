"""Private operator tooling for PostgreSQL provider leases; never calls Gnani."""

import argparse
import json
import sqlite3

from backend.app.core.config import get_settings
from backend.app.db.postgres.account_dispatch import (
    AccountDispatcher,
    DispatchUnavailable,
    Lease,
)
from backend.app.db.postgres.runtime import PostgresTarget


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
    capacity = sub.add_parser("capacity")
    capacity.add_argument("--current", type=int, required=True)
    capacity.add_argument("--new", type=int, required=True)
    capacity.add_argument(
        "--workers-stopped-and-entitlement-verified", action="store_true", required=True
    )
    resolve = sub.add_parser("resolve")
    resolve.add_argument("--lease-id", required=True)
    resolve.add_argument("--fence", type=int, required=True)
    resolve.add_argument(
        "--provider-quiescence-confirmed", action="store_true", required=True
    )
    args = parser.parse_args()
    settings = get_settings()
    target = settings.database_target
    if not isinstance(target, PostgresTarget) or settings.gnani_api_key is None:
        raise SystemExit(
            "An explicit PostgreSQL target and configured provider account are required."
        )
    old_capacity = (
        args.current
        if args.action == "capacity"
        else min(settings.gnani_max_concurrency, settings.gnani_verified_concurrency)
    )
    dispatcher = AccountDispatcher(
        target,
        account_key=settings.gnani_api_key.get_secret_value(),
        capacity=old_capacity,
    )
    if args.action == "capacity":
        dispatcher.reconfigure_capacity(args.new)
        report = {"status": "CAPACITY_UPDATED", "capacity": args.new}
    elif args.action == "resolve":
        dispatcher.finish(Lease(args.lease_id, args.fence))
        report = {"status": "LEASE_RESOLVED"}
    else:
        with target.connect() as conn:
            rows = conn.execute(
                """SELECT id,fence,state,expires_at FROM viva_provider_coordination.leases
                WHERE account_hash=%s AND state<>'RELEASED' ORDER BY fence""",
                (dispatcher.account_hash,),
            ).fetchall()
        report = {
            "capacity": dispatcher.capacity,
            "leases": [
                {
                    "id": row[0],
                    "fence": row[1],
                    "state": row[2],
                    "expires_at": row[3].isoformat(),
                }
                for row in rows
            ],
        }
    print(json.dumps(report))


if __name__ == "__main__":
    try:
        main()
    except (DispatchUnavailable, ValueError, sqlite3.Error) as exc:
        raise SystemExit(str(exc)) from None
