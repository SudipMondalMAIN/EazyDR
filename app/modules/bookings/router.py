import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import ForbiddenError
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user, require_admin, require_merchant, require_patient
from app.modules.auth.models import User, UserRole
from app.modules.bookings import service
from app.modules.facilities.service import get_facility, verify_facility_owner
from app.modules.bookings.models import BookingStatus
from app.modules.bookings.schemas import (
    BookingCreate,
    BookingListItemOut,
    BookingOut,
    BookingWithQrOut,
    CancelBookingRequest,
    CancelBookingResult,
    FacilityBookingListItemOut,
    QueueStatusOut,
    VerifyOnlinePaymentRequest,
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


@router.get("/my", response_model=list[BookingListItemOut])
async def my_bookings(db: AsyncSession = Depends(get_db), user: User = Depends(require_patient)):
    rows = await service.list_bookings_for_patient_with_details(db, user.id)
    out = []
    for row in rows:
        item = BookingListItemOut.model_validate(row["booking"])
        item.doctor_name = row["doctor_name"]
        item.facility_name = row["facility_name"]
        item.facility_address = row["facility_address"]
        item.facility_photo_url = row["facility_photo_url"]
        out.append(item)
    return out


@router.get("/facility/{facility_id}", response_model=list[FacilityBookingListItemOut])
async def facility_bookings(
    facility_id: uuid.UUID,
    status: BookingStatus | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_merchant),
):
    """Booking history for one of the merchant's own facilities — powers
    the Partner App's Booking History screen. Optional `status` query param
    filters to a single status (e.g. ?status=completed); omitted returns
    all bookings for the facility, most recent first."""
    await verify_facility_owner(db, facility_id, user.id)
    rows = await service.list_bookings_for_facility_with_details(db, facility_id, status)
    out = []
    for row in rows:
        item = FacilityBookingListItemOut.model_validate(row["booking"])
        item.doctor_name = row["doctor_name"]
        out.append(item)
    return out


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


@router.get("/{booking_id}/receipt", response_model=BookingWithQrOut)
async def get_booking_receipt(
    booking_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """Full booking details + a freshly regenerated QR — for a printable
    receipt/invoice view. Same ownership rule as GET /bookings/{id}: the
    patient who made it, an admin, or the owning facility's merchant."""
    booking = await service.get_booking(db, booking_id)
    if not (
        booking.patient_id == user.id
        or user.role in (UserRole.ADMIN, UserRole.SUPERADMIN)
        or (user.role == UserRole.MERCHANT and (await get_facility(db, booking.facility_id)).owner_user_id == user.id)
    ):
        raise ForbiddenError("Not your booking")

    booking, qr_base64, doctor_name, facility_name, facility_address = await service.get_booking_receipt(db, booking_id)
    out = BookingWithQrOut.model_validate(booking)
    out.qr_code_base64 = qr_base64
    out.doctor_name = doctor_name
    out.facility_name = facility_name
    out.facility_address = facility_address
    return out


@router.get("/{booking_id}/queue-status", response_model=QueueStatusOut)
async def get_queue_status(
    booking_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """Live snapshot for the 'live status' screen: current token being
    seen, how many are ahead of this booking, and an estimated wait.
    Meant to be polled by the app while a booking is upcoming."""
    booking = await service.get_booking(db, booking_id)
    if not (
        booking.patient_id == user.id
        or user.role in (UserRole.ADMIN, UserRole.SUPERADMIN)
        or (user.role == UserRole.MERCHANT and (await get_facility(db, booking.facility_id)).owner_user_id == user.id)
    ):
        raise ForbiddenError("Not your booking")
    return await service.get_queue_status(db, booking_id)


@router.post("/{booking_id}/verify-payment", response_model=BookingOut)
async def verify_online_payment(
    booking_id: uuid.UUID,
    payload: VerifyOnlinePaymentRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Called after the gateway redirect/callback to verify an online
    payment and settle the facility's share. Safe to call more than once —
    already-settled bookings are returned unchanged (see
    `service.confirm_online_payment`)."""
    booking = await service.get_booking(db, booking_id)
    if not (booking.patient_id == user.id or user.role in (UserRole.ADMIN, UserRole.SUPERADMIN)):
        raise ForbiddenError("Not your booking")
    return await service.confirm_online_payment(db, booking, payload.gateway_response)


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
        booking_code=booking.booking_code,
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
        booking_code=booking.booking_code,
        status=booking.status,
        refund_reward_points=refund_points,
        deduction_percent_applied=deduction,
    )