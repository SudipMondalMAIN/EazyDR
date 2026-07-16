import uuid
from datetime import datetime

from pydantic import BaseModel

from app.modules.bookings.models import BookingStatus


class BookingExportFilter(BaseModel):
    """Query filters for Admin Booking PDF export. All fields optional —
    an unset filter is simply not applied."""

    date: str | None = None            # exact "YYYY-MM-DD" match on appointment_date
    date_from: str | None = None       # inclusive range start "YYYY-MM-DD"
    date_to: str | None = None         # inclusive range end "YYYY-MM-DD"
    doctor_id: uuid.UUID | None = None
    facility_id: uuid.UUID | None = None
    status: BookingStatus | None = None


class FacilityPricingUpdate(BaseModel):
    booking_fee: float | None = None
    commission_percent_override: float | None = None
    cancellation_deduction_percent_override: float | None = None


class FacilityVerifyUpdate(BaseModel):
    is_verified: bool | None = None
    is_active: bool | None = None
    is_ad_sponsored: bool | None = None


class AuditLogOut(BaseModel):
    id: uuid.UUID
    actor_user_id: uuid.UUID
    action: str
    target_type: str
    target_id: str
    details: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class AnalyticsSummaryOut(BaseModel):
    total_bookings: int
    total_revenue_collected: float
    total_platform_commission: float
    active_facilities: int
    no_show_count: int
