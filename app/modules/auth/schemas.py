import uuid

from pydantic import BaseModel, EmailStr, Field

from app.modules.auth.models import UserRole


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    phone: str = Field(min_length=10, max_length=15)
    email: EmailStr
    password: str = Field(min_length=6, max_length=100)
    role: UserRole = UserRole.PATIENT


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=3, description="Email or phone number")
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: uuid.UUID
    full_name: str
    phone: str
    email: EmailStr
    role: UserRole
    is_active: bool
    is_phone_verified: bool
    is_email_verified: bool
    photo_storage_key: str | None = None
    photo_url: str | None = None

    class Config:
        from_attributes = True


# ---------- Email OTP (signup / login / forgot-password) ----------
# OTP is always delivered by email only — never SMS.

class RequestOTPRequest(BaseModel):
    email: EmailStr
    purpose: str = Field(pattern="^(signup|login|forgot_password)$")


class VerifySignupOTPRequest(BaseModel):
    email: EmailStr
    otp: str = Field(min_length=4, max_length=8)


class LoginOTPRequest(BaseModel):
    """Step 1 of OTP login: verify identifier (email or phone) + password,
    then email an OTP."""

    identifier: str = Field(min_length=3, description="Email or phone number")
    password: str


class VerifyLoginOTPRequest(BaseModel):
    """Step 2 of OTP login: exchange the emailed OTP for tokens."""

    email: EmailStr
    otp: str = Field(min_length=4, max_length=8)


class ForgotPasswordRequest(BaseModel):
    identifier: str = Field(min_length=3, description="Email or phone number")


class ResetPasswordRequest(BaseModel):
    identifier: str = Field(min_length=3, description="Email or phone number")
    otp: str = Field(min_length=4, max_length=8)
    new_password: str = Field(min_length=6, max_length=100)


class UpdateProfileRequest(BaseModel):
    """Full profile edit for the logged-in user. Changing phone/email
    re-locks the corresponding verified flag (email OTP re-verification
    required again if email changes)."""

    full_name: str | None = Field(default=None, min_length=2, max_length=150)
    phone: str | None = Field(default=None, min_length=10, max_length=15)
    email: EmailStr | None = None


class PushTokenRequest(BaseModel):
    device_push_token: str = Field(min_length=10, max_length=255)