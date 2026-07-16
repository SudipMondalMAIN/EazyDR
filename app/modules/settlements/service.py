import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestError, NotFoundError
from app.modules.admin.service import log_action
from app.modules.bookings.models import Booking, BookingStatus, PaymentMode
from app.modules.facilities.models import Facility
from app.modules.settlements.models import CashSettlementBatch

# A CANCELLED booking never had cash change hands with the platform's cut
# owed on it (fee is refunded/waived), so it's excluded from settlement.
# Everything else that reached at least CONFIRMED is fair game — including
# NO_SHOW, since the facility/platform commission arrangement is on the
# booking itself, not contingent on the patient actually turning up.
_SETTLEABLE_STATUSES = [
    BookingStatus.CONFIRMED,
    BookingStatus.CHECKED_IN,
    BookingStatus.COMPLETED,
    BookingStatus.NO_SHOW,
]


def _unsettled_filters():
    return [
        Booking.payment_mode == PaymentMode.CASH,
        Booking.cash_commission_settled == False,  # noqa: E712
        Booking.status.in_(_SETTLEABLE_STATUSES),
    ]


async def get_outstanding_summary(db: AsyncSession) -> list[dict]:
    """Per-facility report of unsettled cash commission — what an admin
    calls a facility about to collect."""
    rows = await db.execute(
        select(
            Booking.facility_id,
            Facility.name,
            func.count(Booking.id),
            func.coalesce(func.sum(Booking.platform_commission_amount), 0),
        )
        .join(Facility, Facility.id == Booking.facility_id)
        .where(*_unsettled_filters())
        .group_by(Booking.facility_id, Facility.name)
        .order_by(func.coalesce(func.sum(Booking.platform_commission_amount), 0).desc())
    )
    return [
        {
            "facility_id": r[0],
            "facility_name": r[1],
            "unsettled_booking_count": int(r[2]),
            "unsettled_commission_total": float(r[3]),
        }
        for r in rows.all()
    ]


async def get_pending_bookings_for_facility(db: AsyncSession, facility_id: uuid.UUID) -> list[Booking]:
    result = await db.execute(
        select(Booking).where(Booking.facility_id == facility_id, *_unsettled_filters()).order_by(Booking.appointment_date)
    )
    return list(result.scalars().all())


async def settle_cash_commission(
    db: AsyncSession,
    actor_id: uuid.UUID,
    facility_id: uuid.UUID,
    booking_ids: list[uuid.UUID] | None,
    note: str | None,
) -> CashSettlementBatch:
    query = select(Booking).where(Booking.facility_id == facility_id, *_unsettled_filters())
    if booking_ids:
        query = query.where(Booking.id.in_(booking_ids))

    result = await db.execute(query)
    bookings = list(result.scalars().all())

    if not bookings:
        raise BadRequestError("No outstanding cash-commission bookings match this request")

    if booking_ids:
        found_ids = {b.id for b in bookings}
        missing = set(booking_ids) - found_ids
        if missing:
            preview = ", ".join(str(m) for m in list(missing)[:5])
            raise NotFoundError(
                f"{len(missing)} booking id(s) are not outstanding cash bookings for this facility: {preview}"
            )

    total_commission = sum(b.platform_commission_amount for b in bookings)

    batch = CashSettlementBatch(
        facility_id=facility_id,
        settled_by_user_id=actor_id,
        booking_count=len(bookings),
        total_commission_amount=total_commission,
        related_booking_ids=",".join(str(b.id) for b in bookings),
        note=note,
    )
    db.add(batch)

    for b in bookings:
        b.cash_commission_settled = True

    await db.commit()
    await db.refresh(batch)

    await log_action(
        db,
        actor_id,
        "settle_cash_commission",
        "facility",
        str(facility_id),
        f"batch={batch.id} bookings={len(bookings)} amount={total_commission}",
    )
    return batch


async def get_settlement_history(
    db: AsyncSession, facility_id: uuid.UUID | None, limit: int = 100
) -> list[CashSettlementBatch]:
    query = select(CashSettlementBatch).order_by(CashSettlementBatch.created_at.desc()).limit(limit)
    if facility_id:
        query = query.where(CashSettlementBatch.facility_id == facility_id)
    result = await db.execute(query)
    return list(result.scalars().all())
