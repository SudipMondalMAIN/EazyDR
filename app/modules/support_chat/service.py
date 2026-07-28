import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import NotFoundError
from app.modules.support_chat.models import ChatMessage, ChatSession, ChatSessionStatus, SenderType
from app.modules.support_chat.schemas import ChatSessionSummary
from app.services.support_bot_service import get_bot_reply

# Keyword fallback used only if a user's very first message already sounds
# like they want a human (skips a wasted bot round-trip).
HUMAN_REQUEST_KEYWORDS = [
    "agent", "human", "support executive", "customer support", "customer care",
    "কথা বলতে চাই", "এজেন্ট", "কাস্টমার সাপোর্ট", "मानव", "एजेंट", "कस्टमर सपोर्ट",
]


async def start_session(db: AsyncSession, user_id: uuid.UUID, language: str) -> ChatSession:
    session = ChatSession(user_id=user_id, language=language, status=ChatSessionStatus.BOT)
    db.add(session)
    await db.commit()
    await db.refresh(session)

    greeting = {
        "english": "Hi! I'm EazyDoctor Support. How can I help you today? (booking, payment, cancellation, refund)",
        "hindi": "नमस्ते! मैं EazyDoctor सपोर्ट हूँ। आज मैं आपकी कैसे मदद कर सकता हूँ? (बुकिंग, पेमेंट, कैंसिलेशन, रिफंड)",
        "bengali": "হ্যালো! আমি EazyDoctor সাপোর্ট। আজ আপনাকে কীভাবে সাহায্য করতে পারি? (বুকিং, পেমেন্ট, ক্যানসেলেশন, রিফান্ড)",
    }.get(language, "Hi! I'm EazyDoctor Support. How can I help you today?")

    db.add(ChatMessage(session_id=session.id, sender_type=SenderType.BOT, text=greeting))
    await db.commit()
    return session


async def get_session(db: AsyncSession, session_id: uuid.UUID) -> ChatSession:
    session = (await db.execute(select(ChatSession).where(ChatSession.id == session_id))).scalar_one_or_none()
    if not session:
        raise NotFoundError("Chat session not found")
    return session


async def get_messages(db: AsyncSession, session_id: uuid.UUID) -> list[ChatMessage]:
    result = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at)
    )
    return list(result.scalars().all())


async def escalate(db: AsyncSession, session: ChatSession, reason: str) -> ChatSession:
    session.status = ChatSessionStatus.WAITING_AGENT
    session.escalation_reason = reason
    await db.commit()
    await db.refresh(session)
    return session


async def add_user_message(db: AsyncSession, session: ChatSession, text: str) -> ChatMessage:
    msg = ChatMessage(session_id=session.id, sender_type=SenderType.USER, sender_id=session.user_id, text=text)
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg


async def handle_user_message(db: AsyncSession, session: ChatSession, text: str) -> list[ChatMessage]:
    """Adds the user's message, then — if the session is still bot-handled —
    gets a bot reply (or escalates). Returns the list of new messages
    created (user msg [+ bot msg])."""
    user_msg = await add_user_message(db, session, text)
    new_messages = [user_msg]

    if session.status != ChatSessionStatus.BOT:
        # Already escalated / with an agent — bot stays out of it.
        return new_messages

    lowered = text.lower()
    if any(k in lowered for k in HUMAN_REQUEST_KEYWORDS):
        await escalate(db, session, "User requested a human agent")
        sys_msg = ChatMessage(
            session_id=session.id,
            sender_type=SenderType.SYSTEM,
            text="Connecting you to a support agent. Please wait a moment.",
        )
        db.add(sys_msg)
        await db.commit()
        await db.refresh(sys_msg)
        new_messages.append(sys_msg)
        return new_messages

    history_msgs = await get_messages(db, session.id)
    history = [
        {"role": "model" if m.sender_type != SenderType.USER else "user", "text": m.text}
        for m in history_msgs
        if m.sender_type in (SenderType.USER, SenderType.BOT)
    ]

    reply_text, should_escalate = await get_bot_reply(history, session.language.value)

    bot_msg = ChatMessage(session_id=session.id, sender_type=SenderType.BOT, text=reply_text)
    db.add(bot_msg)
    await db.commit()
    await db.refresh(bot_msg)
    new_messages.append(bot_msg)

    if should_escalate:
        await escalate(db, session, "Bot escalated (uncertain or human/medical request)")

    return new_messages


async def add_agent_message(db: AsyncSession, session: ChatSession, agent_id: uuid.UUID, text: str) -> ChatMessage:
    if session.status != ChatSessionStatus.WITH_AGENT:
        session.status = ChatSessionStatus.WITH_AGENT
    session.agent_id = agent_id
    msg = ChatMessage(session_id=session.id, sender_type=SenderType.AGENT, sender_id=agent_id, text=text)
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg


async def claim_session(db: AsyncSession, session: ChatSession, agent_id: uuid.UUID) -> ChatSession:
    session.status = ChatSessionStatus.WITH_AGENT
    session.agent_id = agent_id
    await db.commit()
    await db.refresh(session)
    return session


async def close_session(db: AsyncSession, session: ChatSession) -> ChatSession:
    session.status = ChatSessionStatus.CLOSED
    await db.commit()
    await db.refresh(session)
    return session


async def list_inbox(db: AsyncSession, statuses: list[ChatSessionStatus] | None = None) -> list[ChatSessionSummary]:
    """Admin support inbox — active/escalated sessions with a preview of the
    last message, newest activity first."""
    query = select(ChatSession)
    if statuses:
        query = query.where(ChatSession.status.in_(statuses))
    sessions = (await db.execute(query.order_by(ChatSession.created_at.desc()))).scalars().all()

    summaries = []
    for s in sessions:
        last = (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == s.id)
                .order_by(ChatMessage.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        summaries.append(
            ChatSessionSummary(
                id=s.id,
                user_id=s.user_id,
                status=s.status,
                language=s.language,
                escalation_reason=s.escalation_reason,
                last_message=last.text if last else None,
                last_message_at=last.created_at if last else None,
                created_at=s.created_at,
            )
        )
    summaries.sort(key=lambda s: s.last_message_at or s.created_at, reverse=True)
    return summaries
