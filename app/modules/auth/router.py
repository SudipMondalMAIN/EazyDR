from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth import service
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.auth.schemas import (
    ForgotPasswordRequest,
    LoginOTPRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    RequestOTPRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserOut,
    VerifyLoginOTPRequest,
    VerifySignupOTPRequest,
)
from app.services import otp_service

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=201)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # An email OTP is sent automatically on register; call
    # /auth/otp/verify-signup to confirm the address.
    user = await service.register_user(db, payload)
    return user


@router.post("/otp/request", status_code=204)
async def request_otp(payload: RequestOTPRequest):
    """Send/resend an OTP by email. purpose: signup | login | forgot_password."""
    await otp_service.request_otp(payload.email, payload.purpose)


@router.post("/otp/verify-signup", response_model=UserOut)
async def verify_signup_otp(payload: VerifySignupOTPRequest, db: AsyncSession = Depends(get_db)):
    return await service.verify_signup_otp(db, payload.email, payload.otp)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await service.authenticate(db, payload)
    return service.issue_tokens(user)


@router.post("/login-otp/request", status_code=204)
async def login_otp_request(payload: LoginOTPRequest, db: AsyncSession = Depends(get_db)):
    """Step 1 of email-OTP login: verify phone+password, email an OTP."""
    await service.request_login_otp(db, payload.phone, payload.password)


@router.post("/login-otp/verify", response_model=TokenResponse)
async def login_otp_verify(payload: VerifyLoginOTPRequest, db: AsyncSession = Depends(get_db)):
    """Step 2 of email-OTP login: exchange the emailed OTP for tokens."""
    user = await service.verify_login_otp(db, payload.email, payload.otp)
    return service.issue_tokens(user)


@router.post("/forgot-password", status_code=204)
async def forgot_password(payload: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    await service.request_password_reset(db, payload.email)


@router.post("/reset-password", status_code=204)
async def reset_password(payload: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    await service.reset_password(db, payload.email, payload.otp, payload.new_password)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, db: AsyncSession = Depends(get_db)):
    return await service.refresh_access_token(db, payload.refresh_token)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user
