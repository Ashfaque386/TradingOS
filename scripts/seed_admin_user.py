"""Bootstraps the first SystemAdministrator user (Phase 4 exit-criteria gap: there was no way to
create a user at all before src/api/routers/users.py existed, and that router itself requires an
existing SystemAdministrator to call -- a chicken-and-egg problem an open unauthenticated
"create the first user" endpoint would solve unsafely. This script is the intended bootstrap
path instead: run once per environment via `docker exec tradingos-app python scripts/seed_admin_user.py`.

Idempotent: re-running with the same email updates the existing row's password/role rather than
erroring or creating a duplicate (the `users.email` column has a UNIQUE constraint).

Credentials come from env vars with dev-only defaults, matching the `jwt_secret_key`
("dev-only-change-me") pattern already established in src/core/config.py -- change both before
any real deployment.
"""

import os

from sqlalchemy import select

from src.core.db import get_session
from src.core.security import ROLE_SYSTEM_ADMINISTRATOR, hash_password
from src.models.user import User

ADMIN_EMAIL = os.environ.get("ADMIN_BOOTSTRAP_EMAIL", "admin@tradingos.local")
ADMIN_PASSWORD = os.environ.get("ADMIN_BOOTSTRAP_PASSWORD", "dev-only-change-me")


def main() -> None:
    with get_session() as session:
        user = session.scalars(select(User).where(User.email == ADMIN_EMAIL)).first()
        if user is None:
            user = User(
                email=ADMIN_EMAIL,
                hashed_password=hash_password(ADMIN_PASSWORD),
                full_name="Bootstrap Administrator",
                role=ROLE_SYSTEM_ADMINISTRATOR,
            )
            session.add(user)
            action = "Created"
        else:
            user.hashed_password = hash_password(ADMIN_PASSWORD)
            user.role = ROLE_SYSTEM_ADMINISTRATOR
            user.is_active = True
            action = "Updated"
        session.commit()

    print(f"{action} SystemAdministrator user: {ADMIN_EMAIL}")
    if ADMIN_PASSWORD == "dev-only-change-me":
        print(
            "WARNING: using the default dev-only password. Set ADMIN_BOOTSTRAP_PASSWORD before "
            "running this against any shared or production database."
        )


if __name__ == "__main__":
    main()
