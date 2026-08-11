"""Bootstraps the one Paper trading Account this system's agents trade with (REL-034).

Idempotent, mirroring scripts/seed_admin_user.py: re-running finds the existing Account row
rather than creating a duplicate. Requires an existing SystemAdministrator user
(scripts/seed_admin_user.py must run first) -- the same ordering dependency that script itself
already documents.

Matched on `broker == "PAPER"` (this script's own sentinel), not just `account_type == "Paper"`:
confirmed live against this project's own dev database that the full pytest suite creates its
own `Account` test fixtures with `account_type="Paper"` and a real broker value (`"Zerodha"`)
that persist in the SAME shared dev Postgres after the test run ends (tests don't run against an
isolated database here) -- matching on `account_type` alone would silently adopt one of those
~20 fixture rows as "the" account instead of creating the real one this script owns.

Also backfills any pre-existing `paper_trades.account_id IS NULL` rows to the seeded account --
covers both the case where this script runs before alembic/versions/a3b4c5d6e7f8's own opportunistic
backfill (nothing to backfill yet, a no-op) and after it (redundant but harmless). Run this before
alembic/versions/b4c5d6e7f8a9 (the NOT NULL cutover), which will otherwise fail loudly if any
row is still unbackfilled -- that failure is deliberate, see that migration's own docstring.

Usage: docker compose exec app python scripts/seed_paper_account.py
"""

import os
from decimal import Decimal

from sqlalchemy import select, text

from src.core.db import get_session
from src.core.security import ROLE_SYSTEM_ADMINISTRATOR
from src.models.account import Account
from src.models.user import User

STARTING_CAPITAL = Decimal(os.environ.get("PAPER_ACCOUNT_STARTING_CAPITAL", "100000.00"))


def main() -> None:
    with get_session() as session:
        account = session.scalars(
            select(Account).where(Account.broker == "PAPER", Account.account_type == "Paper")
        ).first()

        if account is None:
            admin = session.scalars(
                select(User).where(User.role == ROLE_SYSTEM_ADMINISTRATOR).order_by(User.created_at)
            ).first()
            if admin is None:
                raise RuntimeError(
                    "No SystemAdministrator user found -- run scripts/seed_admin_user.py first."
                )
            account = Account(
                user_id=admin.id,
                broker="PAPER",  # sentinel: no real broker credential backs this account
                account_type="Paper",
                capital_allocated=STARTING_CAPITAL,
                currency="INR",
                is_active=True,
            )
            session.add(account)
            session.flush()
            action = "Created"
        else:
            action = "Found existing"

        backfilled = session.execute(
            text("UPDATE paper_trades SET account_id = :account_id WHERE account_id IS NULL"),
            {"account_id": account.id},
        ).rowcount
        session.commit()

        print(
            f"{action} Paper account: {account.id} "
            f"(capital_allocated={account.capital_allocated})"
        )
        if backfilled:
            print(f"Backfilled {backfilled} pre-existing paper_trades row(s) to this account.")


if __name__ == "__main__":
    main()
