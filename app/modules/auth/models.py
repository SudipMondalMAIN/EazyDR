import enum
import uuid

from sqlalchemy import Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.common.mixins import TimestampMixin, UUIDPKMixin
from app.core.database import Base


class UserRole(str, enum.Enum):
    PATIENT = "patient"
    MERCHANT = "merchant"          # pharmacy/nursing-home owner or doctor login
    ADMIN = "admin"                 # normal admin (employee)
    SUPERADMIN = "superadmin"       # founders, full access + 2FA required


class User(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "users"

    full_name: Mapped[str] = mapped_column(String(150))
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(150), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.PATIENT, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_phone_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    # 2FA required for SUPERADMIN role (enforced in auth service, not just UI)
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_2fa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    device_push_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
