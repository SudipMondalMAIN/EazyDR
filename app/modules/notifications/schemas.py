import uuid

from pydantic import BaseModel

from app.modules.notifications.models import NotificationType


class NotificationOut(BaseModel):
    id: uuid.UUID
    notification_type: NotificationType
    title: str
    body: str
    related_booking_id: uuid.UUID | None
    is_read: bool

    class Config:
        from_attributes = True


class UnreadCountOut(BaseModel):
    unread_count: int
