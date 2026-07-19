import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.modules.bookings.models import Booking, BookingStatus
from app.modules.bookings.service import get_booking
from app.modules.reviews.models import Review
from app.modules.reviews.schemas import ReviewCreate


async def create_review(db: AsyncSession, patient_id: uuid.UUID, payload: ReviewCreate) -> Review:
    booking: Booking = await get_booking(db, payload.booking_id)
    if booking.patient_id != patient_id:
        raise ForbiddenError("You can only review your own bookings")
    if booking.status != BookingStatus.COMPLETED:
        raise BadRequestError("Only completed bookings can be reviewed")

    review = Review(
        booking_id=booking.id,
        patient_id=patient_id,
        doctor_id=booking.doctor_id,
        facility_id=booking.facility_id,
        rating=payload.rating,
        comment=payload.comment,
    )
    db.add(review)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ConflictError("This booking has already been reviewed")
    await db.refresh(review)
    return review


async def list_reviews_for_doctor(db: AsyncSession, doctor_id: uuid.UUID) -> list[Review]:
    result = await db.execute(
        select(Review)
        .where(Review.doctor_id == doctor_id, Review.is_hidden == False)  # noqa: E712
        .order_by(Review.created_at.desc())
    )
    return list(result.scalars().all())


async def list_reviews_for_facility(db: AsyncSession, facility_id: uuid.UUID) -> list[Review]:
    result = await db.execute(
        select(Review)
        .where(Review.facility_id == facility_id, Review.is_hidden == False)  # noqa: E712
        .order_by(Review.created_at.desc())
    )
    return list(result.scalars().all())


async def list_reviews_for_facility_admin(db: AsyncSession, facility_id: uuid.UUID) -> list[Review]:
    """Admin view — includes hidden/moderated reviews, unlike the public
    listing above, so admins can see what was flagged and why."""
    result = await db.execute(
        select(Review).where(Review.facility_id == facility_id).order_by(Review.created_at.desc())
    )
    return list(result.scalars().all())


async def list_reviews_by_patient(db: AsyncSession, patient_id: uuid.UUID) -> list[Review]:
    result = await db.execute(
        select(Review).where(Review.patient_id == patient_id).order_by(Review.created_at.desc())
    )
    return list(result.scalars().all())


async def get_doctor_rating_summary(db: AsyncSession, doctor_id: uuid.UUID) -> tuple[float | None, int]:
    result = await db.execute(
        select(func.avg(Review.rating), func.count(Review.id)).where(
            Review.doctor_id == doctor_id, Review.is_hidden == False  # noqa: E712
        )
    )
    avg_rating, total = result.one()
    return (round(float(avg_rating), 2) if avg_rating is not None else None), int(total)


async def get_facility_rating_summary(db: AsyncSession, facility_id: uuid.UUID) -> tuple[float | None, int]:
    result = await db.execute(
        select(func.avg(Review.rating), func.count(Review.id)).where(
            Review.facility_id == facility_id, Review.is_hidden == False  # noqa: E712
        )
    )
    avg_rating, total = result.one()
    return (round(float(avg_rating), 2) if avg_rating is not None else None), int(total)


async def get_review(db: AsyncSession, review_id: uuid.UUID) -> Review:
    result = await db.execute(select(Review).where(Review.id == review_id))
    review = result.scalar_one_or_none()
    if not review:
        raise NotFoundError("Review not found")
    return review


async def set_review_hidden(db: AsyncSession, review_id: uuid.UUID, hidden: bool) -> Review:
    review = await get_review(db, review_id)
    review.is_hidden = hidden
    await db.commit()
    await db.refresh(review)
    return review
