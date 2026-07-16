"""
Notification Service abstraction — push notifications + realtime queue
updates. Business logic calls `notification_service.send_push(...)` /
`notification_service.push_queue_update(...)` only. Firebase is the current
implementation; if it's ever swapped (e.g. OneSignal), only this file changes.
"""
import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from app.core.config import settings

logger = logging.getLogger("notification_service")


class NotificationService(ABC):
    @abstractmethod
    async def send_push(self, device_token: str, title: str, body: str, data: dict | None = None) -> bool:
        ...

    @abstractmethod
    async def push_queue_update(self, facility_id: str, doctor_id: str, payload: dict[str, Any]) -> None:
        """Writes the live 'current token' state to a realtime path so the
        User App's live-queue screen updates instantly without polling."""

    @abstractmethod
    async def notify_topic(self, topic: str, title: str, body: str) -> bool:
        ...


class FirebaseNotificationService(NotificationService):
    def __init__(self):
        import firebase_admin
        from firebase_admin import credentials, db

        if not firebase_admin._apps:
            if settings.firebase_credentials_json:
                cred = credentials.Certificate(json.loads(settings.firebase_credentials_json))
            else:
                cred = credentials.ApplicationDefault()
            firebase_admin.initialize_app(
                cred, {"databaseURL": settings.firebase_database_url}
            )
        self._db = db

    async def send_push(self, device_token: str, title: str, body: str, data: dict | None = None) -> bool:
        from firebase_admin import messaging

        message = messaging.Message(
            token=device_token,
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items()},
        )
        try:
            messaging.send(message)
            return True
        except Exception:
            logger.exception("push notification failed")
            return False

    async def push_queue_update(self, facility_id: str, doctor_id: str, payload: dict[str, Any]) -> None:
        ref = self._db.reference(f"live_queue/{facility_id}/{doctor_id}")
        ref.set(payload)

    async def notify_topic(self, topic: str, title: str, body: str) -> bool:
        from firebase_admin import messaging

        message = messaging.Message(
            topic=topic, notification=messaging.Notification(title=title, body=body)
        )
        try:
            messaging.send(message)
            return True
        except Exception:
            logger.exception("topic notification failed")
            return False


class NoopNotificationService(NotificationService):
    """Used when Firebase credentials aren't configured yet (local dev) so
    the app still boots and booking/queue flows can be tested end-to-end."""

    async def send_push(self, device_token: str, title: str, body: str, data: dict | None = None) -> bool:
        logger.info("NOOP push -> %s: %s / %s / %s", device_token, title, body, data)
        return True

    async def push_queue_update(self, facility_id: str, doctor_id: str, payload: dict[str, Any]) -> None:
        logger.info("NOOP queue update -> facility=%s doctor=%s payload=%s", facility_id, doctor_id, payload)

    async def notify_topic(self, topic: str, title: str, body: str) -> bool:
        logger.info("NOOP topic push -> %s: %s / %s", topic, title, body)
        return True


def get_notification_service() -> NotificationService:
    if settings.firebase_credentials_json and settings.firebase_database_url:
        try:
            return FirebaseNotificationService()
        except Exception:
            logger.exception("Firebase init failed, falling back to Noop")
    return NoopNotificationService()


notification_service = get_notification_service()
