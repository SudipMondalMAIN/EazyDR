"""
Celery beat task: push a reminder ~30 minutes before a confirmed booking's
expected_time. Runs every 5 minutes (see celery_app.py beat schedule) and
looks at a +/-5-minute window around the 30-minute mark, so every booking
gets caught by exactly one run without needing second-level precision.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.modules.auth.models import User
from app.modules.bookings.models import Booking, BookingStatus
from app.modules.notifications.models import NotificationType
from app.modules.notifications.service import create_notification
from app.services.email_service import send_notification_email
from app.services.notification_service import notification_service

logger = logging.getLogger("notifications.tasks")

REMINDER_WINDOW_MINUTES = 30
REMINDER_TOLERANCE_MINUTES = 5  # half the 5-min beat interval either side


@celery_app.task(
    bind=True,
    name="app.modules.notifications.tasks.send_transactional_email",
    max_retries=5,
)
def send_transactional_email(self, to_email: str, subject: str, message: str) -> bool:
    """Sends a transactional email (booking confirmation/cancellation,
    appointment reminder, etc.) with retries and failure logging.

    Retries with exponential backoff on any failure (provider error or
    exception). After the final attempt is exhausted, the failure is
    logged so it can be investigated, rather than silently dropped.
    """
    try:
        sent = asyncio.run(send_notification_email(to_email, subject, message))
        if not sent:
            raise RuntimeError("email provider reported failure")
        return True
    except Exception as exc:  # noqa: BLE001
        attempt = self.request.retries + 1
        total_attempts = self.max_retries + 1
        if self.request.retries >= self.max_retries:
            logger.error(
                "email permanently failed after %s attempts to=%s subject=%s error=%s",
                total_attempts, to_email, subject, exc,
            )
            return False
        logger.warning(
            "email send attempt %s/%s failed to=%s subject=%s error=%s — retrying",
            attempt, total_attempts, to_email, subject, exc,
        )
        raise self.retry(exc=exc, countdown=min(60 * (2 ** self.request.retries), 900))


async def _send_appointment_reminders() -> dict:
    now_ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    window_start = now_ist + timedelta(minutes=REMINDER_WINDOW_MINUTES - REMINDER_TOLERANCE_MINUTES)
    window_end = now_ist + timedelta(minutes=REMINDER_WINDOW_MINUTES + REMINDER_TOLERANCE_MINUTES)

    sent = 0
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Booking).where(
                Booking.status == BookingStatus.CONFIRMED,
                Booking.reminder_sent == False,  # noqa: E712
                Booking.appointment_date == now_ist.strftime("%Y-%m-%d"),
            )
        )
        candidates = result.scalars().all()

        for booking in candidates:
            try:
                expected_dt = datetime.strptime(
                    f"{booking.appointment_date} {booking.expected_time}", "%Y-%m-%d %H:%M"
                ).replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
            except ValueError:
                continue

            if not (window_start <= expected_dt <= window_end):
                continue

            user_result = await db.execute(select(User).where(User.id == booking.patient_id))
            patient = user_result.scalar_one_or_none()

            reminder_body = (
                f"Your appointment (token #{booking.token_number}) is at "
                f"{booking.expected_time} today. See you soon!"
            )
            if patient and patient.device_push_token:
                await notification_service.send_push(
                    device_token=patient.device_push_token,
                    title="Upcoming appointment",
                    body=reminder_body,
                    data={"booking_id": str(booking.id)},
                )
            if patient and patient.email:
                send_transactional_email.delay(
                    patient.email, "Your appointment is in 30 minutes", reminder_body
                )
            if patient:
                await create_notification(
                    db,
                    patient.id,
                    title="Upcoming appointment",
                    body=reminder_body,
                    notification_type=NotificationType.QUEUE,
                    related_booking_id=booking.id,
                )

            booking.reminder_sent = True
            sent += 1

        await db.commit()

    logger.info("appointment reminder sweep: sent=%s", sent)
    return {"sent": sent}


@celery_app.task(name="app.modules.notifications.tasks.send_appointment_reminders")
def send_appointment_reminders() -> dict:
    return asyncio.run(_send_appointment_reminders())
