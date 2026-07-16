import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.mixins import TimestampMixin, UUIDPKMixin
from app.core.database import Base


class RewardEntryType(str, enum.Enum):
    CREDIT_REFUND = "credit_refund"       # cancellation refund issued as points
    CREDIT_PROMO = "credit_promo"         # admin-issued promo credit
    DEBIT_REDEMPTION = "debit_redemption"  # points spent on a future booking


class RewardLedgerEntry(Base, UUIDPKMixin, TimestampMixin):
    """Append-only ledger. Current balance = SUM(credits) - SUM(debits) for a
    user; deliberately not a single mutable 'balance' column so history is
    always auditable (mirrors the facility earnings ledger design)."""

    __tablename__ = "reward_ledger_entries"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    entry_type: Mapped[RewardEntryType] = mapped_column(Enum(RewardEntryType))
    points: Mapped[int] = mapped_column(Integer)  # always positive; sign implied by entry_type
    related_booking_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
