import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import ForbiddenError
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user, require_admin, require_patient
from app.modules.auth.models import User, UserRole
from app.modules.bookings import service
from app.modules.facilities.service import get_facility
from app.modules.bookings.schemas import (
    BookingCreate,
    BookingOut,
    BookingWithQrOut,
    CancelBookingRequest,
    CancelBookingResult,
)

router = APIRouter(prefix="/api/v1/bookings", tags=["bookings"])


@router.post("", response_model=BookingWithQrOut, status_code=201)
async def create_booking(
    payload: BookingCreate, db: AsyncSession = Depends(get_db), user: User = Depends(require_patient)
):
    booking, qr_base64 = await service.create_booking(db, user.id, payload)
    out = BookingWithQrOut.model_validate(booking)
    out.qr_code_base64 = qr_base64
    return out


@router.get("/my", response_model=list[BookingOut])
async def my_bookings(db: AsyncSession = Depends(get_db), user: User = Depends(require_patient)):
    return await service.list_bookings_for_patient(db, user.id)


@router.get("/{booking_id}", response_model=BookingOut)
async def get_booking(booking_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    booking = await service.get_booking(db, booking_id)
    if booking.patient_id == user.id or user.role in (UserRole.ADMIN, UserRole.SUPERADMIN):
        return booking
    if user.role == UserRole.MERCHANT:
        # A merchant may only view bookings made at a facility they own —
        # not any booking on the platform (was previously unchecked, which
        # leaked other facilities' patient names/phones/addresses).
        facility = await get_facility(db, booking.facility_id)
        if facility.owner_user_id == user.id:
            return booking
    raise ForbiddenError("Not your booking")


@router.post("/{booking_id}/cancel", response_model=CancelBookingResult)
async def cancel_booking(
    booking_id: uuid.UUID,
    payload: CancelBookingRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_patient),
):
    booking = await service.get_booking(db, booking_id)
    if booking.patient_id != user.id:
        raise ForbiddenError("Not your booking")
    booking, refund_points, deduction = await service.cancel_booking(db, booking, facility_fault=False)
    return CancelBookingResult(
        booking_id=booking.id,
        status=booking.status,
        refund_reward_points=refund_points,
        deduction_percent_applied=deduction,
    )


@router.post("/{booking_id}/grace-refund", response_model=CancelBookingResult)
async def grace_refund(
    booking_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Admin-triggered full refund for a severely delayed queue — bypasses
    the 5-hour cancellation lock since the delay is the facility's fault,
    not the patient's (spec section 5)."""
    booking = await service.get_booking(db, booking_id)
    booking, refund_points, deduction = await service.cancel_booking(db, booking, facility_fault=True)
    return CancelBookingResult(
        booking_id=booking.id,
        status=booking.status,
        refund_reward_points=refund_points,
        deduction_percent_applied=deduction,
    )
