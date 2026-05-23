"""Create a user (and household) from the command line, for local development.

Usage:
    uv run python -m scripts.create_user EMAIL PASSWORD DISPLAY_NAME HOUSEHOLD_NAME

If a household with the legacy DEV_HOUSEHOLD_ID already exists (from before the
auth split), pass --adopt-dev to make the new user its owner so existing local
Tier A data stays reachable.
"""

from __future__ import annotations

import argparse
import sys

from app.auth import DEV_HOUSEHOLD_ID
from app.db import SessionLocal
from app.models.core import Household, HouseholdMember, Subscription, User
from app.services.auth.passwords import hash_password


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("email")
    parser.add_argument("password")
    parser.add_argument("display_name")
    parser.add_argument("household_name")
    parser.add_argument(
        "--adopt-dev",
        action="store_true",
        help=(
            "If DEV_HOUSEHOLD_ID exists, make the new user its owner instead of creating a new"
            " household."
        ),
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        if db.query(User).filter_by(email=args.email.lower()).one_or_none():
            print(f"error: email {args.email} already exists", file=sys.stderr)
            return 1

        user = User(
            email=args.email.lower(),
            hashed_password=hash_password(args.password),
            display_name=args.display_name,
        )
        db.add(user)
        db.flush()

        household = None
        if args.adopt_dev:
            household = db.get(Household, DEV_HOUSEHOLD_ID)
        if household is None:
            household = Household(name=args.household_name)
            db.add(household)
            db.flush()

        db.add(
            HouseholdMember(
                user_id=user.id,
                household_id=household.id,
                role="owner",
            )
        )
        db.add(
            Subscription(
                user_id=user.id,
                plan="free",
                status="active",
                tier_a_enabled=True,
                tier_b_enabled=True,
                tier_s_enabled=False,
            )
        )
        db.commit()
        print(
            f"created user {user.email} (id={user.id})"
            f" in household {household.name} (id={household.id})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
