"""Shared test helper for creating an authenticated user + bearer token (Phase 4 exit-criteria
gap: JWT auth, src/core/security.py + src/api/deps.py). Every integration test that exercises a
require_role-gated endpoint imports this rather than re-deriving password hashing/token creation
per file.
"""

import uuid

from src.core.db import get_session
from src.core.security import create_access_token, hash_password
from src.models.user import User


def create_authenticated_user(role: str) -> tuple[uuid.UUID, str]:
    user_id = uuid.uuid4()
    with get_session() as session:
        session.add(
            User(
                id=user_id,
                email=f"auth-test-{user_id}@example.invalid",
                hashed_password=hash_password("test-password-123"),
                role=role,
            )
        )
        session.commit()
    token = create_access_token(user_id=str(user_id), role=role)
    return user_id, token


def cleanup_user(user_id: uuid.UUID) -> None:
    with get_session() as session:
        session.query(User).filter(User.id == user_id).delete()
        session.commit()


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
