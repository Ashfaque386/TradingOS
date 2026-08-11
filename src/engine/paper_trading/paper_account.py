"""The one canonical way to find the seeded Paper trading Account (REL-034).

Matched on `broker == "PAPER"` (scripts/seed_paper_account.py's own sentinel), not just
`account_type == "Paper"` -- confirmed live against this project's own dev database that the
pytest suite leaves its own `account_type="Paper"` fixture rows (`broker="Zerodha"`) behind in
this same shared database. Every caller that needs "the" paper account uses this one function so
that filter can never drift out of sync between callers.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.account import Account


def get_paper_account(session: Session) -> Account:
    account = session.scalars(
        select(Account).where(Account.broker == "PAPER", Account.account_type == "Paper")
    ).first()
    if account is None:
        raise RuntimeError(
            "No seeded Paper account found -- run scripts/seed_paper_account.py first."
        )
    return account
