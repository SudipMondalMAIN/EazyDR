"""
Celery app instance. Redis doubles as broker + result backend (same
REDIS_URL already used for caching/rate-limiting — one less moving part at
this scale; move to a dedicated broker later if task volume grows).

Run locally with:
    celery -A app.core.celery_app worker --loglevel=info
    celery -A app.core.celery_app beat --loglevel=info

(two separate processes — worker executes tasks, beat schedules them; see
docker-compose.yml for both wired up as services)
"""
from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "eazydoctor",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.modules.queue.tasks",
        "app.modules.notifications.tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Kolkata",
    enable_utc=True,
    # Belt-and-braces: if a worker dies mid-task, redeliver rather than
    # silently drop it (these are booking/queue-affecting tasks).
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

celery_app.conf.beat_schedule = {
    "sweep-stalled-queues": {
        "task": "app.modules.queue.tasks.sweep_stalled_queues",
        "schedule": crontab(minute="*/15"),
    },
    "send-appointment-reminders": {
        # Runs every 5 min and looks for bookings ~30 min out, rather than
        # running every 30 min, so a booking due in e.g. 27 minutes still
        # gets caught inside the window instead of being missed entirely.
        "task": "app.modules.notifications.tasks.send_appointment_reminders",
        "schedule": crontab(minute="*/5"),
    },
}
