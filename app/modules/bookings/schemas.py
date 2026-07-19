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
    expected_time: str      # "HH:MM"
    payment_mode: PaymentMode


class BookingOut(BaseModel):
    id: uuid.UUID
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


class CancelBookingRequest(BaseModel):
    reason: str | None = None


class CancelBookingResult(BaseModel):
    booking_id: uuid.UUID
    status: BookingStatus
    refund_reward_points: int
    deduction_percent_applied: float
