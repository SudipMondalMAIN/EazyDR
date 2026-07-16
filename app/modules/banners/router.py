import uuid

from fastapi import APIRouter, Depends, File, Query, UploadFile

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import require_admin, require_merchant
from app.modules.auth.models import User
from app.modules.banners import service
from app.modules.banners.models import AdStatus
from app.modules.banners.schemas import (
    AdRejectPayload,
    AdvertisementCreate,
    AdvertisementOut,
    BannerCreate,
    BannerOut,
    BannerUpdate,
    ImageUploadOut,
)
from app.services.storage_service import storage_service

router = APIRouter(prefix="/api/v1", tags=["banners-ads"])


# ---------------------------------------------------------------- Banners --
@router.post("/banners/upload-image", response_model=ImageUploadOut)
async def upload_banner_image(file: UploadFile = File(...), user: User = Depends(require_admin)):
    key = await storage_service.upload_file(file.file, folder="banners")
    return ImageUploadOut(storage_key=key, url=storage_service.get_public_url(key))


@router.post("/banners", response_model=BannerOut, status_code=201)
async def create_banner(
    payload: BannerCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    banner = await service.create_banner(db, payload)
    return service.attach_banner_url(banner)


@router.get("/banners", response_model=list[BannerOut])
async def list_banners(
    active_only: bool = Query(True, description="If true, only currently-active, in-date-range banners"),
    db: AsyncSession = Depends(get_db),
):
    banners = await service.list_banners(db, active_only=active_only)
    return [service.attach_banner_url(b) for b in banners]


@router.patch("/banners/{banner_id}", response_model=BannerOut)
async def update_banner(
    banner_id: uuid.UUID,
    payload: BannerUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    banner = await service.update_banner(db, banner_id, payload)
    return service.attach_banner_url(banner)


@router.delete("/banners/{banner_id}", status_code=204)
async def delete_banner(
    banner_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    await service.delete_banner(db, banner_id)


# ------------------------------------------------------------------- Ads --
@router.post("/ads/upload-image", response_model=ImageUploadOut)
async def upload_ad_image(file: UploadFile = File(...), user: User = Depends(require_merchant)):
    key = await storage_service.upload_file(file.file, folder="ads")
    return ImageUploadOut(storage_key=key, url=storage_service.get_public_url(key))


@router.post("/ads", response_model=AdvertisementOut, status_code=201)
async def create_ad(
    payload: AdvertisementCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_merchant),
):
    ad = await service.create_ad(db, user.id, payload)
    return service.attach_ad_extras(ad)


@router.get("/ads/mine", response_model=list[AdvertisementOut])
async def list_my_ads(db: AsyncSession = Depends(get_db), user: User = Depends(require_merchant)):
    ads = await service.list_my_ads(db, user.id)
    return [service.attach_ad_extras(a) for a in ads]


@router.get("/ads/approved", response_model=list[AdvertisementOut])
async def list_approved_ads(
    city: str | None = None,
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Public feed of currently-live sponsored ads — shown above normal
    facility listings in the requested city/category."""
    ads = await service.list_approved_ads(db, city=city, category=category)
    return [service.attach_ad_extras(a) for a in ads]


@router.get("/ads", response_model=list[AdvertisementOut])
async def list_all_ads(
    status: AdStatus | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    ads = await service.list_ads_admin(db, status=status)
    return [service.attach_ad_extras(a) for a in ads]


@router.patch("/ads/{ad_id}/approve", response_model=AdvertisementOut)
async def approve_ad(
    ad_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
):
    ad = await service.approve_ad(db, ad_id)
    return service.attach_ad_extras(ad)


@router.patch("/ads/{ad_id}/reject", response_model=AdvertisementOut)
async def reject_ad(
    ad_id: uuid.UUID,
    payload: AdRejectPayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    ad = await service.reject_ad(db, ad_id, payload.reason)
    return service.attach_ad_extras(ad)


@router.patch("/ads/{ad_id}/pause", response_model=AdvertisementOut)
async def pause_ad(
    ad_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
):
    ad = await service.pause_ad(db, ad_id)
    return service.attach_ad_extras(ad)


@router.patch("/ads/{ad_id}/resume", response_model=AdvertisementOut)
async def resume_ad(
    ad_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
):
    ad = await service.resume_ad(db, ad_id)
    return service.attach_ad_extras(ad)


@router.delete("/ads/{ad_id}", status_code=204)
async def delete_ad(
    ad_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
):
    await service.delete_ad(db, ad_id)
