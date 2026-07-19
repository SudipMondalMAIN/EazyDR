import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.core.security import hash_password
from app.modules.admin.models import AuditLog
from app.modules.admin.pdf import generate_bookings_pdf
from app.modules.admin.schemas import (
    AdminUserCreate,
    BookingExportFilter,
    DoctorAdminUpdate,
    FacilityOwnerUpdate,
    FacilityPricingUpdate,
    FacilityVerifyUpdate,
    UserUpdateAdmin,
)
from app.modules.auth.models import User, UserRole
from app.modules.bookings.models import Booking, BookingStatus, PaymentMode
from app.modules.bookings.service import list_bookings_for_patient
from app.modules.facilities.models import Doctor, Facility
from app.modules.facilities.schemas import DoctorCreate
from app.modules.facilities.service import get_facility
from app.modules.facilities.service import add_doctor as fac_add_doctor
from app.modules.facilities.service import get_doctor as fac_get_doctor
from app.modules.facilities.service import list_doctors_for_facility_admin
from app.modules.facilities.service import update_doctor as fac_update_doctor
from app.modules.favorites.service import list_favorites_for_user
from app.modules.reviews.service import (
    get_facility_rating_summary,
    list_reviews_by_patient,
    list_reviews_for_facility_admin,
)
from app.modules.rewards.service import (
    get_earning_balance,
    get_reward_balance,
    list_earning_ledger_for_facility,
    list_reward_ledger_for_user,
    list_withdrawals_for_facility,
)


async def log_action(
    db: AsyncSession, actor_user_id: uuid.UUID, action: str, target_type: str, target_id: str, details: str | None = None
) -> None:
    entry = AuditLog(
        actor_user_id=actor_user_id, action=action, target_type=target_type, target_id=target_id, details=details
    )
    db.add(entry)
    await db.commit()


async def update_facility_pricing(db: AsyncSession, actor_id: uuid.UUID, facility_id: uuid.UUID, payload: FacilityPricingUpdate):
    facility = await get_facility(db, facility_id)
    if payload.booking_fee is not None:
        facility.booking_fee = payload.booking_fee
    if payload.commission_percent_override is not None:
        facility.commission_percent_override = payload.commission_percent_override
    if payload.cancellation_deduction_percent_override is not None:
        facility.cancellation_deduction_percent_override = payload.cancellation_deduction_percent_override
    await db.commit()
    await db.refresh(facility)
    await log_action(db, actor_id, "update_pricing", "facility", str(facility_id), payload.model_dump_json())
    return facility


async def update_facility_status(db: AsyncSession, actor_id: uuid.UUID, facility_id: uuid.UUID, payload: FacilityVerifyUpdate):
    facility = await get_facility(db, facility_id)
    if payload.is_verified is not None:
        facility.is_verified = payload.is_verified
    if payload.is_active is not None:
        facility.is_active = payload.is_active
    if payload.is_ad_sponsored is not None:
        facility.is_ad_sponsored = payload.is_ad_sponsored
    await db.commit()
    await db.refresh(facility)
    await log_action(db, actor_id, "update_status", "facility", str(facility_id), payload.model_dump_json())
    return facility


async def get_audit_logs(db: AsyncSession, limit: int = 100) -> list[AuditLog]:
    result = await db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit))
    return list(result.scalars().all())


async def get_analytics_summary(db: AsyncSession) -> dict:
    total_bookings = await db.execute(select(func.count(Booking.id)))
    revenue = await db.execute(
        select(func.coalesce(func.sum(Booking.booking_fee), 0)).where(Booking.status != BookingStatus.CANCELLED)
    )
    commission = await db.execute(
        select(func.coalesce(func.sum(Booking.platform_commission_amount), 0)).where(
            Booking.status != BookingStatus.CANCELLED
        )
    )
    no_shows = await db.execute(select(func.count(Booking.id)).where(Booking.status == BookingStatus.NO_SHOW))

    from app.modules.facilities.models import Facility

    active_facilities = await db.execute(select(func.count(Facility.id)).where(Facility.is_active == True))  # noqa: E712

    return {
        "total_bookings": int(total_bookings.scalar_one()),
        "total_revenue_collected": float(revenue.scalar_one()),
        "total_platform_commission": float(commission.scalar_one()),
        "active_facilities": int(active_facilities.scalar_one()),
        "no_show_count": int(no_shows.scalar_one()),
    }


async def export_bookings_pdf(db: AsyncSession, filters: BookingExportFilter) -> bytes:
    """Fetches bookings matching the given filters (date / date range /
    doctor / facility / status) and renders them into a downloadable PDF.
    Read-only: does not create, update, or otherwise touch booking rows.
    """
    query = (
        select(Booking, Doctor.full_name, Facility.name)
        .join(Doctor, Doctor.id == Booking.doctor_id)
        .join(Facility, Facility.id == Booking.facility_id)
    )

    if filters.date:
        query = query.where(Booking.appointment_date == filters.date)
    if filters.date_from:
        query = query.where(Booking.appointment_date >= filters.date_from)
    if filters.date_to:
        query = query.where(Booking.appointment_date <= filters.date_to)
    if filters.doctor_id:
        query = query.where(Booking.doctor_id == filters.doctor_id)
    if filters.facility_id:
        query = query.where(Booking.facility_id == filters.facility_id)
    if filters.status:
        query = query.where(Booking.status == filters.status)

    query = query.order_by(Booking.appointment_date.desc(), Booking.expected_time.asc())

    result = await db.execute(query)
    rows = result.all()

    doctor_name_filter = None
    facility_name_filter = None
    if filters.doctor_id:
        doc_res = await db.execute(select(Doctor.full_name).where(Doctor.id == filters.doctor_id))
        doctor_name_filter = doc_res.scalar_one_or_none()
    if filters.facility_id:
        fac_res = await db.execute(select(Facility.name).where(Facility.id == filters.facility_id))
        facility_name_filter = fac_res.scalar_one_or_none()

    export_rows = [
        {
            "booking_id": str(booking.id),
            "patient_name": booking.patient_name,
            "phone": booking.patient_phone,
            "doctor": doctor_name,
            "facility": facility_name,
            "booking_time": f"{booking.appointment_date} {booking.expected_time}",
            "token_number": booking.token_number,
            "status": booking.status.value,
            "payment_mode": booking.payment_mode.value,
            "booking_fee": f"{booking.booking_fee:.2f}",
        }
        for booking, doctor_name, facility_name in rows
    ]

    filter_summary = {
        "date": filters.date,
        "date_from": filters.date_from,
        "date_to": filters.date_to,
        "doctor_name": doctor_name_filter,
        "facility_name": facility_name_filter,
        "status": filters.status.value if filters.status else None,
    }
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return generate_bookings_pdf(export_rows, filter_summary, generated_at)


# ============================================================================
# USER MANAGEMENT (Admin + SuperAdmin)
# ============================================================================

_ELEVATED_ROLES = (UserRole.ADMIN, UserRole.SUPERADMIN)


async def list_users(
    db: AsyncSession,
    role: UserRole | None = None,
    is_active: bool | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[User]]:
    stmt = select(User)
    if role is not None:
        stmt = stmt.where(User.role == role)
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(User.full_name.ilike(like), User.phone.ilike(like), User.email.ilike(like)))

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = stmt.order_by(User.created_at.desc()).limit(limit).offset(offset)
    users = (await db.execute(stmt)).scalars().all()
    return int(total), list(users)


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User not found")
    return user


async def update_user(
    db: AsyncSession,
    actor: User,
    user_id: uuid.UUID,
    payload: UserUpdateAdmin,
) -> User:
    user = await get_user(db, user_id)

    # Only a SuperAdmin may promote/demote into or out of Admin/SuperAdmin,
    # and nobody may edit a SuperAdmin except another SuperAdmin.
    role_changing = payload.role is not None and payload.role != user.role
    touches_elevated = user.role in _ELEVATED_ROLES or (payload.role in _ELEVATED_ROLES if payload.role else False)
    if (role_changing or touches_elevated) and actor.role != UserRole.SUPERADMIN:
        raise ForbiddenError("Only a SuperAdmin can manage Admin/SuperAdmin accounts or role changes")
    if user.role == UserRole.SUPERADMIN and actor.id != user.id and actor.role != UserRole.SUPERADMIN:
        raise ForbiddenError("Only a SuperAdmin can edit another SuperAdmin's account")

    if payload.phone is not None and payload.phone != user.phone:
        existing = (await db.execute(select(User).where(User.phone == payload.phone))).scalar_one_or_none()
        if existing:
            raise ConflictError("Phone number already in use by another account")
        user.phone = payload.phone

    if payload.email is not None and payload.email != user.email:
        existing = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
        if existing:
            raise ConflictError("Email already in use by another account")
        user.email = payload.email

    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.role is not None:
        user.role = payload.role

    await db.commit()
    await db.refresh(user)
    await log_action(db, actor.id, "update_user", "user", str(user_id), payload.model_dump_json())
    return user


async def deactivate_user(db: AsyncSession, actor: User, user_id: uuid.UUID) -> User:
    """Soft-delete: accounts are deactivated, never hard-deleted, since
    bookings/facilities/audit logs reference user ids by foreign key."""
    user = await get_user(db, user_id)
    if user.role == UserRole.SUPERADMIN and actor.role != UserRole.SUPERADMIN:
        raise ForbiddenError("Only a SuperAdmin can deactivate a SuperAdmin account")
    if user.id == actor.id:
        raise BadRequestError("You can't deactivate your own account")
    user.is_active = False
    await db.commit()
    await db.refresh(user)
    await log_action(db, actor.id, "deactivate_user", "user", str(user_id))
    return user


async def create_admin_user(db: AsyncSession, actor: User, payload: AdminUserCreate) -> User:
    """SuperAdmin-only. The public /auth/register endpoint refuses
    ADMIN/SUPERADMIN roles outright — this is the only way to create one."""
    if payload.role not in _ELEVATED_ROLES:
        raise BadRequestError("role must be admin or superadmin")

    existing_phone = (await db.execute(select(User).where(User.phone == payload.phone))).scalar_one_or_none()
    if existing_phone:
        raise ConflictError("Phone number already registered")
    existing_email = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if existing_email:
        raise ConflictError("Email already registered")

    user = User(
        full_name=payload.full_name,
        phone=payload.phone,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_email_verified=True,  # created directly by a SuperAdmin, no signup OTP needed
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await log_action(db, actor.id, "create_admin_user", "user", str(user.id), f"role={payload.role.value}")
    return user


# ============================================================================
# MERCHANT / FACILITY MANAGEMENT (Admin + SuperAdmin)
# ============================================================================

async def _facility_admin_rows(db: AsyncSession, stmt) -> list[dict]:
    """Joins in owner info + doctor count for a Facility select statement
    and returns plain dicts ready for FacilityAdminOut.model_validate."""
    result = await db.execute(stmt)
    facilities = result.scalars().unique().all()
    if not facilities:
        return []

    owner_ids = {f.owner_user_id for f in facilities}
    owners_res = await db.execute(select(User).where(User.id.in_(owner_ids)))
    owners_by_id = {u.id: u for u in owners_res.scalars().all()}

    facility_ids = [f.id for f in facilities]
    counts_res = await db.execute(
        select(Doctor.facility_id, func.count(Doctor.id))
        .where(Doctor.facility_id.in_(facility_ids))
        .group_by(Doctor.facility_id)
    )
    doctor_counts = {fid: count for fid, count in counts_res.all()}

    rows = []
    for f in facilities:
        owner = owners_by_id.get(f.owner_user_id)
        rows.append(
            {
                "id": f.id,
                "name": f.name,
                "facility_type": f.facility_type,
                "address": f.address,
                "city": f.city,
                "state": f.state,
                "latitude": f.latitude,
                "longitude": f.longitude,
                "booking_fee": f.booking_fee,
                "commission_percent_override": f.commission_percent_override,
                "cancellation_deduction_percent_override": f.cancellation_deduction_percent_override,
                "is_verified": f.is_verified,
                "is_active": f.is_active,
                "is_ad_sponsored": f.is_ad_sponsored,
                "owner_user_id": f.owner_user_id,
                "owner_full_name": owner.full_name if owner else None,
                "owner_phone": owner.phone if owner else None,
                "owner_email": owner.email if owner else None,
                "doctor_count": doctor_counts.get(f.id, 0),
                "created_at": f.created_at,
            }
        )
    return rows


async def list_facilities_admin(
    db: AsyncSession,
    facility_type=None,
    is_verified: bool | None = None,
    is_active: bool | None = None,
    city: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[dict]]:
    stmt = select(Facility)
    if facility_type is not None:
        stmt = stmt.where(Facility.facility_type == facility_type)
    if is_verified is not None:
        stmt = stmt.where(Facility.is_verified == is_verified)
    if is_active is not None:
        stmt = stmt.where(Facility.is_active == is_active)
    if city:
        stmt = stmt.where(Facility.city.ilike(f"%{city}%"))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Facility.name.ilike(like), Facility.address.ilike(like)))

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = stmt.order_by(Facility.created_at.desc()).limit(limit).offset(offset)
    rows = await _facility_admin_rows(db, stmt)
    return int(total), rows


async def get_facility_admin(db: AsyncSession, facility_id: uuid.UUID) -> dict:
    stmt = select(Facility).where(Facility.id == facility_id)
    rows = await _facility_admin_rows(db, stmt)
    if not rows:
        raise NotFoundError("Facility not found")
    return rows[0]


async def deactivate_facility(db: AsyncSession, actor_id: uuid.UUID, facility_id: uuid.UUID) -> Facility:
    facility = await get_facility(db, facility_id)
    facility.is_active = False
    await db.commit()
    await db.refresh(facility)
    await log_action(db, actor_id, "deactivate_facility", "facility", str(facility_id))
    return facility


async def reassign_facility_owner(
    db: AsyncSession, actor_id: uuid.UUID, facility_id: uuid.UUID, payload: FacilityOwnerUpdate
) -> Facility:
    facility = await get_facility(db, facility_id)
    new_owner = await get_user(db, payload.owner_user_id)
    if new_owner.role != UserRole.MERCHANT:
        raise BadRequestError("New owner must be a merchant account")
    facility.owner_user_id = new_owner.id
    await db.commit()
    await db.refresh(facility)
    await log_action(
        db, actor_id, "reassign_facility_owner", "facility", str(facility_id), f"new_owner={new_owner.id}"
    )
    return facility


# ============================================================================
# FACILITY DRILL-DOWN: DOCTORS (Admin + SuperAdmin)
# ============================================================================

async def list_doctors_admin(db: AsyncSession, facility_id: uuid.UUID) -> list[Doctor]:
    await get_facility(db, facility_id)  # 404s cleanly if the facility itself doesn't exist
    return await list_doctors_for_facility_admin(db, facility_id)


async def add_doctor_admin(db: AsyncSession, actor_id: uuid.UUID, facility_id: uuid.UUID, payload: DoctorCreate) -> Doctor:
    doctor = await fac_add_doctor(db, facility_id, payload)
    await log_action(db, actor_id, "add_doctor", "doctor", str(doctor.id), f"facility={facility_id}")
    return doctor


async def update_doctor_admin(db: AsyncSession, actor_id: uuid.UUID, doctor_id: uuid.UUID, payload: DoctorAdminUpdate) -> Doctor:
    doctor = await fac_update_doctor(db, doctor_id, payload.model_dump(exclude_unset=True))
    await log_action(db, actor_id, "update_doctor", "doctor", str(doctor_id), payload.model_dump_json())
    return doctor


async def deactivate_doctor_admin(db: AsyncSession, actor_id: uuid.UUID, doctor_id: uuid.UUID) -> Doctor:
    """Soft-delete: bookings/reviews/availability reference doctor_id by FK,
    so a doctor profile is deactivated, never hard-deleted."""
    doctor = await fac_update_doctor(db, doctor_id, {"is_active": False})
    await log_action(db, actor_id, "deactivate_doctor", "doctor", str(doctor_id))
    return doctor


# ============================================================================
# FACILITY DRILL-DOWN: REVIEWS (Admin + SuperAdmin)
# ============================================================================

async def get_facility_reviews_admin(db: AsyncSession, facility_id: uuid.UUID) -> dict:
    await get_facility(db, facility_id)
    reviews = await list_reviews_for_facility_admin(db, facility_id)
    average_rating, total = await get_facility_rating_summary(db, facility_id)
    return {
        "summary": {"average_rating": average_rating, "total_reviews": total},
        "reviews": reviews,
    }


# ============================================================================
# FACILITY DRILL-DOWN: EARNINGS (Admin + SuperAdmin)
# ============================================================================

_SETTLEABLE_STATUSES = [
    BookingStatus.CONFIRMED,
    BookingStatus.CHECKED_IN,
    BookingStatus.COMPLETED,
    BookingStatus.NO_SHOW,
]


async def _unsettled_commission_total(db: AsyncSession, facility_id: uuid.UUID) -> float:
    result = await db.execute(
        select(func.coalesce(func.sum(Booking.platform_commission_amount), 0)).where(
            Booking.facility_id == facility_id,
            Booking.payment_mode == PaymentMode.CASH,
            Booking.cash_commission_settled == False,  # noqa: E712
            Booking.status.in_(_SETTLEABLE_STATUSES),
        )
    )
    return float(result.scalar_one())


async def get_facility_earnings_admin(db: AsyncSession, facility_id: uuid.UUID) -> dict:
    await get_facility(db, facility_id)
    balance = await get_earning_balance(db, facility_id)
    ledger = await list_earning_ledger_for_facility(db, facility_id)
    withdrawals = await list_withdrawals_for_facility(db, facility_id)
    unsettled = await _unsettled_commission_total(db, facility_id)
    return {
        "facility_id": facility_id,
        "balance": balance,
        "unsettled_commission_total": unsettled,
        "ledger": ledger,
        "withdrawals": withdrawals,
    }


# ============================================================================
# FACILITY DRILL-DOWN: DASHBOARD (Admin + SuperAdmin)
# ============================================================================

async def get_facility_dashboard_admin(db: AsyncSession, facility_id: uuid.UUID) -> dict:
    facility_row = await get_facility_admin(db, facility_id)
    doctors = await list_doctors_for_facility_admin(db, facility_id)

    status_counts_res = await db.execute(
        select(Booking.status, func.count(Booking.id))
        .where(Booking.facility_id == facility_id)
        .group_by(Booking.status)
    )
    by_status = {status.value: 0 for status in BookingStatus}
    total_bookings = 0
    for status, count in status_counts_res.all():
        by_status[status.value] = int(count)
        total_bookings += int(count)

    revenue_res = await db.execute(
        select(func.coalesce(func.sum(Booking.booking_fee), 0)).where(
            Booking.facility_id == facility_id, Booking.status != BookingStatus.CANCELLED
        )
    )
    commission_res = await db.execute(
        select(func.coalesce(func.sum(Booking.platform_commission_amount), 0)).where(
            Booking.facility_id == facility_id, Booking.status != BookingStatus.CANCELLED
        )
    )

    unsettled = await _unsettled_commission_total(db, facility_id)
    balance = await get_earning_balance(db, facility_id)
    average_rating, total_reviews = await get_facility_rating_summary(db, facility_id)

    return {
        "facility": facility_row,
        "doctors": doctors,
        "doctor_count": len(doctors),
        "total_bookings": total_bookings,
        "bookings_by_status": {
            "pending": by_status.get("pending", 0),
            "confirmed": by_status.get("confirmed", 0),
            "checked_in": by_status.get("checked_in", 0),
            "completed": by_status.get("completed", 0),
            "cancelled": by_status.get("cancelled", 0),
            "no_show": by_status.get("no_show", 0),
        },
        "total_revenue_collected": float(revenue_res.scalar_one()),
        "total_platform_commission": float(commission_res.scalar_one()),
        "unsettled_commission_total": unsettled,
        "earning_balance": balance,
        "rating": {"average_rating": average_rating, "total_reviews": total_reviews},
    }


# ============================================================================
# USER DRILL-DOWN (Admin + SuperAdmin)
# ============================================================================

async def get_user_bookings_admin(db: AsyncSession, user_id: uuid.UUID) -> list[Booking]:
    await get_user(db, user_id)
    return await list_bookings_for_patient(db, user_id)


async def get_user_reviews_admin(db: AsyncSession, user_id: uuid.UUID):
    await get_user(db, user_id)
    return await list_reviews_by_patient(db, user_id)


async def get_user_rewards_admin(db: AsyncSession, user_id: uuid.UUID) -> dict:
    await get_user(db, user_id)
    balance = await get_reward_balance(db, user_id)
    ledger = await list_reward_ledger_for_user(db, user_id)
    return {"user_id": user_id, "balance": balance, "ledger": ledger}


async def get_user_dashboard_admin(db: AsyncSession, user_id: uuid.UUID) -> dict:
    user = await get_user(db, user_id)

    status_counts_res = await db.execute(
        select(Booking.status, func.count(Booking.id))
        .where(Booking.patient_id == user_id)
        .group_by(Booking.status)
    )
    by_status = {status.value: 0 for status in BookingStatus}
    total_bookings = 0
    for status, count in status_counts_res.all():
        by_status[status.value] = int(count)
        total_bookings += int(count)

    spent_res = await db.execute(
        select(func.coalesce(func.sum(Booking.booking_fee), 0)).where(
            Booking.patient_id == user_id, Booking.status != BookingStatus.CANCELLED
        )
    )

    reward_balance = await get_reward_balance(db, user_id)
    reviews = await list_reviews_by_patient(db, user_id)
    favorites = await list_favorites_for_user(db, user_id)

    owned_facility_count = 0
    if user.role == UserRole.MERCHANT:
        count_res = await db.execute(select(func.count(Facility.id)).where(Facility.owner_user_id == user_id))
        owned_facility_count = int(count_res.scalar_one())

    return {
        "user": user,
        "total_bookings": total_bookings,
        "bookings_by_status": {
            "pending": by_status.get("pending", 0),
            "confirmed": by_status.get("confirmed", 0),
            "checked_in": by_status.get("checked_in", 0),
            "completed": by_status.get("completed", 0),
            "cancelled": by_status.get("cancelled", 0),
            "no_show": by_status.get("no_show", 0),
        },
        "total_spent": float(spent_res.scalar_one()),
        "reward_balance": reward_balance,
        "review_count": len(reviews),
        "favorite_count": len(favorites),
        "owned_facility_count": owned_facility_count,
    }
