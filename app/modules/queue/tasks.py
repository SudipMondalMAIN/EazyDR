"""
Celery beat task wiring for GET /api/v1/queue/stalled's underlying logic.
The endpoint stays as-is for on-demand polling from the admin dashboard;
this task is what actually drives the staff push reminder -> admin
escalation flow automatically every 15 minutes, per spec section 5:

  1. Queue hasn't advanced in QUEUE_STALL_MINUTES and hasn't been notified
     yet -> push a reminder to the facility's staff device.
  2. Queue is still stalled next sweep after being notified -> escalate to
     the Admin dashboard alert feed (escalated_to_admin=True), which is
     what GET /api/v1/queue/stalled surfaces.

Celery tasks are sync; the app is async end-to-end, so each task run opens
its own asyncio event loop for the duration of the DB work.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.modules.queue import service
from app.services.notification_service import notification_service

logger = logging.getLogger("queue.tasks")


async def _sweep_stalled_queues() -> dict:
    notified, escalated = 0, 0
    async with AsyncSessionLocal() as db:
        stalled_states = await service.find_stalled_queues(db)
        for state in stalled_states:
            already_notified = state.stall_notified_at is not None
            cutoff_for_escalation = datetime.now(timezone.utc) - timedelta(
                minutes=settings.queue_stall_minutes
            )

            if not already_notified:
                await notification_service.notify_topic(
                    topic=f"facility_staff_{state.doctor_id}",
                    title="Queue stalled",
                    body=f"Queue for doctor {state.doctor_id} hasn't advanced in "
                    f"{settings.queue_stall_minutes}+ minutes. Please check in the next patient.",
                )
                await service.mark_stall_notified(db, state)
                notified += 1
            elif state.stall_notified_at < cutoff_for_escalation:
                # Already nudged staff once and it's still stuck -> escalate.
                await service.escalate_to_admin(db, state)
                escalated += 1

    logger.info("stalled-queue sweep: notified=%s escalated=%s", notified, escalated)
    return {"notified": notified, "escalated": escalated}


@celery_app.task(name="app.modules.queue.tasks.sweep_stalled_queues")
def sweep_stalled_queues() -> dict:
    return asyncio.run(_sweep_stalled_queues())
