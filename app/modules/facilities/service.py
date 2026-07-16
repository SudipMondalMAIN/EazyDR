import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import ForbiddenError, NotFoundError
from app.modules.facilities.models import Doctor, DoctorAvailability, Facility
from app.modules.facilities.schemas import (
    AvailabilitySlotCreate,
    DoctorCreate,
    FacilityCreate,
    FacilitySearchParams,
)
from app.services.geo_service import haversine_km


async def create_facility(db: AsyncSession, owner_user_id: uuid.UUID, payload: FacilityCreate) -> Facility:
    facility = Facility(owner_user_id=owner_user_id, **payload.model_dump())
    db.add(facility)
    await db.commit()
    await db.refresh(facility)
    return facility


async def get_facility(db: AsyncSession, facility_id: uuid.UUID) -> Facility:
    result = await db.execute(select(Facility).where(Facility.id == facility_id))
    facility = result.scalar_one_or_none()
    if not facility:
        raise NotFoundError("Facility not found")
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
