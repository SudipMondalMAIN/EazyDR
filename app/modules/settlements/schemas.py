import uuid
from datetime import datetime

from pydantic import BaseModel


class FacilityCashOutstandingOut(BaseModel):
    facility_id: uuid.UUID
    facility_name: str
    unsettled_booking_count: int
    unsettled_commission_total: float


class PendingCashBookingOut(BaseModel):
    booking_id: uuid.UUID
    appointment_date: str
    patient_name: str
    booking_fee: float
    platform_commission_amount: float
    status: str


class SettleCashCommissionRequest(BaseModel):
    # Omit to settle everything currently outstanding for the facility;
    # pass a subset to settle only those (e.g. partial cash collection).
    booking_ids: list[uuid.UUID] | None = None
    note: str | None = None


class CashSettlementBatchOut(BaseModel):
    id: uuid.UUID
    facility_id: uuid.UUID
    settled_by_user_id: uuid.UUID
    booking_count: int
    total_commission_amount: float
    note: str | None
    created_at: datetime

    class Config:
        from_attributes = True
