import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user, require_merchant
from app.modules.auth.models import User
from app.modules.facilities import service
from app.modules.facilities.schemas import (
    AvailabilitySlotCreate,
    AvailabilitySlotOut,
    DoctorCreate,
    DoctorOut,
    FacilityCreate,
    FacilityOut,
    FacilitySearchParams,
)
from app.services.cache_service import cache_service

router = APIRouter(prefix="/api/v1/facilities", tags=["facilities"])


@router.post("", response_model=FacilityOut, status_code=201)
async def create_facility(
    payload: FacilityCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_merchant),
):
    facility = await service.create_facility(db, user.id, payload)
    # A new facility can appear in existing search result pages, so those
    # cached pages (keyed by query params, not facility id) must go stale.
    await cache_service.delete_prefix("cache:facility_search:")
    return facility


@router.get("/search", response_model=list[FacilityOut])
async def search_facilities(
    query: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float = Query(5.0, gt=0),
    city: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    params = FacilitySearchParams(
        query=query, latitude=latitude, longitude=longitude, radius_km=radius_km, city=city
    )
    cache_key = (
        f"cache:facility_search:{query}:{latitude}:{longitude}:{radius_km}:{city}"
    )
    cached = await cache_service.get_json(cache_key)
    if cached is not None:
        return [FacilityOut.model_validate(item) for item in cached]

    results = await service.search_facilities(db, params)
    out = []
    for facility, distance in results:
        item = FacilityOut.model_validate(facility)
        item.distance_km = round(distance, 2) if distance is not None else None
        out.append(item)

    await cache_service.set_json(
        cache_key,
        [item.model_dump(mode="json") for item in out],
        settings.cache_ttl_facility_search,
    )
    return out


@router.get("/my", response_model=list[FacilityOut])
async def my_facilities(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_merchant),
):
    """Facilities owned by the logged-in merchant — lets the client find
    an existing facility on a fresh device instead of relying on a
    client-side cache of the facility id."""
    facilities = await service.list_facilities_for_owner(db, user.id)
    return [FacilityOut.model_validate(f) for f in facilities]


@router.get("/{facility_id}", response_model=FacilityOut)
async def get_facility(facility_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    cache_key = f"cache:facility:{facility_id}"
    cached = await cache_service.get_json(cache_key)
    if cached is not None:
        return FacilityOut.model_validate(cached)

    facility = await service.get_facility(db, facility_id)
    out = FacilityOut.model_validate(facility)
    await cache_service.set_json(cache_key, out.model_dump(mode="json"), settings.cache_ttl_facility_profile)
    return out


@router.post("/{facility_id}/doctors", response_model=DoctorOut, status_code=201)
async def add_doctor(
    facility_id: uuid.UUID,
    payload: DoctorCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_merchant),
):
    await service.verify_facility_owner(db, facility_id, user.id)
    doctor = await service.add_doctor(db, facility_id, payload)
    # New doctor can match a doctor-name/specialty search and shows up in
    # this facility's doctor list — invalidate both.
    await cache_service.delete_prefix("cache:facility_search:")
    await cache_service.delete(f"cache:facility:{facility_id}:doctors")
    return doctor


@router.get("/{facility_id}/doctors", response_model=list[DoctorOut])
async def list_doctors(facility_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    cache_key = f"cache:facility:{facility_id}:doctors"
    cached = await cache_service.get_json(cache_key)
    if cached is not None:
        return [DoctorOut.model_validate(item) for item in cached]

    doctors = await service.list_doctors_for_facility(db, facility_id)
    out = [DoctorOut.model_validate(d) for d in doctors]
    await cache_service.set_json(
        cache_key, [item.model_dump(mode="json") for item in out], settings.cache_ttl_facility_profile
    )
    return out


@router.post("/doctors/{doctor_id}/availability", response_model=AvailabilitySlotOut, status_code=201)
async def set_availability(
    doctor_id: uuid.UUID,
    payload: AvailabilitySlotCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_merchant),
):
    await service.verify_doctor_owner(db, doctor_id, user.id)
    return await service.set_availability(db, doctor_id, payload)


@router.get("/doctors/{doctor_id}/availability", response_model=list[AvailabilitySlotOut])
async def list_availability(doctor_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await service.list_availability(db, doctor_id)
