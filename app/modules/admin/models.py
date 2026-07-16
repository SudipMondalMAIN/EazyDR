import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.mixins import TimestampMixin, UUIDPKMixin
from app.core.database import Base


class AuditLog(Base, UUIDPKMixin, TimestampMixin):
    """Every admin action gets logged here and is visible to SuperAdmin, per
    spec section 3 ('all actions logged/audited'). Normal Admins cannot
    delete these rows via the API — only SuperAdmin read access is exposed."""

    __tablename__ = "audit_logs"

    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(100))
    target_type: Mapped[str] = mapped_column(String(50))
    target_id: Mapped[str] = mapped_column(String(100))
    details: Mapped[str | None] = mapped_column(String(1000), nullable=True)
