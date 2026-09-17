"""Backfill existing Tin users; dry-run unless --apply is supplied. Never imports Clerk users."""

import argparse
import asyncio
import json

from tin_lite.billing import BillingService
from tin_lite.db import Database
from tin_lite.settings import Settings


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--env-file", action="append", default=[])
    args = parser.parse_args()
    settings = Settings(_env_file=tuple(args.env_file or [".env"]))
    if not settings.billing_enabled or not settings.billing_welcome_credits_enabled:
        raise RuntimeError("Hosted billing and welcome credits must be explicitly enabled")
    database = Database(settings.runtime_dsn)
    await database.connect()
    try:
        users = await database.pool.fetch(
            """SELECT u.clerk_user_id FROM tin_users u
               WHERE NOT EXISTS(SELECT 1 FROM billing_welcome_grants g
                                WHERE g.clerk_user_id=u.clerk_user_id)
               ORDER BY u.first_signed_in_at, u.clerk_user_id LIMIT 10000"""
        )
        result = {"apply": args.apply, "users_without_grant": len(users), "granted": 0}
        if args.apply:
            service = BillingService(database=database, settings=settings)
            for user in users:
                result["granted"] += int(await service.grant_welcome_credit(user["clerk_user_id"]))
            result["awaiting_workspace_or_admin"] = len(users) - result["granted"]
        print(json.dumps(result))
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
