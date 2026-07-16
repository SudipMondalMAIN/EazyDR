import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.mixins import TimestampMixin, UUIDPKMixin
from app.core.database import Base


class QueueState(Base, UUIDPKMixin, TimestampMixin):
    """One row per (doctor, date). Tracks the current token being served so
    the live-queue screen has a fast single-row read instead of scanning all
    bookings, and so the 15-minute-stall fallback has a `last_advanced_at`
    to compare against."""

    __tablename__ = "queue_states"
    __table_args__ = (UniqueConstraint("doctor_id", "queue_date", name="uq_queue_doctor_date"),)

    doctor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("doctors.id"), index=True)
    queue_date: Mapped[str] = mapped_column(String(10))  # "YYYY-MM-DD"

    current_token: Mapped[int] = mapped_column(Integer, default=0)  # 0 = not started yet
    last_advanced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    stall_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated_to_admin: Mapped[bool] = mapped_column(Boolean, default=False)
