import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import ForbiddenError, NotFoundError
from app.modules.facilities.models import Doctor, DoctorAvailability, Facility
from app.modules.facilities.schemas import (
    AvailabilitySlotCreate,
    DoctorCreate,
    DoctorOut,
    FacilityCreate,
    FacilityOut,
    FacilitySearchParams,
)
from app.services.geo_service import haversine_km
from app.services.storage_service import storage_service


async def create_facility(db: AsyncSession, owner_user_id: uuid.UUID, payload: FacilityCreate) -> Facility:
    facility = Facility(owner_user_id=owner_user_id, **payload.model_dump())
    db.add(facility)
    await db.commit()
    await db.refresh(facility)
    return facility


async def list_facilities_for_owner(db: AsyncSession, owner_user_id: uuid.UUID) -> list[Facility]:
    result = await db.execute(select(Facility).where(Facility.owner_user_id == owner_user_id))
    return list(result.scalars().all())


async def get_facility(db: AsyncSession, facility_id: uuid.UUID) -> Facility:
    result = await db.execute(select(Facility).where(Facility.id == facility_id))
    facility = result.scalar_one_or_none()
    if not facility:
        raise NotFoundError("Facility not found")
    return facility


def attach_facility_photo_url(facility: Facility) -> FacilityOut:
    out = FacilityOut.model_validate(facility)
    if facility.photo_storage_key:
        out.photo_url = storage_service.get_public_url(facility.photo_storage_key)
    return out


async def update_facility_photo(db: AsyncSession, facility_id: uuid.UUID, storage_key: str) -> Facility:
    facility = await get_facility(db, facility_id)  # raises NotFoundError if missing
    if facility.photo_storage_key:
        try:
            await storage_service.delete_file(facility.photo_storage_key)
        except Exception:
            pass
    facility.photo_storage_key = storage_key
    await db.commit()
    await db.refresh(facility)
    return facility


async def search_facilities(db: AsyncSession, params: FacilitySearchParams) -> list[tuple[Facility, float | None]]:
    """Swiggy/Zomato-style search: text match on facility name/city + doctor
    name/specialty, filtered by radius if lat/lng given. At current
    Bolpur-launch scale this filters in Python; see geo_service.py for the
    PostGIS migration note for when facility count grows large."""
    stmt = select(Facility).where(Facility.is_active == True)  # noqa: E712

    if params.city:
        stmt = stmt.where(Facility.city.ilike(f"%{params.city}%"))

    if params.query:
        q = f"%{params.query}%"
        stmt = stmt.outerjoin(Doctor).where(
            or_(
                Facility.name.ilike(q),
                Facility.address.ilike(q),
                Doctor.full_name.ilike(q),
                Doctor.specialty.ilike(q),
            )
        ).distinct()

    result = await db.execute(stmt)
    facilities = result.scalars().unique().all()

    scored: list[tuple[Facility, float | None]] = []
    for f in facilities:
        distance = None
        if params.latitude is not None and params.longitude is not None:
            distance = haversine_km(params.latitude, params.longitude, f.latitude, f.longitude)
            if distance > params.radius_km:
                continue
        scored.append((f, distance))

    # Sponsored facilities float to the top, then by distance (nearest first)
    scored.sort(key=lambda pair: (not pair[0].is_ad_sponsored, pair[1] if pair[1] is not None else 0))
    return scored


async def verify_facility_owner(db: AsyncSession, facility_id: uuid.UUID, user_id: uuid.UUID) -> Facility:
    """Raises ForbiddenError unless `user_id` owns the given facility.
    Every merchant-only endpoint that acts on a specific facility (or a
    doctor/queue belonging to one) must call this — `require_merchant`
    only checks the user's *role*, never which facility they actually own."""
    facility = await get_facility(db, facility_id)  # raises NotFoundError if missing
    if facility.owner_user_id != user_id:
        raise ForbiddenError("You do not have permission to manage this facility")
    return facility


async def verify_doctor_owner(db: AsyncSession, doctor_id: uuid.UUID, user_id: uuid.UUID) -> Doctor:
    """Raises ForbiddenError unless `user_id` owns the facility this doctor
    belongs to. Returns the Doctor if ownership checks out."""
    doctor = await get_doctor(db, doctor_id)  # raises NotFoundError if missing
    await verify_facility_owner(db, doctor.facility_id, user_id)
    return doctor


async def add_doctor(db: AsyncSession, facility_id: uuid.UUID, payload: DoctorCreate) -> Doctor:
    await get_facility(db, facility_id)  # raises NotFoundError if missing
    doctor = Doctor(facility_id=facility_id, **payload.model_dump())
    db.add(doctor)
    await db.commit()
    await db.refresh(doctor)
    return doctor


async def get_doctor(db: AsyncSession, doctor_id: uuid.UUID) -> Doctor:
    result = await db.execute(select(Doctor).where(Doctor.id == doctor_id))
    doctor = result.scalar_one_or_none()
    if not doctor:
        raise NotFoundError("Doctor not found")
    return doctor


async def list_doctors_for_facility(db: AsyncSession, facility_id: uuid.UUID) -> list[Doctor]:
    result = await db.execute(
        select(Doctor).where(Doctor.facility_id == facility_id, Doctor.is_active == True)  # noqa: E712
    )
    return list(result.scalars().all())


async def list_doctors_for_facility_admin(db: AsyncSession, facility_id: uuid.UUID) -> list[Doctor]:
    """Admin view — includes inactive/deactivated doctors too, unlike the
    public listing above."""
    result = await db.execute(select(Doctor).where(Doctor.facility_id == facility_id))
    return list(result.scalars().all())


async def update_doctor(db: AsyncSession, doctor_id: uuid.UUID, updates: dict) -> Doctor:
    doctor = await get_doctor(db, doctor_id)
    for field, value in updates.items():
        if value is not None:
            setattr(doctor, field, value)
    await db.commit()
    await db.refresh(doctor)
    return doctor


def attach_doctor_photo_url(doctor: Doctor) -> DoctorOut:
    out = DoctorOut.model_validate(doctor)
    if doctor.photo_storage_key:
        out.photo_url = storage_service.get_public_url(doctor.photo_storage_key)
    return out


async def update_doctor_photo(db: AsyncSession, doctor_id: uuid.UUID, storage_key: str) -> Doctor:
    doctor = await get_doctor(db, doctor_id)  # raises NotFoundError if missing
    if doctor.photo_storage_key:
        try:
            await storage_service.delete_file(doctor.photo_storage_key)
        except Exception:
            pass
    doctor.photo_storage_key = storage_key
    await db.commit()
    await db.refresh(doctor)
    return doctor


async def set_availability(db: AsyncSession, doctor_id: uuid.UUID, payload: AvailabilitySlotCreate) -> DoctorAvailability:
    await get_doctor(db, doctor_id)
    slot = DoctorAvailability(doctor_id=doctor_id, **payload.model_dump())
    db.add(slot)
    await db.commit()
    await db.refresh(slot)
    return slot


async def list_availability(db: AsyncSession, doctor_id: uuid.UUID) -> list[DoctorAvailability]:
    result = await db.execute(select(DoctorAvailability).where(DoctorAvailability.doctor_id == doctor_id))
    return list(result.scalars().all())
