import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.notifications import service
from app.modules.notifications.schemas import NotificationOut, UnreadCountOut

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("/me", response_model=list[NotificationOut])
async def my_notifications(
    unread_only: bool = False, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    return await service.list_notifications_for_user(db, user.id, unread_only)


@router.get("/me/unread-count", response_model=UnreadCountOut)
async def unread_count(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    count = await service.count_unread(db, user.id)
    return UnreadCountOut(unread_count=count)


@router.patch("/{notification_id}/read", response_model=NotificationOut)
async def mark_read(
    notification_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    return await service.mark_read(db, user.id, notification_id)


@router.post("/read-all")
async def mark_all_read(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    count = await service.mark_all_read(db, user.id)
    return {"marked_read": count}
