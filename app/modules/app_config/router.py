from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.app_config import service
from app.modules.app_config.schemas import (
    AppConfigOut,
    NavConfigUpdate,
    NotificationBroadcastCreate,
    NotificationBroadcastOut,
    ThemeConfigUpdate,
    VersionControlUpdate,
)
from app.modules.app_config.tasks import send_broadcast
from app.modules.auth.dependencies import require_superadmin
from app.modules.auth.models import User

# Public router — the User App calls this at splash, before login, so it
# must NOT require auth. No prefix beyond /api/v1 (not under /admin).
public_router = APIRouter(prefix="/api/v1", tags=["app-config"])

# Admin router — every write here is SuperAdmin-only per the founder-control
# requirement, and every change is audit-logged (see service.py).
admin_router = APIRouter(prefix="/api/v1/admin/app-config", tags=["admin-app-config"])


@public_router.get("/app-config", response_model=AppConfigOut)
async def get_app_config(db: AsyncSession = Depends(get_db)):
    return await service.get_config(db)


@admin_router.put("/nav", response_model=AppConfigOut)
async def update_nav(
    payload: NavConfigUpdate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_superadmin),
):
    return await service.update_nav_config(db, actor.id, payload)


@admin_router.put("/theme", response_model=AppConfigOut)
async def update_theme(
    payload: ThemeConfigUpdate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_superadmin),
):
    return await service.update_theme_config(db, actor.id, payload)


@admin_router.put("/version-control", response_model=AppConfigOut)
async def update_version_control(
    payload: VersionControlUpdate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_superadmin),
):
    return await service.update_version_control(db, actor.id, payload)


@admin_router.post("/notifications/broadcast", response_model=NotificationBroadcastOut)
async def broadcast_notification(
    payload: NotificationBroadcastCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_superadmin),
):
    # Record created with counts=0, then the celery task fills in real
    # numbers once fan-out completes (see tasks.py).
    record = await service.create_broadcast_record(
        db, actor.id, payload, recipients_count=0, push_success_count=0,
    )
    send_broadcast.delay(str(record.id), payload.title, payload.body)
    return record


@admin_router.get("/notifications/broadcasts", response_model=list[NotificationBroadcastOut])
async def list_broadcasts(
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_superadmin),
):
    return await service.list_broadcasts(db)
