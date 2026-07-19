import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.mixins import TimestampMixin, UUIDPKMixin
from app.core.database import Base


class NotificationType(str, enum.Enum):
    BOOKING = "booking"
    QUEUE = "queue"
    REWARD = "reward"
    PROMO = "promo"
    SYSTEM = "system"


class Notification(Base, UUIDPKMixin, TimestampMixin):
    """Persisted, in-app notification feed — separate from the fire-and-forget
    Firebase push in notification_service.py. Push gets a message onto the
    phone right now; this is what powers a "Notifications" screen the user
    can open later and a reliable unread-count badge, which a push
    notification alone can't give you (it doesn't survive app reinstall,
    a new device, or the user simply swiping it away unread)."""

    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    notification_type: Mapped[NotificationType] = mapped_column(Enum(NotificationType), default=NotificationType.SYSTEM)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(String(1000))
    related_booking_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
