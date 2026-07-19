import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.mixins import TimestampMixin, UUIDPKMixin
from app.core.database import Base


class Review(Base, UUIDPKMixin, TimestampMixin):
    """A patient's rating/comment on a COMPLETED booking. One review per
    booking (enforced at the DB level) — doctor_id/facility_id are
    denormalized from the booking at creation time so listing a doctor's or
    facility's reviews never needs a join back through bookings."""

    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("booking_id", name="uq_review_booking"),
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_review_rating_range"),
    )

    booking_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("bookings.id"), index=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    doctor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("doctors.id"), index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("facilities.id"), index=True)

    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Admin moderation — a flagged review can be hidden from public listings
    # without deleting it outright (keeps the audit trail, mirrors the
    # ledger-style "never hard-delete history" pattern used elsewhere).
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
