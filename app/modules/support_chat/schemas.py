import uuid
from datetime import datetime

from pydantic import BaseModel

from app.modules.support_chat.models import ChatLanguage, ChatSessionStatus, SenderType


class ChatSessionOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    status: ChatSessionStatus
    language: ChatLanguage
    agent_id: uuid.UUID | None
    escalation_reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatMessageOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    sender_type: SenderType
    sender_id: uuid.UUID | None
    text: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatSessionStart(BaseModel):
    language: ChatLanguage = ChatLanguage.ENGLISH


class ChatMessageIn(BaseModel):
    text: str


class ChatSessionSummary(BaseModel):
    """Row shown in the admin support inbox list."""

    id: uuid.UUID
    user_id: uuid.UUID
    status: ChatSessionStatus
    language: ChatLanguage
    escalation_reason: str | None
    last_message: str | None
    last_message_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
