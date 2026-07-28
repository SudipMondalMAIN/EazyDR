import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import NotFoundError
from app.core.config import settings
from app.modules.auth.models import User
from app.modules.bookings import service as bookings_service
from app.modules.bookings.models import BookingStatus
from app.modules.facilities.service import get_doctor, get_facility
from app.modules.rewards.service import get_reward_balance
from app.modules.support_chat.models import ChatMessage, ChatSession, ChatSessionStatus, SenderType
from app.modules.support_chat.schemas import ChatSessionSummary
from app.services.notification_service import notification_service
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


async def _build_user_booking_context(db: AsyncSession, patient_id: uuid.UUID) -> str:
    """Rich plain-text summary of the user's account so the bot can actually
    answer 'where's my booking / did my payment go through / what's my
    refund status / how many people ahead of me / can I still cancel /
    how many points do I have' — instead of always saying it doesn't know.
    Capped to the 5 most recent bookings so the prompt stays small."""
    bookings = await bookings_service.list_bookings_for_patient(db, patient_id)
    reward_balance = await get_reward_balance(db, patient_id)

    if not bookings:
        return f"This user has no bookings yet. Reward point balance: {reward_balance}."

    bookings = sorted(bookings, key=lambda b: b.created_at, reverse=True)[:5]
    now = datetime.now(timezone.utc)
    lines = []
    for b in bookings:
        try:
            doctor = await get_doctor(db, b.doctor_id)
            facility = await get_facility(db, b.facility_id)
            doctor_name, facility_name = doctor.full_name, facility.name
        except Exception:
            doctor_name, facility_name = "Unknown doctor", "Unknown facility"

        line = (
            f"- Booking #{b.token_number} on {b.appointment_date} at {b.expected_time} with {doctor_name} "
            f"({facility_name}) — status: {b.status.value}, payment: {b.payment_mode.value}, "
            f"amount: ₹{b.booking_fee}, booking_id: {b.id}"
        )

        # Live queue position — only meaningful once the appointment day has
        # started and the booking is still active in the queue.
        if b.status in (BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN):
            try:
                q = await bookings_service.get_queue_status(db, b.id)
                if q["patients_ahead"] is not None:
                    wait = (
                        f"{q['estimated_wait_minutes']} min estimated wait"
                        if q["estimated_wait_minutes"] is not None
                        else "wait time unavailable"
                    )
                    line += (
                        f" | LIVE QUEUE: {q['patients_ahead']} patient(s) ahead, "
                        f"current token being seen: {q['current_token'] or 'none yet'}, {wait}"
                    )
            except Exception:
                pass

        # Cancellation eligibility — tell the bot directly whether the lock
        # window has already passed, so it doesn't have to guess.
        if b.status in (BookingStatus.PENDING, BookingStatus.CONFIRMED):
            try:
                appt_dt = bookings_service._appointment_datetime(b)
                hours_until = (appt_dt - now).total_seconds() / 3600
                if hours_until < settings.cancellation_lock_hours:
                    line += " | CANCELLATION: locked (too close to appointment time, cannot self-cancel)"
                else:
                    line += f" | CANCELLATION: still allowed (self-cancel from My Bookings, deduction applies)"
            except Exception:
                pass

        # Cash refund credited so far for this specific booking (cancellation case).
        if b.cancellation_refund_points:
            line += f" | {b.cancellation_refund_points} reward points credited for this cancellation"

        lines.append(line)

    return (
        f"This user's reward point balance: {reward_balance}.\n"
        "This user's recent bookings:\n" + "\n".join(lines)
    )


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

    reply_text, should_escalate = await get_bot_reply(
        db, session.user_id, history, session.language.value, await _build_user_booking_context(db, session.user_id)
    )

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

    # Best-effort — a push failure must never fail the agent's reply itself.
    try:
        user_result = await db.execute(select(User).where(User.id == session.user_id))
        user = user_result.scalar_one_or_none()
        if user and user.device_push_token:
            await notification_service.send_push(
                device_token=user.device_push_token,
                title="Support reply",
                body=text[:150],
                data={"chat_session_id": str(session.id)},
            )
    except Exception:  # noqa: BLE001
        pass

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