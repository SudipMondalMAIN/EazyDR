import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import require_admin
from app.modules.auth.models import User
from app.modules.settlements import service
from app.modules.settlements.schemas import (
    CashSettlementBatchOut,
    FacilityCashOutstandingOut,
    PendingCashBookingOut,
    SettleCashCommissionRequest,
)

router = APIRouter(prefix="/api/v1/admin/settlements", tags=["settlements"])


@router.get("/summary", response_model=list[FacilityCashOutstandingOut])
async def outstanding_summary(db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    """Per-facility outstanding cash commission — the report to work off of."""
    return await service.get_outstanding_summary(db)


@router.get("/facilities/{facility_id}/pending", response_model=list[PendingCashBookingOut])
async def pending_bookings(
    facility_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
):
    bookings = await service.get_pending_bookings_for_facility(db, facility_id)
    return [
        PendingCashBookingOut(
            booking_id=b.id,
            appointment_date=b.appointment_date,
            patient_name=b.patient_name,
            booking_fee=b.booking_fee,
            platform_commission_amount=b.platform_commission_amount,
            status=b.status.value,
        )
        for b in bookings
    ]


@router.post("/facilities/{facility_id}/settle", response_model=CashSettlementBatchOut)
async def settle(
    facility_id: uuid.UUID,
    payload: SettleCashCommissionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Mark cash commission as settled for a facility — everything currently
    outstanding if `booking_ids` is omitted, or just that subset otherwise."""
    return await service.settle_cash_commission(db, user.id, facility_id, payload.booking_ids, payload.note)


@router.get("/history", response_model=list[CashSettlementBatchOut])
async def history(
    facility_id: uuid.UUID | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    return await service.get_settlement_history(db, facility_id, limit)
