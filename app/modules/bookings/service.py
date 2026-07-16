import base64
import hashlib
import hmac
import io
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import qrcode
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.config import settings
from app.modules.bookings.models import Booking, BookingStatus, PaymentMode
from app.modules.bookings.schemas import BookingCreate
from app.modules.facilities.service import get_doctor, get_facility
from app.modules.rewards.service import credit_facility_earning, credit_reward_points
from app.services.payment_service import payment_service


def _sign_qr(qr_uuid: uuid.UUID) -> str:
    """HMAC signature over the booking's QR UUID using the app's JWT secret
    as key material, so a scanned QR can be verified as platform-issued
    without a DB round trip before the real lookup."""
    return hmac.new(settings.jwt_secret.encode(), str(qr_uuid).encode(), hashlib.sha256).hexdigest()


def _generate_qr_base64(qr_uuid: uuid.UUID, signature: str) -> str:
    payload = f"eazydoctor://checkin?uuid={qr_uuid}&sig={signature}"
    img = qrcode.make(payload)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


async def _next_token_number(db: AsyncSession, doctor_id: uuid.UUID, appointment_date: str) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(Booking.token_number), 0)).where(
            Booking.doctor_id == doctor_id,
            Booking.appointment_date == appointment_date,
            Booking.status != BookingStatus.CANCELLED,
        )
    )
    return int(result.scalar_one()) + 1


async def create_booking(db: AsyncSession, patient_id: uuid.UUID, payload: BookingCreate) -> tuple[Booking, str]:
    facility = await get_facility(db, payload.facility_id)
    doctor = await get_doctor(db, payload.doctor_id)
    if doctor.facility_id != facility.id:
        raise BadRequestError("Doctor does not belong to this facility")

    booking_fee = facility.booking_fee or settings.default_booking_fee
    commission_percent = facility.commission_percent_override or settings.default_platform_commission_percent
    commission_amount = round(booking_fee * commission_percent / 100, 2)
    facility_amount = round(booking_fee - commission_amount, 2)

    qr_uuid = uuid.uuid4()
    signature = _sign_qr(qr_uuid)

    if payload.payment_mode == PaymentMode.CASH:
        payment_result = await payment_service.initiate_cash_payment(str(qr_uuid), booking_fee)
        status = BookingStatus.CONFIRMED
    else:
        payment_result = await payment_service.initiate_online_payment(str(qr_uuid), booking_fee, str(patient_id))
        if payment_result.status == "failed":
            raise BadRequestError(
                "Online payment is not available yet (gateway approval pending) — please choose Pay Cash at checkout"
            )
        status = BookingStatus.PENDING  # flips to CONFIRMED once payment callback verifies

    # Token numbers are assigned by MAX(token_number)+1, which is not safe
    # under concurrency on its own — two requests can read the same MAX and
    # both try to insert the same next token. The DB-level unique constraint
    # on (doctor_id, appointment_date, token_number) is the real guard; if
    # it fires we recompute the next token and retry the insert a few times
    # rather than surfacing a spurious failure to the patient. We do NOT
    # redo payment initiation on retry — that already succeeded/was
    # recorded above and must not be repeated per attempt.
    max_attempts = 5
    booking: Booking | None = None
    for attempt in range(max_attempts):
        token_number = await _next_token_number(db, doctor.id, payload.appointment_date)
        booking = Booking(
            patient_id=patient_id,
            facility_id=facility.id,
            doctor_id=doctor.id,
            patient_name=payload.patient_name,
            patient_phone=payload.patient_phone,
            patient_address=payload.patient_address,
            token_number=token_number,
            appointment_date=payload.appointment_date,
            expected_time=payload.expected_time,
            booking_fee=booking_fee,
            platform_commission_amount=commission_amount,
            facility_earning_amount=facility_amount,
            payment_mode=payload.payment_mode,
            payment_transaction_ref=payment_result.transaction_ref,
            status=status,
            qr_uuid=qr_uuid,
            qr_signature=signature,
        )
        db.add(booking)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            if attempt == max_attempts - 1:
                raise ConflictError(
                    "Could not assign a queue token — please try booking again"
                )
            continue
        else:
            await db.refresh(booking)
            break

    # Credit facility earnings immediately for cash (settlement of the
    # platform's cut with the facility is handled out-of-band per spec
    # section 4). For online payments this should happen in the payment
    # webhook/callback handler once verified — not here.
    if payload.payment_mode == PaymentMode.CASH:
        await credit_facility_earning(
            db, facility.id, facility_amount, booking.id, "Cash booking — facility share"
        )

    qr_base64 = _generate_qr_base64(qr_uuid, signature)
    return booking, qr_base64


async def get_booking(db: AsyncSession, booking_id: uuid.UUID) -> Booking:
    result = await db.execute(select(Booking).where(Booking.id == booking_id))
    booking = result.scalar_one_or_none()
    if not booking:
        raise NotFoundError("Booking not found")
    return booking


async def get_booking_by_qr(db: AsyncSession, qr_uuid: uuid.UUID, signature: str) -> Booking:
    result = await db.execute(select(Booking).where(Booking.qr_uuid == qr_uuid))
    booking = result.scalar_one_or_none()
    if not booking:
        raise NotFoundError("Invalid QR — booking not found")
    if not hmac.compare_digest(booking.qr_signature, signature):
        raise BadRequestError("QR signature verification failed — possibly tampered")
    return booking


async def list_bookings_for_patient(db: AsyncSession, patient_id: uuid.UUID) -> list[Booking]:
    result = await db.execute(
        select(Booking).where(Booking.patient_id == patient_id).order_by(Booking.created_at.desc())
    )
    return list(result.scalars().all())


_APP_TZ = ZoneInfo(settings.app_timezone)


def _appointment_datetime(booking: Booking) -> datetime:
    """Appointment date/time are stored as naive local wall-clock values
    (e.g. "14:30" as told to the patient at a Bolpur facility) — i.e. IST,
    not UTC. Interpret them in the configured app timezone and convert to
    an aware UTC datetime so comparisons against datetime.now(timezone.utc)
    are correct. Getting this wrong shifts the cancellation lock window by
    the full UTC offset (5.5 hours for IST)."""
    naive_local = datetime.strptime(
        f"{booking.appointment_date} {booking.expected_time}", "%Y-%m-%d %H:%M"
    )
    return naive_local.replace(tzinfo=_APP_TZ).astimezone(timezone.utc)


async def cancel_booking(
    db: AsyncSession, booking: Booking, facility_fault: bool = False
) -> tuple[Booking, int, float]:
    """Cancels a booking. Returns (booking, refund_points, deduction_percent_applied).

    - Blocked within CANCELLATION_LOCK_HOURS of appointment time, UNLESS
      facility_fault=True (used by the queue-delay grace-refund fallback,
      which is allowed to bypass the lock since the delay isn't the
      patient's doing — see spec section 5)."""
    if booking.status in (BookingStatus.CANCELLED, BookingStatus.COMPLETED, BookingStatus.CHECKED_IN):
        raise ConflictError(f"Booking cannot be cancelled from status '{booking.status.value}'")

    now = datetime.now(timezone.utc)
    appointment_dt = _appointment_datetime(booking)
    hours_until = (appointment_dt - now).total_seconds() / 3600

    if not facility_fault and hours_until < settings.cancellation_lock_hours:
        raise BadRequestError(
            f"Cancellation is locked within {settings.cancellation_lock_hours} hours of the appointment"
        )

    facility = await get_facility(db, booking.facility_id)
    deduction_percent = 0.0 if facility_fault else (
        facility.cancellation_deduction_percent_override
        if facility.cancellation_deduction_percent_override is not None
        else settings.default_cancellation_deduction_percent
    )

    refund_amount = booking.booking_fee * (1 - deduction_percent / 100)
    # Reward points are issued 1:1 with rupees for simplicity; make this a
    # configurable conversion rate in Admin settings if the business wants
    # a different ratio later.
    refund_points = round(refund_amount)

    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = now
    booking.cancellation_refund_points = refund_points
    await db.commit()
    await db.refresh(booking)

    if refund_points > 0:
        note = "Facility-fault grace refund (queue delay)" if facility_fault else "Cancellation refund"
        await credit_reward_points(db, booking.patient_id, refund_points, booking.id, note)

    return booking, refund_points, deduction_percent
