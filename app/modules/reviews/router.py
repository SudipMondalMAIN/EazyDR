import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import require_admin, require_patient
from app.modules.auth.models import User
from app.modules.reviews import service
from app.modules.reviews.schemas import RatingSummary, ReviewCreate, ReviewOut

router = APIRouter(prefix="/api/v1/reviews", tags=["reviews"])


@router.post("", response_model=ReviewOut, status_code=201)
async def create_review(
    payload: ReviewCreate, db: AsyncSession = Depends(get_db), user: User = Depends(require_patient)
):
    return await service.create_review(db, user.id, payload)


@router.get("/doctor/{doctor_id}", response_model=list[ReviewOut])
async def list_doctor_reviews(doctor_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await service.list_reviews_for_doctor(db, doctor_id)


@router.get("/doctor/{doctor_id}/summary", response_model=RatingSummary)
async def doctor_rating_summary(doctor_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    average_rating, total = await service.get_doctor_rating_summary(db, doctor_id)
    return RatingSummary(average_rating=average_rating, total_reviews=total)


@router.get("/facility/{facility_id}", response_model=list[ReviewOut])
async def list_facility_reviews(facility_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await service.list_reviews_for_facility(db, facility_id)


@router.get("/facility/{facility_id}/summary", response_model=RatingSummary)
async def facility_rating_summary(facility_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    average_rating, total = await service.get_facility_rating_summary(db, facility_id)
    return RatingSummary(average_rating=average_rating, total_reviews=total)


@router.patch("/{review_id}/hide", response_model=ReviewOut)
async def hide_review(review_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    """Admin moderation — hide an inappropriate review without deleting it."""
    return await service.set_review_hidden(db, review_id, True)


@router.patch("/{review_id}/unhide", response_model=ReviewOut)
async def unhide_review(review_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    return await service.set_review_hidden(db, review_id, False)
