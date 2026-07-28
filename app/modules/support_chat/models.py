import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.mixins import TimestampMixin, UUIDPKMixin
from app.core.database import Base


class ChatSessionStatus(str, enum.Enum):
    BOT = "bot"  # AI/rule bot is answering
    WAITING_AGENT = "waiting_agent"  # escalated, no admin has joined yet
    WITH_AGENT = "with_agent"  # an admin has joined and is replying
    CLOSED = "closed"


class ChatLanguage(str, enum.Enum):
    ENGLISH = "english"
    HINDI = "hindi"
    BENGALI = "bengali"


class SenderType(str, enum.Enum):
    USER = "user"
    BOT = "bot"
    AGENT = "agent"
    SYSTEM = "system"


class ChatSession(Base, UUIDPKMixin, TimestampMixin):
    """One support conversation for a user. Starts in BOT status; either the
    bot escalates automatically (uncertain / policy-restricted question) or
    the user taps 'Talk to Customer Support', which flips status to
    WAITING_AGENT so it shows up in the admin's live support inbox."""

    __tablename__ = "chat_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    status: Mapped[ChatSessionStatus] = mapped_column(
        Enum(ChatSessionStatus, name="chatsessionstatus"), default=ChatSessionStatus.BOT, index=True
    )
    language: Mapped[ChatLanguage] = mapped_column(
        Enum(ChatLanguage, name="chatlanguage"), default=ChatLanguage.ENGLISH
    )
    # Set when an admin actually joins the session (for "assigned to" display
    # in the admin inbox). Nullable — no agent assigned yet.
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Short reason the bot escalated (e.g. "user requested agent",
    # "bot uncertain", "health/medical question") — helps admin triage fast.
    escalation_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ChatMessage(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "chat_messages"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_sessions.id"), index=True
    )
    sender_type: Mapped[SenderType] = mapped_column(Enum(SenderType, name="chatsendertype"))
    # sender_id is null for bot/system messages
    sender_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    text: Mapped[str] = mapped_column(Text)
