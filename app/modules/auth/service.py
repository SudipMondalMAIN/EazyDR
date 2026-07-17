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
from app.services import otp_service


async def register_user(db: AsyncSession, payload: RegisterRequest) -> User:
    existing = await db.execute(select(User).where(User.phone == payload.phone))
    if existing.scalar_one_or_none():
        raise ConflictError("Phone number already registered")

    existing_email = await db.execute(select(User).where(User.email == payload.email))
    if existing_email.scalar_one_or_none():
        raise ConflictError("Email already registered")

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

    # Kick off email verification OTP (signup). Delivery failures don't
    # block account creation — the client can call the resend endpoint.
    await otp_service.request_otp(user.email, "signup")
    return user


async def verify_signup_otp(db: AsyncSession, email: str, otp: str) -> User:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise BadRequestError("No account found for this email")

    await otp_service.verify_otp(email, otp, "signup")

    user.is_email_verified = True
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


async def request_login_otp(db: AsyncSession, phone: str, password: str) -> str:
    """Verifies phone+password, then emails a login OTP. Returns the user's
    email (masked by the caller/router if desired) so the client knows
    where the code was sent."""
    result = await db.execute(select(User).where(User.phone == phone))
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        raise UnauthorizedError("Invalid phone number or password")
    if not user.is_active:
        raise UnauthorizedError("Account is disabled")

    await otp_service.request_otp(user.email, "login")
    return user.email


async def verify_login_otp(db: AsyncSession, email: str, otp: str) -> User:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise UnauthorizedError("Invalid email or OTP")

    await otp_service.verify_otp(email, otp, "login")

    if not user.is_active:
        raise UnauthorizedError("Account is disabled")
    return user


async def request_password_reset(db: AsyncSession, email: str) -> None:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        # Don't reveal whether the email is registered.
        return
    await otp_service.request_otp(user.email, "forgot_password")


async def reset_password(db: AsyncSession, email: str, otp: str, new_password: str) -> None:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise BadRequestError("Invalid email or OTP")

    await otp_service.verify_otp(email, otp, "forgot_password")

    user.password_hash = hash_password(new_password)
    await db.commit()


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
