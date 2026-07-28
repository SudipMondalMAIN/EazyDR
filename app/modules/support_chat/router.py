import uuid

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import NotFoundError
from app.core.database import AsyncSessionLocal, get_db
from app.core.security import decode_token
from app.modules.auth.dependencies import get_current_user, require_admin
from app.modules.auth.models import User
from app.modules.support_chat import service
from app.modules.support_chat.models import ChatSessionStatus
from app.modules.support_chat.schemas import (
    ChatMessageIn,
    ChatMessageOut,
    ChatSessionOut,
    ChatSessionStart,
    ChatSessionSummary,
)
from app.modules.support_chat.ws_manager import chat_manager

router = APIRouter(prefix="/api/v1/support", tags=["support-chat"])


def _msg_payload(msg) -> dict:
    return {
        "type": "message",
        "id": str(msg.id),
        "session_id": str(msg.session_id),
        "sender_type": msg.sender_type.value,
        "sender_id": str(msg.sender_id) if msg.sender_id else None,
        "text": msg.text,
        "created_at": msg.created_at.isoformat(),
    }


async def _broadcast_new_messages(session_id: uuid.UUID, messages: list) -> None:
    for m in messages:
        await chat_manager.broadcast(session_id, _msg_payload(m))


# ---------- User-facing endpoints ----------


@router.post("/sessions", response_model=ChatSessionOut, status_code=201)
async def start_session(
    payload: ChatSessionStart, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    return await service.start_session(db, user.id, payload.language.value)


@router.get("/sessions/{session_id}", response_model=ChatSessionOut)
async def get_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await service.get_session(db, session_id)


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageOut])
async def get_messages(session_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await service.get_session(db, session_id)  # 404 if not found
    return await service.get_messages(db, session_id)


@router.post("/sessions/{session_id}/messages", response_model=list[ChatMessageOut])
async def send_message(
    session_id: uuid.UUID,
    payload: ChatMessageIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = await service.get_session(db, session_id)
    new_messages = await service.handle_user_message(db, session, payload.text)
    await _broadcast_new_messages(session_id, new_messages)
    return new_messages


@router.post("/sessions/{session_id}/escalate", response_model=ChatSessionOut)
async def escalate_session(
    session_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """'Talk to Customer Support' button — manual escalation regardless of
    what the bot thinks."""
    session = await service.get_session(db, session_id)
    session = await service.escalate(db, session, "User tapped 'Talk to Customer Support'")
    from app.modules.support_chat.models import ChatMessage, SenderType

    sys_msg = ChatMessage(
        session_id=session.id, sender_type=SenderType.SYSTEM, text="Connecting you to a support agent. Please wait a moment."
    )
    db.add(sys_msg)
    await db.commit()
    await db.refresh(sys_msg)
    await _broadcast_new_messages(session_id, [sys_msg])
    return session


@router.post("/sessions/{session_id}/close", response_model=ChatSessionOut)
async def end_chat(session_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """User-initiated 'End Chat' — only the session's own user can close it
    this way (admins close via the separate /admin/.../close route)."""
    session = await service.get_session(db, session_id)
    if session.user_id != user.id:
        raise NotFoundError("Chat session not found")
    session = await service.close_session(db, session)
    await chat_manager.broadcast(session_id, {"type": "session_closed", "session_id": str(session_id)})
    return session


# ---------- Admin endpoints (for the separate admin website to call) ----------


@router.get("/admin/inbox", response_model=list[ChatSessionSummary])
async def admin_inbox(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    return await service.list_inbox(db, statuses=[ChatSessionStatus.WAITING_AGENT, ChatSessionStatus.WITH_AGENT])


@router.post("/admin/sessions/{session_id}/claim", response_model=ChatSessionOut)
async def admin_claim(session_id: uuid.UUID, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    session = await service.get_session(db, session_id)
    return await service.claim_session(db, session, admin.id)


@router.post("/admin/sessions/{session_id}/messages", response_model=ChatMessageOut)
async def admin_send_message(
    session_id: uuid.UUID,
    payload: ChatMessageIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    session = await service.get_session(db, session_id)
    msg = await service.add_agent_message(db, session, admin.id, payload.text)
    await _broadcast_new_messages(session_id, [msg])
    return msg


@router.post("/admin/sessions/{session_id}/close", response_model=ChatSessionOut)
async def admin_close(session_id: uuid.UUID, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    session = await service.get_session(db, session_id)
    session = await service.close_session(db, session)
    await chat_manager.broadcast(session_id, {"type": "session_closed", "session_id": str(session_id)})
    return session


# ---------- WebSocket (used by both the Flutter app and the admin website) ----------


@router.websocket("/ws/{session_id}")
async def chat_ws(websocket: WebSocket, session_id: uuid.UUID, token: str = ""):
    """Auth via ?token=<access_token> query param (WebSocket clients can't
    easily set Authorization headers). Any authenticated user or admin who
    owns/handles the session can connect; a simple 'connect anyway' policy
    (session_id is a random UUID, not guessable) — tighten to strict
    ownership checks later if needed."""
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        await websocket.close(code=4401)
        return

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == payload["sub"]))
        user = result.scalar_one_or_none()
        if not user or not user.is_active:
            await websocket.close(code=4401)
            return
        try:
            session = await service.get_session(db, session_id)
        except Exception:
            await websocket.close(code=4404)
            return

    is_admin = user.role.value in ("admin", "superadmin")
    if not is_admin and session.user_id != user.id:
        await websocket.close(code=4403)
        return

    await chat_manager.connect(session_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            text = (data or {}).get("text", "").strip()
            if not text:
                continue
            async with AsyncSessionLocal() as db:
                session = await service.get_session(db, session_id)
                if is_admin:
                    new_messages = [await service.add_agent_message(db, session, user.id, text)]
                else:
                    new_messages = await service.handle_user_message(db, session, text)
            await _broadcast_new_messages(session_id, new_messages)
    except WebSocketDisconnect:
        chat_manager.disconnect(session_id, websocket)