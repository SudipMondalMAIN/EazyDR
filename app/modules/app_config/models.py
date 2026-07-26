import uuid

from sqlalchemy import JSON, Boolean, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.mixins import TimestampMixin, UUIDPKMixin
from app.core.database import Base


class AppConfig(Base, UUIDPKMixin, TimestampMixin):
    """Single-row table holding the app's remotely-controlled config.

    Deliberately kept as ONE row (see service.get_config, which always reads
    the oldest row and creates it with defaults if missing) rather than a
    key/value table — the User App fetches this whole row in one request at
    splash, so there's nothing to join or aggregate at read time.
    """

    __tablename__ = "app_config"

    # --- Bottom navigation ---
    # List of {"key": str, "label": str, "icon": str, "order": int,
    # "visible": bool, "screen": str}. Frontend renders tabs from this,
    # sorted by "order", skipping any with visible=False.
    nav_config: Mapped[list] = mapped_column(JSON, default=list)

    # --- Theme ---
    theme_mode: Mapped[str] = mapped_column(String(10), default="light")  # "light" | "dark"
    primary_color: Mapped[str] = mapped_column(String(20), default="#0A84FF")
    secondary_color: Mapped[str] = mapped_column(String(20), default="#34C759")

    # --- Force update / version gate ---
    min_app_version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    force_update: Mapped[bool] = mapped_column(Boolean, default=False)
    update_message: Mapped[str] = mapped_column(
        String(500), default="A new version is available. Please update to continue."
    )


class NotificationBroadcast(Base, UUIDPKMixin, TimestampMixin):
    """Record of a custom notification an admin pushed to all users. Kept
    separate from the per-user `notifications` table (notifications module)
    so the admin panel can show broadcast history/results without scanning
    every user's individual notification rows."""

    __tablename__ = "notification_broadcasts"

    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    title: Mapped[str] = mapped_column(String(150))
    body: Mapped[str] = mapped_column(String(1000))
    recipients_count: Mapped[int] = mapped_column(default=0)
    push_success_count: Mapped[int] = mapped_column(default=0)
