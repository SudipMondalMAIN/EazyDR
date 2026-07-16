import enum
import uuid

from sqlalchemy import Enum, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.mixins import TimestampMixin, UUIDPKMixin
from app.core.database import Base


class EarningEntryType(str, enum.Enum):
    CREDIT_BOOKING = "credit_booking"     # facility's cut of a booking fee
    DEBIT_WITHDRAWAL = "debit_withdrawal"  # payout sent via Paytm Payout API


class EarningLedgerEntry(Base, UUIDPKMixin, TimestampMixin):
    """Ledger-only balance for facilities — platform never 'holds' real money
    on their behalf; a withdrawal triggers a real payout API call. This is
    what keeps the platform outside RBI PPI licensing (see spec section 4)."""

    __tablename__ = "earning_ledger_entries"

    facility_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("facilities.id"), index=True)
    entry_type: Mapped[EarningEntryType] = mapped_column(Enum(EarningEntryType))
    amount: Mapped[float] = mapped_column(Float)  # always positive; sign implied by entry_type
    related_booking_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    payout_transaction_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)


class WithdrawalStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"


class WithdrawalRequest(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "withdrawal_requests"

    facility_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("facilities.id"), index=True)
    amount: Mapped[float] = mapped_column(Float)
    status: Mapped[WithdrawalStatus] = mapped_column(Enum(WithdrawalStatus), default=WithdrawalStatus.PENDING)
    payout_transaction_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
