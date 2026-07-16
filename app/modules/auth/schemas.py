import uuid

from pydantic import BaseModel, EmailStr, Field

from app.modules.auth.models import UserRole


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    phone: str = Field(min_length=10, max_length=15)
    email: EmailStr | None = None
    password: str = Field(min_length=6, max_length=100)
    role: UserRole = UserRole.PATIENT


class LoginRequest(BaseModel):
    phone: str
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
    email: EmailStr | None
    role: UserRole
    is_active: bool
    is_phone_verified: bool

    class Config:
        from_attributes = True
