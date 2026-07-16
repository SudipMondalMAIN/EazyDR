import uuid

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.mixins import TimestampMixin, UUIDPKMixin
from app.core.database import Base


class CashSettlementBatch(Base, UUIDPKMixin, TimestampMixin):
    """One settlement 'run' against a facility for its accumulated cash-booking
    platform commission. Append-only, like the reward/earning ledgers —
    never edited after creation, only ever created. The per-booking marking
    (Booking.cash_commission_settled = True) happens in the same DB
    transaction as this row, so every booking can be traced back to the
    batch that settled it via `related_booking_ids`.
    """

    __tablename__ = "cash_settlement_batches"

    facility_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("facilities.id"), index=True)
    settled_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    booking_count: Mapped[int] = mapped_column(Integer)
    total_commission_amount: Mapped[float] = mapped_column(Float)

    # Comma-joined booking UUIDs settled in this batch. Denormalized on
    # purpose — this is a small admin-facing audit trail, not a hot path,
    # so a join table would be overkill.
    related_booking_ids: Mapped[str] = mapped_column(String)

    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
