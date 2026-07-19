import enum
import uuid

from sqlalchemy import Enum, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.mixins import TimestampMixin, UUIDPKMixin
from app.core.database import Base


class FavoriteTargetType(str, enum.Enum):
    DOCTOR = "doctor"
    FACILITY = "facility"


class Favorite(Base, UUIDPKMixin, TimestampMixin):
    """A patient's saved/bookmarked doctor or facility, for quick re-booking.
    A single polymorphic (target_type, target_id) pair is used instead of
    two nullable FK columns — with two nullable FKs, Postgres treats NULLs
    as distinct for uniqueness purposes, so duplicate favorites would slip
    through the unique constraint. This way one constraint reliably covers
    both target types."""

    __tablename__ = "favorites"
    __table_args__ = (
        UniqueConstraint("user_id", "target_type", "target_id", name="uq_favorite_user_target"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    target_type: Mapped[FavoriteTargetType] = mapped_column(Enum(FavoriteTargetType))
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
