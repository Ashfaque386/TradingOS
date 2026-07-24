"""Login endpoint (Phase 4 exit-criteria gap). See src/core/security.py's module docstring for
what this real-but-reduced auth layer covers relative to the full Phase_12 design.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select, update

from src.api.deps import get_current_user
from src.core.db import get_session
from src.core.security import create_access_token, verify_password
from src.models.user import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: uuid.UUID
    role: str


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest) -> LoginResponse:
    with get_session() as session:
        user = session.scalars(select(User).where(User.email == body.email)).first()
        # Constant-shape response whether the email doesn't exist or the password is wrong --
        # never reveal which one via a different error, since that lets an attacker enumerate
        # valid emails.
        if user is None or not verify_password(body.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password"
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is inactive"
            )

        # Use the DB's own clock (func.now()) rather than Python's, and update via a targeted
        # statement instead of mutating the detached-after-commit ORM object.
        session.execute(update(User).where(User.id == user.id).values(last_login_at=func.now()))
        session.commit()

        token = create_access_token(user_id=str(user.id), role=user.role)
        return LoginResponse(access_token=token, user_id=user.id, role=user.role)


class CurrentUserResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    role: str


@router.get("/me", response_model=CurrentUserResponse)
def me(user: User = Depends(get_current_user)) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=user.id, email=user.email, full_name=user.full_name, role=user.role
    )
