import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import require_admin, require_merchant
from app.modules.auth.models import User
from app.modules.queue import service
from app.modules.queue.schemas import CheckInResult, LiveQueueOut, ManualCheckInRequest, QrCheckInRequest

router = APIRouter(prefix="/api/v1/queue", tags=["queue"])


@router.post("/check-in/qr", response_model=CheckInResult)
async def check_in_qr(
    payload: QrCheckInRequest, db: AsyncSession = Depends(get_db), user: User = Depends(require_merchant)
):
    booking = await service.check_in_by_qr(db, payload.qr_uuid, payload.signature, user.id)
    return CheckInResult(
        booking_id=booking.id,
        patient_name=booking.patient_name,
        doctor_id=booking.doctor_id,
        token_number=booking.token_number,
        status=booking.status.value,
        checked_in_at=booking.checked_in_at.isoformat(),
    )


@router.post("/check-in/manual", response_model=CheckInResult)
async def check_in_manual(
    payload: ManualCheckInRequest, db: AsyncSession = Depends(get_db), user: User = Depends(require_merchant)
):
    booking = await service.check_in_manual(
        db, payload.doctor_id, payload.appointment_date, payload.booking_id, payload.patient_phone, user.id
    )
    return CheckInResult(
        booking_id=booking.id,
        patient_name=booking.patient_name,
        doctor_id=booking.doctor_id,
        token_number=booking.token_number,
        status=booking.status.value,
        checked_in_at=booking.checked_in_at.isoformat(),
    )


@router.get("/live/{doctor_id}", response_model=LiveQueueOut)
async def live_queue(doctor_id: uuid.UUID, date: str, db: AsyncSession = Depends(get_db)):
    current_token, is_stalled = await service.get_live_queue(db, doctor_id, date)
    return LiveQueueOut(doctor_id=doctor_id, queue_date=date, current_token=current_token, is_stalled=is_stalled)


@router.get("/stalled", response_model=list[str])
async def stalled_queues(db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    """Admin dashboard alert feed — queues stuck 15+ minutes, candidates for
    the follow-up call to the facility (spec section 5)."""
    states = await service.find_stalled_queues(db)
    return [str(s.doctor_id) for s in states]
