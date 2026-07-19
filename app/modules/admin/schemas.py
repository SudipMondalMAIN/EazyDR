import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr

from app.modules.auth.models import UserRole
from app.modules.bookings.models import BookingStatus
from app.modules.facilities.models import FacilityType


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


# ---------------------------- User management ----------------------------

class UserAdminOut(BaseModel):
    id: uuid.UUID
    full_name: str
    phone: str
    email: EmailStr
    role: UserRole
    is_active: bool
    is_phone_verified: bool
    is_email_verified: bool
    created_at: datetime

    class Config:
        from_attributes = True


class UserListOut(BaseModel):
    total: int
    items: list[UserAdminOut]


class UserUpdateAdmin(BaseModel):
    """All fields optional/patch-style. `role` may only be changed to/from
    ADMIN or SUPERADMIN by a SuperAdmin — enforced in the service layer,
    not just here, since this schema alone can't see who's calling it."""

    full_name: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    is_active: bool | None = None
    role: UserRole | None = None


class AdminUserCreate(BaseModel):
    """SuperAdmin-only: create an Admin or SuperAdmin account directly
    (these roles can never self-register — see auth/service.py)."""

    full_name: str
    phone: str
    email: EmailStr
    password: str
    role: UserRole = UserRole.ADMIN


# ------------------------- Merchant / facility management -------------------------

class FacilityAdminOut(BaseModel):
    id: uuid.UUID
    name: str
    facility_type: FacilityType
    address: str
    city: str
    state: str
    latitude: float
    longitude: float
    booking_fee: float
    commission_percent_override: float | None
    cancellation_deduction_percent_override: float | None
    is_verified: bool
    is_active: bool
    is_ad_sponsored: bool
    owner_user_id: uuid.UUID
    owner_full_name: str | None = None
    owner_phone: str | None = None
    owner_email: str | None = None
    doctor_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


class FacilityListOut(BaseModel):
    total: int
    items: list[FacilityAdminOut]


class FacilityOwnerUpdate(BaseModel):
    """Reassign a facility to a different merchant account (e.g. the
    original owner lost access to their phone/email)."""

    owner_user_id: uuid.UUID


# --------------------- Facility drill-down: doctors ---------------------

class DoctorAdminOut(BaseModel):
    id: uuid.UUID
    facility_id: uuid.UUID
    full_name: str
    qualification: str
    specialty: str
    consultation_fee: float
    is_active: bool

    class Config:
        from_attributes = True


class DoctorAdminUpdate(BaseModel):
    """All fields optional/patch-style. `is_active=False` is how a doctor
    profile is soft-removed — bookings reference doctor_id by FK, so a
    hard delete is never offered here."""

    full_name: str | None = None
    qualification: str | None = None
    specialty: str | None = None
    consultation_fee: float | None = None
    is_active: bool | None = None


# --------------------- Facility drill-down: reviews ---------------------

class ReviewAdminOut(BaseModel):
    id: uuid.UUID
    booking_id: uuid.UUID
    patient_id: uuid.UUID
    doctor_id: uuid.UUID
    facility_id: uuid.UUID
    rating: int
    comment: str | None
    is_hidden: bool
    created_at: datetime

    class Config:
        from_attributes = True


class RatingSummaryOut(BaseModel):
    average_rating: float | None
    total_reviews: int


class FacilityReviewsOut(BaseModel):
    summary: RatingSummaryOut
    reviews: list[ReviewAdminOut]


# --------------------- Facility drill-down: earnings ---------------------

class EarningLedgerEntryOut(BaseModel):
    id: uuid.UUID
    entry_type: str
    amount: float
    related_booking_id: uuid.UUID | None
    payout_transaction_ref: str | None
    note: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class WithdrawalRequestOut(BaseModel):
    id: uuid.UUID
    amount: float
    status: str
    payout_transaction_ref: str | None
    failure_reason: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class FacilityEarningsOut(BaseModel):
    facility_id: uuid.UUID
    balance: float
    unsettled_commission_total: float
    ledger: list[EarningLedgerEntryOut]
    withdrawals: list[WithdrawalRequestOut]


# --------------------- Facility drill-down: dashboard ---------------------

class BookingsByStatusOut(BaseModel):
    pending: int = 0
    confirmed: int = 0
    checked_in: int = 0
    completed: int = 0
    cancelled: int = 0
    no_show: int = 0


class FacilityDashboardOut(BaseModel):
    facility: FacilityAdminOut
    doctors: list[DoctorAdminOut]
    doctor_count: int
    total_bookings: int
    bookings_by_status: BookingsByStatusOut
    total_revenue_collected: float
    total_platform_commission: float
    unsettled_commission_total: float
    earning_balance: float
    rating: RatingSummaryOut


# --------------------- User drill-down ---------------------

class RewardLedgerEntryOut(BaseModel):
    id: uuid.UUID
    entry_type: str
    points: int
    related_booking_id: uuid.UUID | None
    note: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class UserRewardsOut(BaseModel):
    user_id: uuid.UUID
    balance: int
    ledger: list[RewardLedgerEntryOut]


class UserDashboardOut(BaseModel):
    user: UserAdminOut
    total_bookings: int
    bookings_by_status: BookingsByStatusOut
    total_spent: float
    reward_balance: int
    review_count: int
    favorite_count: int
    owned_facility_count: int  # only meaningful for merchant accounts
