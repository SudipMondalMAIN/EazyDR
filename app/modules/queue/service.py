import hmac
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestError, NotFoundError
from app.core.config import settings
from app.modules.bookings.models import Booking, BookingStatus
from app.modules.bookings.service import get_booking_by_qr
from app.modules.facilities.service import verify_doctor_owner
from app.modules.queue.models import QueueState
from app.services.notification_service import notification_service


async def _get_or_create_queue_state(db: AsyncSession, doctor_id: uuid.UUID, queue_date: str) -> QueueState:
    result = await db.execute(
        select(QueueState).where(QueueState.doctor_id == doctor_id, QueueState.queue_date == queue_date)
    )
    state = result.scalar_one_or_none()
    if not state:
        state = QueueState(doctor_id=doctor_id, queue_date=queue_date)
        db.add(state)
        await db.commit()
        await db.refresh(state)
    return state


async def _advance_queue(db: AsyncSession, booking: Booking) -> QueueState:
    """Marks the booking as checked-in/with-doctor and advances the queue.
    Per spec: there's no separate 'complete' action — scanning the NEXT
    patient's QR is what implicitly completes the previous one, hence we
    just mark any prior CHECKED_IN booking (same doctor+date, lower token)
    as COMPLETED here."""
    now = datetime.now(timezone.utc)

    prior = await db.execute(
        select(Booking).where(
            Booking.doctor_id == booking.doctor_id,
            Booking.appointment_date == booking.appointment_date,
            Booking.status == BookingStatus.CHECKED_IN,
            Booking.token_number < booking.token_number,
        )
    )
    for prior_booking in prior.scalars().all():
        prior_booking.status = BookingStatus.COMPLETED

    booking.status = BookingStatus.CHECKED_IN
    booking.checked_in_at = now
    await db.commit()
    await db.refresh(booking)

    state = await _get_or_create_queue_state(db, booking.doctor_id, booking.appointment_date)
    state.current_token = booking.token_number
    state.last_advanced_at = now
    state.stall_notified_at = None
    state.escalated_to_admin = False
    await db.commit()
    await db.refresh(state)

    await notification_service.push_queue_update(
        str(booking.facility_id),
        str(booking.doctor_id),
        {
            "current_token": state.current_token,
            "updated_at": now.isoformat(),
            "booking_id": str(booking.id),
        },
    )
    return state


async def check_in_by_qr(
    db: AsyncSession, qr_uuid: uuid.UUID, signature: str, merchant_user_id: uuid.UUID
) -> Booking:
    booking = await get_booking_by_qr(db, qr_uuid, signature)
    # Ownership check must happen after we know which doctor/facility this
    # booking belongs to, and before any status mutation — a merchant must
    # only ever be able to check in patients at a facility they own.
    await verify_doctor_owner(db, booking.doctor_id, merchant_user_id)
    if booking.status == BookingStatus.CANCELLED:
        raise BadRequestError("This booking was cancelled")
    if booking.status in (BookingStatus.CHECKED_IN, BookingStatus.COMPLETED):
        raise BadRequestError("This QR has already been used for check-in")
    await _advance_queue(db, booking)
    return booking


async def check_in_manual(
    db: AsyncSession,
    doctor_id: uuid.UUID,
    appointment_date: str,
    booking_id: uuid.UUID | None,
    patient_phone: str | None,
    merchant_user_id: uuid.UUID,
) -> Booking:
    """Fallback for walk-ins without a visible/scannable QR — verify by
    Booking ID or phone number instead."""
    await verify_doctor_owner(db, doctor_id, merchant_user_id)
    if not booking_id and not patient_phone:
        raise BadRequestError("Provide either booking_id or patient_phone")

    stmt = select(Booking).where(
        Booking.doctor_id == doctor_id, Booking.appointment_date == appointment_date
    )
    if booking_id:
        stmt = stmt.where(Booking.id == booking_id)
    else:
        stmt = stmt.where(Booking.patient_phone == patient_phone, Booking.status == BookingStatus.CONFIRMED)

    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()
    if not booking:
        raise NotFoundError("No matching confirmed booking found")
    if booking.status in (BookingStatus.CHECKED_IN, BookingStatus.COMPLETED):
        raise BadRequestError("This booking has already been checked in")

    await _advance_queue(db, booking)
    return booking


async def get_live_queue(db: AsyncSession, doctor_id: uuid.UUID, queue_date: str) -> tuple[int, bool]:
    state = await _get_or_create_queue_state(db, doctor_id, queue_date)
    is_stalled = False
    if state.last_advanced_at:
        elapsed = datetime.now(timezone.utc) - state.last_advanced_at
        is_stalled = elapsed > timedelta(minutes=settings.queue_stall_minutes)
    return state.current_token, is_stalled


async def find_stalled_queues(db: AsyncSession) -> list[QueueState]:
    """Meant to be called from a periodic background worker (Celery beat).
    Returns queues that haven't advanced in QUEUE_STALL_MINUTES and haven't
    already been notified — used to fire the staff push reminder, then
    (if still unaddressed) escalate to the Admin dashboard alert + call
    trigger per spec section 5."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.queue_stall_minutes)
    result = await db.execute(
        select(QueueState).where(
            QueueState.last_advanced_at.is_not(None),
            QueueState.last_advanced_at < cutoff,
            QueueState.escalated_to_admin == False,  # noqa: E712
        )
    )
    return list(result.scalars().all())


async def mark_stall_notified(db: AsyncSession, state: QueueState) -> None:
    state.stall_notified_at = datetime.now(timezone.utc)
    await db.commit()


async def escalate_to_admin(db: AsyncSession, state: QueueState) -> None:
    state.escalated_to_admin = True
    await db.commit()
