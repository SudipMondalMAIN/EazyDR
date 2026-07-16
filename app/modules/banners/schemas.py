import uuid

from pydantic import BaseModel, Field

from app.modules.banners.models import AdStatus


# ---------------------------------------------------------------- Banners --
class BannerCreate(BaseModel):
    title: str
    image_storage_key: str
    redirect_url: str | None = None
    display_order: int = 0
    is_active: bool = True
    start_date: str | None = None
    end_date: str | None = None


class BannerUpdate(BaseModel):
    title: str | None = None
    image_storage_key: str | None = None
    redirect_url: str | None = None
    display_order: int | None = None
    is_active: bool | None = None
    start_date: str | None = None
    end_date: str | None = None


class BannerOut(BaseModel):
    id: uuid.UUID
    title: str
    image_storage_key: str
    image_url: str | None = None
    redirect_url: str | None = None
    display_order: int
    is_active: bool
    start_date: str | None = None
    end_date: str | None = None

    class Config:
        from_attributes = True


class ImageUploadOut(BaseModel):
    storage_key: str
    url: str


# ------------------------------------------------------------------- Ads --
class AdvertisementCreate(BaseModel):
    title: str
    image_storage_key: str
    category: str
    city: str = "Bolpur"
    duration_days: int = Field(7, gt=0, le=365)
    facility_id: uuid.UUID | None = None


class AdRejectPayload(BaseModel):
    reason: str


class AdvertisementOut(BaseModel):
    id: uuid.UUID
    merchant_user_id: uuid.UUID
    facility_id: uuid.UUID | None = None
    title: str
    image_storage_key: str
    image_url: str | None = None
    category: str
    city: str
    duration_days: int
    start_date: str | None = None
    end_date: str | None = None
    status: AdStatus
    rejection_reason: str | None = None
    is_sponsored: bool = False

    class Config:
        from_attributes = True
