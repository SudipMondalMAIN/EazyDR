import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.service import log_action
from app.modules.app_config.models import AppConfig, NotificationBroadcast
from app.modules.app_config.schemas import (
    NavConfigUpdate,
    NotificationBroadcastCreate,
    ThemeConfigUpdate,
    VersionControlUpdate,
)

DEFAULT_NAV_CONFIG = [
    {"key": "home", "label": "Home", "icon": "home", "order": 0, "visible": True, "screen": "home"},
    {"key": "search", "label": "Search", "icon": "search", "order": 1, "visible": True, "screen": "search"},
    {"key": "bookings", "label": "Bookings", "icon": "calendar", "order": 2, "visible": True, "screen": "bookings"},
    {"key": "wallet", "label": "Wallet", "icon": "wallet", "order": 3, "visible": True, "screen": "wallet"},
    {"key": "profile", "label": "Profile", "icon": "user", "order": 4, "visible": True, "screen": "profile"},
]


async def get_config(db: AsyncSession) -> AppConfig:
    """Always the single oldest row. Created with defaults on first read so
    callers never have to special-case a missing row."""
    result = await db.execute(select(AppConfig).order_by(AppConfig.created_at.asc()).limit(1))
    config = result.scalar_one_or_none()
    if config is None:
        config = AppConfig(nav_config=DEFAULT_NAV_CONFIG)
        db.add(config)
        await db.commit()
        await db.refresh(config)
    return config


async def update_nav_config(db: AsyncSession, actor_id: uuid.UUID, payload: NavConfigUpdate) -> AppConfig:
    config = await get_config(db)
    config.nav_config = [item.model_dump() for item in payload.nav_config]
    await db.commit()
    await db.refresh(config)
    await log_action(db, actor_id, "update_nav_config", "app_config", str(config.id))
    return config


async def update_theme_config(db: AsyncSession, actor_id: uuid.UUID, payload: ThemeConfigUpdate) -> AppConfig:
    config = await get_config(db)
    if payload.theme_mode is not None:
        config.theme_mode = payload.theme_mode
    if payload.primary_color is not None:
        config.primary_color = payload.primary_color
    if payload.secondary_color is not None:
        config.secondary_color = payload.secondary_color
    await db.commit()
    await db.refresh(config)
    await log_action(db, actor_id, "update_theme_config", "app_config", str(config.id))
    return config


async def update_version_control(db: AsyncSession, actor_id: uuid.UUID, payload: VersionControlUpdate) -> AppConfig:
    config = await get_config(db)
    if payload.min_app_version is not None:
        config.min_app_version = payload.min_app_version
    if payload.force_update is not None:
        config.force_update = payload.force_update
    if payload.update_message is not None:
        config.update_message = payload.update_message
    await db.commit()
    await db.refresh(config)
    await log_action(
        db, actor_id, "update_version_control", "app_config", str(config.id),
        details=f"force_update={config.force_update} min_version={config.min_app_version}",
    )
    return config


async def create_broadcast_record(
    db: AsyncSession, actor_id: uuid.UUID, payload: NotificationBroadcastCreate,
    recipients_count: int, push_success_count: int,
) -> NotificationBroadcast:
    record = NotificationBroadcast(
        actor_user_id=actor_id,
        title=payload.title,
        body=payload.body,
        recipients_count=recipients_count,
        push_success_count=push_success_count,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    await log_action(
        db, actor_id, "broadcast_notification", "notification_broadcast", str(record.id),
        details=f"recipients={recipients_count} push_ok={push_success_count}",
    )
    return record


async def list_broadcasts(db: AsyncSession, limit: int = 50) -> list[NotificationBroadcast]:
    result = await db.execute(
        select(NotificationBroadcast).order_by(NotificationBroadcast.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())