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
from app.modules.auth.schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.services import otp_service
from app.services.storage_service import storage_service


async def register_user(db: AsyncSession, payload: RegisterRequest) -> User:
    if payload.role in (UserRole.ADMIN, UserRole.SUPERADMIN):
        # Admin accounts must be created by an existing SuperAdmin via the
        # admin module, never via public self-registration.
        raise BadRequestError("Admin accounts cannot self-register")

    existing_phone = (
        await db.execute(select(User).where(User.phone == payload.phone))
    ).scalar_one_or_none()
    existing_email = (
        await db.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()

    # A row that matches on phone or email but was never OTP-verified isn't
    # a "real" account yet — most likely the same person abandoned the
    # signup flow before entering the OTP (closed the tab, hit back, etc).
    # Block only if it's the SAME unverified row on both fields; a genuine
    # conflict (phone taken by one unverified row, email by a different
    # one) still needs to be rejected so we don't silently merge accounts.
    stale_user = None
    if existing_phone and existing_email:
        if existing_phone.id == existing_email.id and not existing_phone.is_email_verified:
            stale_user = existing_phone
        elif existing_phone.is_email_verified or existing_email.is_email_verified:
            raise ConflictError("Phone number or email already registered")
        elif existing_phone.id != existing_email.id:
            raise ConflictError("Phone number or email already registered")
    elif existing_phone:
        if existing_phone.is_email_verified:
            raise ConflictError("Phone number already registered")
        stale_user = existing_phone
    elif existing_email:
        if existing_email.is_email_verified:
            raise ConflictError("Email already registered")
        stale_user = existing_email

    if stale_user:
        # Resume signup: overwrite the abandoned row with the latest
        # details/password the user just submitted and send a fresh OTP.
        stale_user.full_name = payload.full_name
        stale_user.phone = payload.phone
        stale_user.email = payload.email
        stale_user.password_hash = hash_password(payload.password)
        stale_user.role = payload.role
        user = stale_user
    else:
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


async def verify_signup_otp(db: AsyncSession, email: str, otp: str) -> TokenResponse:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise BadRequestError("No account found for this email")

    await otp_service.verify_otp(email, otp, "signup")

    user.is_email_verified = True
    await db.commit()
    await db.refresh(user)
    return issue_tokens(user)


async def authenticate(db: AsyncSession, payload: LoginRequest) -> User:
    result = await db.execute(select(User).where(User.phone == payload.phone))
    user = result.scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise UnauthorizedError("Invalid phone number or password")
    if not user.is_active:
        raise UnauthorizedError("Account is disabled")
    if not user.is_email_verified:
        raise UnauthorizedError("Please verify your email with the OTP sent to it before logging in")
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
    if not user.is_email_verified:
        raise UnauthorizedError("Please verify your email with the OTP sent to it before logging in")

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


def attach_photo_url(user: User) -> UserOut:
    out = UserOut.model_validate(user)
    if user.photo_storage_key:
        out.photo_url = storage_service.get_public_url(user.photo_storage_key)
    return out


async def update_profile_photo(db: AsyncSession, user: User, storage_key: str) -> User:
    # Best-effort cleanup of the old photo — a failed delete shouldn't block
    # the user from setting their new one.
    if user.photo_storage_key:
        try:
            await storage_service.delete_file(user.photo_storage_key)
        except Exception:
            pass
    user.photo_storage_key = storage_key
    await db.commit()
    await db.refresh(user)
    return user


async def refresh_access_token(db: AsyncSession, refresh_token: str) -> TokenResponse:
    payload = decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise UnauthorizedError("Invalid refresh token")

    result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise UnauthorizedError("User not found or disabled")

    return issue_tokens(user)
