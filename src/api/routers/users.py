"""User management endpoints (API-002/003 from the original Phase 10 spec -- never implemented
until this router). SystemAdministrator-only, per Phase_12_Security_Design.md §2.2 (only SA
manages accounts; nothing in the matrix grants any other role user-creation rights).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from src.api.deps import require_role
from src.core.db import get_session
from src.core.security import ALL_ROLES, ROLE_SYSTEM_ADMINISTRATOR, hash_password
from src.models.user import User

router = APIRouter(
    prefix="/api/v1/users",
    tags=["users"],
    dependencies=[Depends(require_role(ROLE_SYSTEM_ADMINISTRATOR))],
)


class CreateUserRequest(BaseModel):
    email: str
    password: str
    full_name: str | None = None
    role: str


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    role: str
    is_active: bool


@router.get("", response_model=list[UserResponse])
def list_users() -> list[UserResponse]:
    with get_session() as session:
        users = session.scalars(select(User).order_by(User.created_at))
        return [
            UserResponse(
                id=u.id, email=u.email, full_name=u.full_name, role=u.role, is_active=u.is_active
            )
            for u in users
        ]


@router.post("", response_model=UserResponse, status_code=201)
def create_user(body: CreateUserRequest) -> UserResponse:
    if body.role not in ALL_ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"role must be one of {ALL_ROLES}",
        )
    with get_session() as session:
        existing = session.scalars(select(User).where(User.email == body.email)).first()
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
            )

        user = User(
            email=body.email,
            hashed_password=hash_password(body.password),
            full_name=body.full_name,
            role=body.role,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return UserResponse(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=user.role,
            is_active=user.is_active,
        )
