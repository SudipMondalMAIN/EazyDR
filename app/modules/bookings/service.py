import base64
import hashlib
import hmac
import io
import logging
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import qrcode
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.config import settings
from app.modules.auth.models import User
from app.modules.bookings.models import Booking, BookingStatus, PaymentMode
from app.modules.bookings.schemas import BookingCreate
from app.modules.facilities.models import Doctor, Facility
from app.modules.facilities.service import get_doctor, get_facility, list_availability
from app.services.storage_service import storage_service
from app.modules.notifications.models import NotificationType
from app.modules.notifications.service import create_notification
from app.modules.notifications.tasks import send_transactional_email
from app.modules.rewards.service import credit_facility_earning, credit_reward_points
from app.services.notification_service import notification_service
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


# Used when a doctor has no matching availability row for the requested day —
# should be rare in practice since facilities are expected to keep a weekly
# schedule set, but a booking must never hard-fail just because of a gap in it.
_FALLBACK_START_TIME = "10:00"


async def _compute_expected_time(
    db: AsyncSession, doctor_id: uuid.UUID, appointment_date: str, token_number: int
) -> str:
    """Derives the patient's expected slot time from the doctor's weekly
    availability + their position in today's queue (token_number), instead of
    letting the patient pick a time themselves. This keeps a single source of
    truth (the queue) for how the day's tokens map to clock time.

    day_of_week: 0=Monday ... 6=Sunday (matches DoctorAvailability), derived
    from the appointment_date's actual weekday.
    """
    weekday = datetime.strptime(appointment_date, "%Y-%m-%d").weekday()
    slots = await list_availability(db, doctor_id)

    on_leave = any(
        s.leave_date == appointment_date and s.is_leave for s in slots
    )
    if on_leave:
        raise BadRequestError("This doctor is on leave on the selected date")

    matching = [s for s in slots if not s.is_leave and s.day_of_week == weekday]
    if not matching:
        logging.getLogger("bookings.service").warning(
            "no availability slot for doctor=%s weekday=%s — falling back to default start time",
            doctor_id, weekday,
        )
        start_time, slot_duration = _FALLBACK_START_TIME, 15
    else:
        slot = matching[0]
        start_time, slot_duration = slot.start_time, slot.slot_duration_minutes

    start_dt = datetime.strptime(start_time, "%H:%M")
    expected_dt = start_dt + timedelta(minutes=slot_duration * (token_number - 1))
    return expected_dt.strftime("%H:%M")


async def create_booking(db: AsyncSession, patient_id: uuid.UUID, payload: BookingCreate) -> tuple[Booking, str]:
    facility = await get_facility(db, payload.facility_id)
    if not facility.is_active or not facility.is_verified:
        raise BadRequestError("This facility is not currently accepting bookings")
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
        expected_time = await _compute_expected_time(
            db, doctor.id, payload.appointment_date, token_number
        )
        booking = Booking(
            patient_id=patient_id,
            facility_id=facility.id,
            doctor_id=doctor.id,
            patient_name=payload.patient_name,
            patient_phone=payload.patient_phone,
            patient_address=payload.patient_address,
            token_number=token_number,
            appointment_date=payload.appointment_date,
            expected_time=expected_time,
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

    # Best-effort — an in-app notification failing must never fail the
    # booking itself, so exceptions here are logged and swallowed.
    try:
        booking_title = "Booking confirmed" if status == BookingStatus.CONFIRMED else "Booking received"
        booking_body = (
            f"Token #{token_number} at {doctor.full_name} on {payload.appointment_date}, "
            f"{expected_time}."
        )
        await create_notification(
            db,
            patient_id,
            title=booking_title,
            body=booking_body,
            notification_type=NotificationType.BOOKING,
            related_booking_id=booking.id,
        )
        await create_notification(
            db,
            facility.owner_user_id,
            title="New booking",
            body=f"{payload.patient_name} booked token #{token_number} with {doctor.full_name} "
            f"for {payload.appointment_date}.",
            notification_type=NotificationType.BOOKING,
            related_booking_id=booking.id,
        )
        patient_result = await db.execute(select(User).where(User.id == patient_id))
        patient = patient_result.scalar_one_or_none()
        if patient and patient.device_push_token:
            await notification_service.send_push(
                device_token=patient.device_push_token,
                title=booking_title,
                body=booking_body,
                data={"booking_id": str(booking.id)},
            )
        if patient and patient.email:
            send_transactional_email.delay(patient.email, booking_title, booking_body)
    except Exception:  # noqa: BLE001
        logging.getLogger("bookings.service").exception("failed to create in-app notification for booking")

    qr_base64 = _generate_qr_base64(qr_uuid, signature)
    return booking, qr_base64


async def confirm_online_payment(db: AsyncSession, booking: Booking, gateway_response: dict) -> Booking:
    """Verify an online (gateway) payment for a booking and settle it.

    This is the online counterpart to the immediate cash-credit path in
    `create_booking`: it must move the booking to CONFIRMED and credit the
    facility's share to their earnings ledger, but ONLY once. Cash and
    online transactions are kept on separate settlement flags
    (`cash_commission_settled` vs `online_payment_settled`) and separate
    ledger notes so the two payment paths never get mixed together in the
    facility's earnings history or double-counted against each other.
    """
    if booking.payment_mode != PaymentMode.ONLINE:
        raise BadRequestError("This booking was not paid online")

    # Idempotency guard: prevent duplicate settlement if the gateway
    # callback fires more than once, or verification is retried.
    if booking.online_payment_settled:
        return booking

    if not booking.payment_transaction_ref:
        raise BadRequestError("Booking has no payment transaction reference")

    result = await payment_service.verify_payment(booking.payment_transaction_ref, gateway_response)
    if not result.success:
        raise BadRequestError("Online payment verification failed")

    booking.online_payment_settled = True
    if booking.status == BookingStatus.PENDING:
        booking.status = BookingStatus.CONFIRMED

    await credit_facility_earning(
        db, booking.facility_id, booking.facility_earning_amount, booking.id, "Online booking — facility share"
    )

    await db.commit()
    await db.refresh(booking)
    return booking


async def get_booking(db: AsyncSession, booking_id: uuid.UUID) -> Booking:
    result = await db.execute(select(Booking).where(Booking.id == booking_id))
    booking = result.scalar_one_or_none()
    if not booking:
        raise NotFoundError("Booking not found")
    return booking


async def get_booking_receipt(db: AsyncSession, booking_id: uuid.UUID) -> tuple[Booking, str, str, str, str]:
    """Re-derives the same QR PNG shown at booking time (deterministic from
    the stored qr_uuid + qr_signature) so a receipt/invoice view can be
    reopened or reprinted any time, not just right after booking. Also pulls
    doctor/facility display names so the receipt doesn't need extra calls."""
    booking = await get_booking(db, booking_id)
    qr_base64 = _generate_qr_base64(booking.qr_uuid, booking.qr_signature)
    doctor = await get_doctor(db, booking.doctor_id)
    facility = await get_facility(db, booking.facility_id)
    return booking, qr_base64, doctor.full_name, facility.name, facility.address


async def get_queue_status(db: AsyncSession, booking_id: uuid.UUID) -> dict:
    """Live queue snapshot for a single booking: which token is currently
    being seen, how many checked-in patients are still ahead of this one,
    and a rough wait estimate from the doctor's slot duration. Recomputed
    fresh on every call — there's no cached/pushed state, the app polls."""
    booking = await get_booking(db, booking_id)
    doctor = await get_doctor(db, booking.doctor_id)
    facility = await get_facility(db, booking.facility_id)

    result = await db.execute(
        select(Booking).where(
            Booking.doctor_id == booking.doctor_id,
            Booking.appointment_date == booking.appointment_date,
            Booking.status.in_([BookingStatus.CHECKED_IN, BookingStatus.IN_PROGRESS]),
        )
    )
    same_day_active = list(result.scalars().all())

    in_progress = [b for b in same_day_active if b.status == BookingStatus.IN_PROGRESS]
    current_token = in_progress[0].token_number if in_progress else None

    patients_ahead = len([
        b for b in same_day_active
        if b.status == BookingStatus.CHECKED_IN and b.token_number < booking.token_number
    ])

    # Estimate wait using the doctor's configured slot length for that
    # weekday (same source of truth as _compute_expected_time), default 15m
    # if no matching slot is on file.
    weekday = datetime.strptime(booking.appointment_date, "%Y-%m-%d").weekday()
    slots = await list_availability(db, booking.doctor_id)
    matching = [s for s in slots if not s.is_leave and s.day_of_week == weekday]
    slot_duration = matching[0].slot_duration_minutes if matching else 15

    estimated_wait_minutes = None
    if booking.status in (BookingStatus.CHECKED_IN, BookingStatus.CONFIRMED, BookingStatus.PENDING):
        estimated_wait_minutes = patients_ahead * slot_duration

    return {
        "booking_id": booking.id,
        "doctor_name": doctor.full_name,
        "facility_name": facility.name,
        "appointment_date": booking.appointment_date,
        "your_token": booking.token_number,
        "status": booking.status,
        "current_token": current_token,
        "patients_ahead": patients_ahead,
        "estimated_wait_minutes": estimated_wait_minutes,
        "updated_at": datetime.now(timezone.utc),
    }


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


async def list_bookings_for_patient_with_details(db: AsyncSession, patient_id: uuid.UUID) -> list[dict]:
    """Same bookings as list_bookings_for_patient, but with doctor name,
    facility name/address, and facility photo attached — powers GET
    /bookings/my for the "My Bookings" list. Facility/doctor rows are
    fetched in two bulk queries (not per-booking) to avoid N+1s."""
    bookings = await list_bookings_for_patient(db, patient_id)
    if not bookings:
        return []

    facility_ids = {b.facility_id for b in bookings}
    doctor_ids = {b.doctor_id for b in bookings}

    fac_result = await db.execute(select(Facility).where(Facility.id.in_(facility_ids)))
    facilities = {f.id: f for f in fac_result.scalars().all()}

    doc_result = await db.execute(select(Doctor).where(Doctor.id.in_(doctor_ids)))
    doctors = {d.id: d for d in doc_result.scalars().all()}

    out = []
    for b in bookings:
        facility = facilities.get(b.facility_id)
        doctor = doctors.get(b.doctor_id)
        photo_url = None
        if facility and facility.photo_storage_key:
            photo_url = storage_service.get_public_url(facility.photo_storage_key)
        out.append({
            "booking": b,
            "doctor_name": doctor.full_name if doctor else "",
            "facility_name": facility.name if facility else "",
            "facility_address": facility.address if facility else "",
            "facility_photo_url": photo_url,
        })
    return out


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
    if booking.status in (
        BookingStatus.CANCELLED,
        BookingStatus.COMPLETED,
        BookingStatus.CHECKED_IN,
        BookingStatus.IN_PROGRESS,
    ):
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

    try:
        cancellation_body = (
            f"Token #{booking.token_number} on {booking.appointment_date} was cancelled."
            + (f" {refund_points} reward points credited." if refund_points > 0 else "")
        )
        await create_notification(
            db,
            booking.patient_id,
            title="Booking cancelled",
            body=cancellation_body,
            notification_type=NotificationType.BOOKING,
            related_booking_id=booking.id,
        )
        patient_result = await db.execute(select(User).where(User.id == booking.patient_id))
        patient = patient_result.scalar_one_or_none()
        if patient and patient.device_push_token:
            await notification_service.send_push(
                device_token=patient.device_push_token,
                title="Booking cancelled",
                body=cancellation_body,
                data={"booking_id": str(booking.id)},
            )
        if patient and patient.email:
            send_transactional_email.delay(patient.email, "Booking cancelled", cancellation_body)
    except Exception:  # noqa: BLE001
        logging.getLogger("bookings.service").exception("failed to create in-app notification for cancellation")

    return booking, refund_points, deduction_percent