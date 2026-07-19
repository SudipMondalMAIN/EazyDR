import uuid

from pydantic import BaseModel, Field


class ReviewCreate(BaseModel):
    booking_id: uuid.UUID
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(None, max_length=1000)


class ReviewOut(BaseModel):
    id: uuid.UUID
    booking_id: uuid.UUID
    patient_id: uuid.UUID
    doctor_id: uuid.UUID
    facility_id: uuid.UUID
    rating: int
    comment: str | None
    is_hidden: bool

    class Config:
        from_attributes = True


class RatingSummary(BaseModel):
    average_rating: float | None
    total_reviews: int
