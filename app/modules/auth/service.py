from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestError, ConflictError, UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.modules.auth.models import User, UserRole
from app.modules.auth.schemas import LoginRequest, RegisterRequest, TokenResponse


async def register_user(db: AsyncSession, payload: RegisterRequest) -> User:
    existing = await db.execute(select(User).where(User.phone == payload.phone))
    if existing.scalar_one_or_none():
        raise ConflictError("Phone number already registered")

    if payload.role in (UserRole.ADMIN, UserRole.SUPERADMIN):
        # Admin accounts must be created by an existing SuperAdmin via the
        # admin module, never via public self-registration.
        raise BadRequestError("Admin accounts cannot self-register")

    user = User(
        full_name=payload.full_name,
        phone=payload.phone,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate(db: AsyncSession, payload: LoginRequest) -> User:
    result = await db.execute(select(User).where(User.phone == payload.phone))
    user = result.scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise UnauthorizedError("Invalid phone number or password")
    if not user.is_active:
        raise UnauthorizedError("Account is disabled")
    return user


def issue_tokens(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(str(user.id), user.role.value),
        refresh_token=create_refresh_token(str(user.id)),
    )


async def refresh_access_token(db: AsyncSession, refresh_token: str) -> TokenResponse:
    payload = decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise UnauthorizedError("Invalid refresh token")

    result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise UnauthorizedError("User not found or disabled")

    return issue_tokens(user)
