import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestError
from app.core.config import settings
from app.modules.facilities.models import Facility
from app.modules.facilities.service import verify_facility_owner
from app.modules.rewards.earning_models import (
    EarningEntryType,
    EarningLedgerEntry,
    WithdrawalRequest,
    WithdrawalStatus,
)
from app.modules.rewards.models import RewardEntryType, RewardLedgerEntry
from app.services.payment_service import payment_service


# ---------------- Reward points (patient side) ----------------

async def get_reward_balance(db: AsyncSession, user_id: uuid.UUID) -> int:
    credits = await db.execute(
        select(func.coalesce(func.sum(RewardLedgerEntry.points), 0)).where(
            RewardLedgerEntry.user_id == user_id,
            RewardLedgerEntry.entry_type.in_([RewardEntryType.CREDIT_REFUND, RewardEntryType.CREDIT_PROMO]),
        )
    )
    debits = await db.execute(
        select(func.coalesce(func.sum(RewardLedgerEntry.points), 0)).where(
            RewardLedgerEntry.user_id == user_id,
            RewardLedgerEntry.entry_type == RewardEntryType.DEBIT_REDEMPTION,
        )
    )
    return int(credits.scalar_one()) - int(debits.scalar_one())


async def credit_reward_points(
    db: AsyncSession, user_id: uuid.UUID, points: int, booking_id: uuid.UUID | None, note: str
) -> RewardLedgerEntry:
    entry = RewardLedgerEntry(
        user_id=user_id,
        entry_type=RewardEntryType.CREDIT_REFUND,
        points=points,
        related_booking_id=booking_id,
        note=note,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


# ---------------- Facility earnings (merchant side) ----------------

async def get_earning_balance(db: AsyncSession, facility_id: uuid.UUID) -> float:
    credits = await db.execute(
        select(func.coalesce(func.sum(EarningLedgerEntry.amount), 0)).where(
            EarningLedgerEntry.facility_id == facility_id,
            EarningLedgerEntry.entry_type == EarningEntryType.CREDIT_BOOKING,
        )
    )
    debits = await db.execute(
        select(func.coalesce(func.sum(EarningLedgerEntry.amount), 0)).where(
            EarningLedgerEntry.facility_id == facility_id,
            EarningLedgerEntry.entry_type == EarningEntryType.DEBIT_WITHDRAWAL,
        )
    )
    return float(credits.scalar_one()) - float(debits.scalar_one())


async def credit_facility_earning(
    db: AsyncSession, facility_id: uuid.UUID, amount: float, booking_id: uuid.UUID, note: str
) -> EarningLedgerEntry:
    entry = EarningLedgerEntry(
        facility_id=facility_id,
        entry_type=EarningEntryType.CREDIT_BOOKING,
        amount=amount,
        related_booking_id=booking_id,
        note=note,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


async def request_withdrawal(
    db: AsyncSession, facility_id: uuid.UUID, amount: float, merchant_user_id: uuid.UUID
) -> WithdrawalRequest:
    # CRITICAL: without this check any merchant could drain any other
    # facility's earnings ledger to their own bank/UPI via the Paytm
    # Payout API just by guessing/enumerating a facility_id.
    await verify_facility_owner(db, facility_id, merchant_user_id)
    if amount < settings.min_withdrawal_amount:
        raise BadRequestError(f"Minimum withdrawal amount is {settings.min_withdrawal_amount}")

    # CRITICAL: lock this facility's row for the rest of the transaction
    # before reading the balance. Without this, two concurrent withdrawal
    # requests can both read the same balance (e.g. ₹500), both pass the
    # `amount > balance` check for a ₹400 withdrawal, and both insert a
    # debit — draining ₹800 from a ₹500 balance (double-withdraw / TOCTOU
    # race). SELECT ... FOR UPDATE makes the second request's transaction
    # block until the first commits, so it re-reads the *post-debit*
    # balance and correctly gets rejected if funds are no longer sufficient.
    # This only serializes requests for the *same* facility_id — other
    # facilities' withdrawals are unaffected.
    await db.execute(select(Facility.id).where(Facility.id == facility_id).with_for_update())

    balance = await get_earning_balance(db, facility_id)
    if amount > balance:
        raise BadRequestError("Insufficient earnings balance")

    withdrawal = WithdrawalRequest(facility_id=facility_id, amount=amount, status=WithdrawalStatus.PENDING)
    db.add(withdrawal)
    await db.commit()
    await db.refresh(withdrawal)

    # NOTE: actual Paytm Payout API call is a stub for now — see
    # app/services/payment_service.py header for the security-review caveat.
    # In production this should be dispatched to a background worker
    # (Celery), not called inline in the request/response cycle.
    debit = EarningLedgerEntry(
        facility_id=facility_id,
        entry_type=EarningEntryType.DEBIT_WITHDRAWAL,
        amount=amount,
        note=f"Withdrawal request {withdrawal.id} (payout pending Paytm integration)",
    )
    db.add(debit)
    withdrawal.status = WithdrawalStatus.PROCESSING
    await db.commit()
    await db.refresh(withdrawal)
    return withdrawal
