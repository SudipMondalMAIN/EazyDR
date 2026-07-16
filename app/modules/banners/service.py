import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.modules.banners.models import AdStatus, Advertisement, Banner
from app.modules.banners.schemas import AdvertisementCreate, BannerCreate, BannerUpdate
from app.services.storage_service import storage_service


def _today_str() -> str:
    return date.today().isoformat()


def attach_banner_url(banner: Banner) -> Banner:
    banner.image_url = storage_service.get_public_url(banner.image_storage_key)  # type: ignore[attr-defined]
    return banner


def attach_ad_extras(ad: Advertisement) -> Advertisement:
    ad.image_url = storage_service.get_public_url(ad.image_storage_key)  # type: ignore[attr-defined]
    today = _today_str()
    ad.is_sponsored = (  # type: ignore[attr-defined]
        ad.status == AdStatus.APPROVED
        and ad.start_date is not None
        and ad.end_date is not None
        and ad.start_date <= today <= ad.end_date
    )
    return ad


# ---------------------------------------------------------------- Banners --
async def create_banner(db: AsyncSession, payload: BannerCreate) -> Banner:
    banner = Banner(**payload.model_dump())
    db.add(banner)
    await db.commit()
    await db.refresh(banner)
    return banner


async def get_banner(db: AsyncSession, banner_id: uuid.UUID) -> Banner:
    result = await db.execute(select(Banner).where(Banner.id == banner_id))
    banner = result.scalar_one_or_none()
    if not banner:
        raise NotFoundError("Banner not found")
    return banner


async def update_banner(db: AsyncSession, banner_id: uuid.UUID, payload: BannerUpdate) -> Banner:
    banner = await get_banner(db, banner_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(banner, field, value)
    await db.commit()
    await db.refresh(banner)
    return banner


async def delete_banner(db: AsyncSession, banner_id: uuid.UUID) -> None:
    banner = await get_banner(db, banner_id)
    await db.delete(banner)
    await db.commit()


async def list_banners(db: AsyncSession, active_only: bool = False) -> list[Banner]:
    stmt = select(Banner).order_by(Banner.display_order.asc(), Banner.created_at.desc())
    result = await db.execute(stmt)
    banners = list(result.scalars().all())

    if not active_only:
        return banners

    today = _today_str()
    visible = []
    for b in banners:
        if not b.is_active:
            continue
        if b.start_date and today < b.start_date:
            continue
        if b.end_date and today > b.end_date:
            continue
        visible.append(b)
    return visible


# ------------------------------------------------------------------- Ads --
async def create_ad(db: AsyncSession, merchant_id: uuid.UUID, payload: AdvertisementCreate) -> Advertisement:
    ad = Advertisement(merchant_user_id=merchant_id, status=AdStatus.PENDING, **payload.model_dump())
    db.add(ad)
    await db.commit()
    await db.refresh(ad)
    return ad


async def get_ad(db: AsyncSession, ad_id: uuid.UUID) -> Advertisement:
    result = await db.execute(select(Advertisement).where(Advertisement.id == ad_id))
    ad = result.scalar_one_or_none()
    if not ad:
        raise NotFoundError("Advertisement not found")
    return ad


async def verify_ad_owner(db: AsyncSession, ad_id: uuid.UUID, merchant_id: uuid.UUID) -> Advertisement:
    ad = await get_ad(db, ad_id)
    if ad.merchant_user_id != merchant_id:
        raise ForbiddenError("You do not have permission to manage this advertisement")
    return ad


async def list_my_ads(db: AsyncSession, merchant_id: uuid.UUID) -> list[Advertisement]:
    result = await db.execute(
        select(Advertisement).where(Advertisement.merchant_user_id == merchant_id).order_by(Advertisement.created_at.desc())
    )
    return list(result.scalars().all())


async def list_ads_admin(db: AsyncSession, status: AdStatus | None = None) -> list[Advertisement]:
    stmt = select(Advertisement).order_by(Advertisement.created_at.desc())
    if status:
        stmt = stmt.where(Advertisement.status == status)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_approved_ads(
    db: AsyncSession, city: str | None = None, category: str | None = None
) -> list[Advertisement]:
    """Currently-live approved ads — these get the Sponsored badge and are
    shown above normal facility listings in the given city/category."""
    stmt = select(Advertisement).where(Advertisement.status == AdStatus.APPROVED)
    if city:
        stmt = stmt.where(Advertisement.city.ilike(f"%{city}%"))
    if category:
        stmt = stmt.where(Advertisement.category.ilike(f"%{category}%"))
    result = await db.execute(stmt)
    ads = list(result.scalars().all())

    today = _today_str()
    live = [
        ad for ad in ads
        if ad.start_date and ad.end_date and ad.start_date <= today <= ad.end_date
    ]
    live.sort(key=lambda a: a.created_at, reverse=True)
    return live


async def approve_ad(db: AsyncSession, ad_id: uuid.UUID) -> Advertisement:
    ad = await get_ad(db, ad_id)
    if ad.status == AdStatus.APPROVED:
        raise BadRequestError("Advertisement is already approved")
    start = date.today()
    end = start + timedelta(days=ad.duration_days)
    ad.status = AdStatus.APPROVED
    ad.start_date = start.isoformat()
    ad.end_date = end.isoformat()
    ad.rejection_reason = None
    await db.commit()
    await db.refresh(ad)
    return ad


async def reject_ad(db: AsyncSession, ad_id: uuid.UUID, reason: str) -> Advertisement:
    ad = await get_ad(db, ad_id)
    ad.status = AdStatus.REJECTED
    ad.rejection_reason = reason
    await db.commit()
    await db.refresh(ad)
    return ad


async def pause_ad(db: AsyncSession, ad_id: uuid.UUID) -> Advertisement:
    ad = await get_ad(db, ad_id)
    if ad.status != AdStatus.APPROVED:
        raise BadRequestError("Only approved advertisements can be paused")
    ad.status = AdStatus.PAUSED
    await db.commit()
    await db.refresh(ad)
    return ad


async def resume_ad(db: AsyncSession, ad_id: uuid.UUID) -> Advertisement:
    ad = await get_ad(db, ad_id)
    if ad.status != AdStatus.PAUSED:
        raise BadRequestError("Only paused advertisements can be resumed")
    ad.status = AdStatus.APPROVED
    await db.commit()
    await db.refresh(ad)
    return ad


async def delete_ad(db: AsyncSession, ad_id: uuid.UUID) -> None:
    ad = await get_ad(db, ad_id)
    await db.delete(ad)
    await db.commit()
