import enum
import uuid

from sqlalchemy import Enum, Float, ForeignKey, String, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.mixins import TimestampMixin, UUIDPKMixin
from app.core.database import Base


class FacilityType(str, enum.Enum):
    NURSING_HOME = "nursing_home"
    DOCTOR_CHAMBER = "doctor_chamber"
    PHARMACY = "pharmacy"


class Facility(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "facilities"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    name: Mapped[str] = mapped_column(String(200), index=True)
    facility_type: Mapped[FacilityType] = mapped_column(Enum(FacilityType))
    address: Mapped[str] = mapped_column(String(500))
    city: Mapped[str] = mapped_column(String(100), index=True, default="Bolpur")
    state: Mapped[str] = mapped_column(String(100), default="West Bengal")
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)

    # Per-facility booking price — NOT global. Admin can override.
    booking_fee: Mapped[float] = mapped_column(Float, default=10.0)
    # Admin-overridable per-facility commission %, falls back to global default
    # in config if null.
    commission_percent_override: Mapped[float | None] = mapped_column(Float, nullable=True)
    cancellation_deduction_percent_override: Mapped[float | None] = mapped_column(Float, nullable=True)

    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_ad_sponsored: Mapped[bool] = mapped_column(Boolean, default=False)  # "Sponsored" tag

    doctors: Mapped[list["Doctor"]] = relationship(back_populates="facility", cascade="all, delete-orphan")


class Doctor(Base, UUIDPKMixin, TimestampMixin):
    """A doctor's profile. Multiple doctors can sit under one facility, each
    with a fully independent schedule + queue (per Section 5 of the spec)."""

    __tablename__ = "doctors"

    facility_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("facilities.id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    full_name: Mapped[str] = mapped_column(String(150))
    qualification: Mapped[str] = mapped_column(String(300))
    specialty: Mapped[str] = mapped_column(String(150), index=True)
    consultation_fee: Mapped[float] = mapped_column(Float, default=0.0)
    photo_storage_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    facility: Mapped["Facility"] = relationship(back_populates="doctors")
    availability_slots: Mapped[list["DoctorAvailability"]] = relationship(
        back_populates="doctor", cascade="all, delete-orphan"
    )


class DoctorAvailability(Base, UUIDPKMixin, TimestampMixin):
    """Weekly recurring schedule. day_of_week: 0=Monday ... 6=Sunday.
    A row with is_leave=True on a specific `leave_date` overrides that date."""

    __tablename__ = "doctor_availability"

    doctor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("doctors.id"))
    day_of_week: Mapped[int | None] = mapped_column(nullable=True)  # null if this row is a one-off leave day
    start_time: Mapped[str] = mapped_column(String(5))  # "HH:MM" 24h
    end_time: Mapped[str] = mapped_column(String(5))
    slot_duration_minutes: Mapped[int] = mapped_column(default=15)

    is_leave: Mapped[bool] = mapped_column(Boolean, default=False)
    leave_date: Mapped[str | None] = mapped_column(String(10), nullable=True)  # "YYYY-MM-DD"

    doctor: Mapped["Doctor"] = relationship(back_populates="availability_slots")
