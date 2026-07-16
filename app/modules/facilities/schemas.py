import uuid

from pydantic import BaseModel, Field

from app.modules.facilities.models import FacilityType


class FacilityCreate(BaseModel):
    name: str
    facility_type: FacilityType
    address: str
    city: str = "Bolpur"
    state: str = "West Bengal"
    latitude: float
    longitude: float
    booking_fee: float = 10.0


class FacilityOut(BaseModel):
    id: uuid.UUID
    name: str
    facility_type: FacilityType
    address: str
    city: str
    latitude: float
    longitude: float
    booking_fee: float
    is_verified: bool
    is_active: bool
    is_ad_sponsored: bool
    distance_km: float | None = None

    class Config:
        from_attributes = True


class DoctorCreate(BaseModel):
    full_name: str
    qualification: str
    specialty: str
    consultation_fee: float = 0.0


class DoctorOut(BaseModel):
    id: uuid.UUID
    facility_id: uuid.UUID
    full_name: str
    qualification: str
    specialty: str
    consultation_fee: float
    is_active: bool

    class Config:
        from_attributes = True


class AvailabilitySlotCreate(BaseModel):
    day_of_week: int | None = Field(None, ge=0, le=6)
    start_time: str
    end_time: str
    slot_duration_minutes: int = 15
    is_leave: bool = False
    leave_date: str | None = None


class AvailabilitySlotOut(AvailabilitySlotCreate):
    id: uuid.UUID
    doctor_id: uuid.UUID

    class Config:
        from_attributes = True


class FacilitySearchParams(BaseModel):
    query: str | None = None           # doctor name / disease / specialty / area text
    latitude: float | None = None
    longitude: float | None = None
    radius_km: float = 5.0
    city: str | None = None
