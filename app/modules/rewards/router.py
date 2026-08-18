import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user, require_merchant
from app.modules.auth.models import User
from app.modules.facilities.service import verify_facility_owner
from app.modules.rewards import service

router = APIRouter(prefix="/api/v1/rewards", tags=["rewards"])


class RewardBalanceOut(BaseModel):
    user_id: uuid.UUID
    points: int


class EarningBalanceOut(BaseModel):
    facility_id: uuid.UUID
    balance: float


class WithdrawalCreate(BaseModel):
    facility_id: uuid.UUID
    amount: float


class WithdrawalOut(BaseModel):
    id: uuid.UUID
    facility_id: uuid.UUID
    amount: float
    status: str
    payout_transaction_ref: str | None = None
    failure_reason: str | None = None
    created_at: str


@router.get("/balance", response_model=RewardBalanceOut)
async def my_reward_balance(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    points = await service.get_reward_balance(db, user.id)
    return RewardBalanceOut(user_id=user.id, points=points)


@router.get("/earnings/{facility_id}", response_model=EarningBalanceOut)
async def facility_earning_balance(
    facility_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_merchant)
):
    await verify_facility_owner(db, facility_id, user.id)
    balance = await service.get_earning_balance(db, facility_id)
    return EarningBalanceOut(facility_id=facility_id, balance=balance)


@router.post("/withdrawals")
async def withdraw(
    payload: WithdrawalCreate, db: AsyncSession = Depends(get_db), user: User = Depends(require_merchant)
):
    withdrawal = await service.request_withdrawal(db, payload.facility_id, payload.amount, user.id)
    return {
        "id": withdrawal.id,
        "status": withdrawal.status,
        "amount": withdrawal.amount,
    }


@router.get("/withdrawals/{facility_id}", response_model=list[WithdrawalOut])
async def list_withdrawals(
    facility_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_merchant)
):
    """History of withdrawal requests for one of the merchant's own
    facilities, most recent first."""
    await verify_facility_owner(db, facility_id, user.id)
    withdrawals = await service.list_withdrawals_for_facility(db, facility_id)
    return [
        WithdrawalOut(
            id=w.id,
            facility_id=w.facility_id,
            amount=w.amount,
            status=w.status.value,
            payout_transaction_ref=w.payout_transaction_ref,
            failure_reason=w.failure_reason,
            created_at=w.created_at.isoformat(),
        )
        for w in withdrawals
    ]
