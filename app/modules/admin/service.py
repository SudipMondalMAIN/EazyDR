import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import AuditLog
from app.modules.admin.pdf import generate_bookings_pdf
from app.modules.admin.schemas import BookingExportFilter, FacilityPricingUpdate, FacilityVerifyUpdate
from app.modules.bookings.models import Booking, BookingStatus
from app.modules.facilities.models import Doctor, Facility
from app.modules.facilities.service import get_facility


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
