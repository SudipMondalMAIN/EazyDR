import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.mixins import TimestampMixin, UUIDPKMixin
from app.core.database import Base


class BookingStatus(str, enum.Enum):
    PENDING = "pending"              # created, awaiting payment or just cash-confirmed
    CONFIRMED = "confirmed"          # payment settled (or cash accepted) — QR is live
    CHECKED_IN = "checked_in"        # QR scanned at facility, "with doctor"
    COMPLETED = "completed"          # implied once next patient scanned, or admin can force
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class PaymentMode(str, enum.Enum):
    CASH = "cash"
    ONLINE = "online"


class Booking(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "bookings"
    __table_args__ = (
        # Prevents the token-number race condition: two concurrent bookings
        # for the same doctor/day computing the same MAX(token_number)+1 will
        # have one of them rejected at the DB level instead of silently
        # producing duplicate tokens.
        UniqueConstraint(
            "doctor_id", "appointment_date", "token_number", name="uq_booking_doctor_date_token"
        ),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("facilities.id"), index=True)
    doctor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("doctors.id"), index=True)

    patient_name: Mapped[str] = mapped_column(String(150))
    patient_phone: Mapped[str] = mapped_column(String(20))
    patient_address: Mapped[str] = mapped_column(String(500))

    token_number: Mapped[int] = mapped_column(Integer)
    appointment_date: Mapped[str] = mapped_column(String(10))   # "YYYY-MM-DD"
    expected_time: Mapped[str] = mapped_column(String(5))       # "HH:MM"

    booking_fee: Mapped[float] = mapped_column(Float)
    platform_commission_amount: Mapped[float] = mapped_column(Float)
    facility_earning_amount: Mapped[float] = mapped_column(Float)

    payment_mode: Mapped[PaymentMode] = mapped_column(Enum(PaymentMode))
    payment_transaction_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # For cash bookings: commission owed to platform but not yet collected —
    # settled later via manual/periodic reconciliation with the facility.
    cash_commission_settled: Mapped[bool] = mapped_column(default=False)

    status: Mapped[BookingStatus] = mapped_column(Enum(BookingStatus), default=BookingStatus.PENDING, index=True)

    # Booking UUID embedded in the QR — kept distinct from primary key `id`
    # so it can be rotated/invalidated independently if ever needed.
    qr_uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, index=True)
    qr_signature: Mapped[str] = mapped_column(String(128))

    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_refund_points: Mapped[int] = mapped_column(Integer, default=0)

    # Set by the Celery "send-appointment-reminders" beat task once the
    # 30-min-before push has gone out, so a booking never gets reminded twice.
    reminder_sent: Mapped[bool] = mapped_column(default=False)
