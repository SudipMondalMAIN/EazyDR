import uuid

from pydantic import BaseModel


class QrCheckInRequest(BaseModel):
    qr_uuid: uuid.UUID
    signature: str


class ManualCheckInRequest(BaseModel):
    doctor_id: uuid.UUID
    appointment_date: str
    booking_id: uuid.UUID | None = None
    patient_phone: str | None = None


class CheckInResult(BaseModel):
    booking_id: uuid.UUID
    patient_name: str
    doctor_id: uuid.UUID
    token_number: int
    status: str
    checked_in_at: str


class ConsultationResult(BaseModel):
    booking_id: uuid.UUID
    doctor_id: uuid.UUID
    token_number: int
    status: str
    consultation_started_at: str | None = None
    consultation_completed_at: str | None = None


class LiveQueueOut(BaseModel):
    doctor_id: uuid.UUID
    queue_date: str
    current_token: int
    is_stalled: bool
