import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.mixins import TimestampMixin, UUIDPKMixin
from app.core.database import Base


class Banner(Base, UUIDPKMixin, TimestampMixin):
    """Platform-level marketing banners shown on the home/search screens.
    Managed by admin only. Image lives in StorageService (Cloudinary/local),
    only the storage key is persisted here — never a raw provider URL."""

    __tablename__ = "banners"

    title: Mapped[str] = mapped_column(String(200))
    image_storage_key: Mapped[str] = mapped_column(String(255))
    redirect_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    display_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # "YYYY-MM-DD" strings, same convention as DoctorAvailability.leave_date.
    start_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    end_date: Mapped[str | None] = mapped_column(String(10), nullable=True)


class AdStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAUSED = "paused"


class Advertisement(Base, UUIDPKMixin, TimestampMixin):
    """Merchant-submitted sponsored ads. Once APPROVED, they get a
    "Sponsored" badge and are shown above normal facilities in the
    relevant category/city listings, per spec."""

    __tablename__ = "advertisements"

    merchant_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    facility_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facilities.id"), nullable=True
    )

    title: Mapped[str] = mapped_column(String(200))
    image_storage_key: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(100), index=True)
    city: Mapped[str] = mapped_column(String(100), index=True, default="Bolpur")

    duration_days: Mapped[int] = mapped_column(Integer, default=7)
    # Populated only once the ad is approved (start = approval date).
    start_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    end_date: Mapped[str | None] = mapped_column(String(10), nullable=True)

    status: Mapped[AdStatus] = mapped_column(Enum(AdStatus), default=AdStatus.PENDING, index=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
