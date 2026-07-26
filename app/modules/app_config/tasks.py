"""
Celery task for admin "custom notification" broadcasts. Kept off the request
path (same reasoning as notifications/tasks.py's email sends) since sending
push to every user with a device token can be thousands of calls — the admin
gets an immediate "queued" response and the broadcast record is filled in
with real counts once the fan-out finishes.
"""
import asyncio
import logging
import uuid

from sqlalchemy import select

from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.modules.app_config.models import NotificationBroadcast
from app.modules.auth.models import User
from app.modules.notifications.models import NotificationType
from app.modules.notifications.service import create_notification
from app.services.notification_service import notification_service

logger = logging.getLogger("app_config.tasks")


async def _send_broadcast(broadcast_id: str, title: str, body: str) -> dict:
    recipients = 0
    push_ok = 0
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.is_active == True))  # noqa: E712
        users = result.scalars().all()

        for user in users:
            recipients += 1
            if user.device_push_token:
                sent = await notification_service.send_push(
                    device_token=user.device_push_token, title=title, body=body,
                )
                if sent:
                    push_ok += 1
            await create_notification(
                db, user.id, title=title, body=body, notification_type=NotificationType.PROMO,
            )

        broadcast_result = await db.execute(
            select(NotificationBroadcast).where(NotificationBroadcast.id == uuid.UUID(broadcast_id))
        )
        broadcast = broadcast_result.scalar_one_or_none()
        if broadcast:
            broadcast.recipients_count = recipients
            broadcast.push_success_count = push_ok
            await db.commit()

    logger.info("broadcast %s sent: recipients=%s push_ok=%s", broadcast_id, recipients, push_ok)
    return {"recipients": recipients, "push_ok": push_ok}


@celery_app.task(name="app.modules.app_config.tasks.send_broadcast")
def send_broadcast(broadcast_id: str, title: str, body: str) -> dict:
    return asyncio.run(_send_broadcast(broadcast_id, title, body))
