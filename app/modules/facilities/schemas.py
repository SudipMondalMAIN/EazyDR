import re
import uuid

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.modules.facilities.models import FacilityType

PHONE_RE = re.compile(r"^\+?[0-9]{10,15}$")


class FacilityCreate(BaseModel):
    name: str
    facility_type: FacilityType
    address: str
    city: str = "Bolpur"
    state: str = "West Bengal"
    latitude: float
    longitude: float
    booking_fee: float = 10.0
    phone: str | None = None
    email: EmailStr | None = None
    description: str | None = None
    working_hours: str | None = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v):
        if v is not None and not PHONE_RE.match(v):
            raise ValueError("Phone number must be 10-15 digits, optionally prefixed with +")
        return v


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
    photo_storage_key: str | None = None
    photo_url: str | None = None
    distance_km: float | None = None
    phone: str | None = None
    email: str | None = None
    description: str | None = None
    working_hours: str | None = None

    class Config:
        from_attributes = True


class FacilityUpdate(BaseModel):
    """Patch-style self-service update for the facility owner (merchant).
    All fields optional; only fields explicitly provided are changed."""

    name: str | None = Field(None, min_length=2, max_length=200)
    address: str | None = Field(None, min_length=5, max_length=500)
    city: str | None = Field(None, min_length=2, max_length=100)
    state: str | None = Field(None, min_length=2, max_length=100)
    phone: str | None = None
    email: EmailStr | None = None
    description: str | None = Field(None, max_length=2000)
    working_hours: str | None = Field(None, max_length=500)
    latitude: float | None = None
    longitude: float | None = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v):
        if v is not None and not PHONE_RE.match(v):
            raise ValueError("Phone number must be 10-15 digits, optionally prefixed with +")
        return v

    @field_validator("name", "address", "city", "state", "description", "working_hours")
    @classmethod
    def strip_and_reject_blank(cls, v):
        if v is not None:
            v = v.strip()
            if v == "":
                raise ValueError("Field cannot be blank")
        return v


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
    photo_storage_key: str | None = None
    photo_url: str | None = None

    class Config:
        from_attributes = True


class DoctorUpdate(BaseModel):
    """Patch-style self-service update for the doctor's owning merchant."""

    full_name: str | None = Field(None, min_length=2, max_length=150)
    qualification: str | None = Field(None, min_length=2, max_length=300)
    specialty: str | None = Field(None, min_length=2, max_length=150)
    consultation_fee: float | None = Field(None, ge=0)
    is_active: bool | None = None

    @field_validator("full_name", "qualification", "specialty")
    @classmethod
    def strip_and_reject_blank(cls, v):
        if v is not None:
            v = v.strip()
            if v == "":
                raise ValueError("Field cannot be blank")
        return v


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
