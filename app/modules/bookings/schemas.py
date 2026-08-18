import uuid
from datetime import datetime

from pydantic import BaseModel

from app.modules.bookings.models import BookingStatus, PaymentMode


class BookingCreate(BaseModel):
    facility_id: uuid.UUID
    doctor_id: uuid.UUID
    patient_name: str
    patient_phone: str
    patient_address: str
    appointment_date: str   # "YYYY-MM-DD"
    payment_mode: PaymentMode


class BookingOut(BaseModel):
    id: uuid.UUID
    booking_code: str
    facility_id: uuid.UUID
    doctor_id: uuid.UUID
    patient_name: str
    token_number: int
    appointment_date: str
    expected_time: str
    booking_fee: float
    payment_mode: PaymentMode
    status: BookingStatus
    qr_uuid: uuid.UUID
    created_at: datetime

    class Config:
        from_attributes = True


class BookingWithQrOut(BookingOut):
    qr_code_base64: str = ""
    doctor_name: str = ""
    facility_name: str = ""
    facility_address: str = ""


class BookingListItemOut(BookingOut):
    """Used by GET /bookings/my — same fields as BookingWithQrOut minus the
    QR (the list view doesn't need it), plus the facility photo so the
    app can show it without a follow-up call per booking."""
    doctor_name: str = ""
    facility_name: str = ""
    facility_address: str = ""
    facility_photo_url: str | None = None


class FacilityBookingListItemOut(BookingOut):
    """Used by GET /bookings/facility/{facility_id} — the Partner App's
    booking history for one of the merchant's own facilities. No facility
    name/address needed (the merchant already knows which facility they're
    viewing); just the doctor name plus patient contact info for reference."""
    doctor_name: str = ""
    patient_phone: str = ""


class QueueStatusOut(BaseModel):
    booking_id: uuid.UUID
    booking_code: str
    doctor_name: str
    facility_name: str
    appointment_date: str
    your_token: int
    status: BookingStatus
    current_token: int | None       # token currently in_progress right now, if any
    patients_ahead: int             # checked_in patients with a smaller token, not yet served
    estimated_wait_minutes: int | None
    updated_at: datetime


class CancelBookingRequest(BaseModel):
    reason: str | None = None


class VerifyOnlinePaymentRequest(BaseModel):
    gateway_response: dict = {}


class CancelBookingResult(BaseModel):
    booking_id: uuid.UUID
    booking_code: str
    status: BookingStatus
    refund_reward_points: int
    deduction_percent_applied: float