import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.admin import service
from app.modules.admin.schemas import (
    AdminUserCreate,
    AnalyticsSummaryOut,
    AuditLogOut,
    BookingExportFilter,
    DoctorAdminOut,
    DoctorAdminUpdate,
    FacilityAdminOut,
    FacilityDashboardOut,
    FacilityEarningsOut,
    FacilityListOut,
    FacilityOwnerUpdate,
    FacilityPricingUpdate,
    FacilityReviewsOut,
    FacilityVerifyUpdate,
    UserAdminOut,
    UserDashboardOut,
    UserListOut,
    UserRewardsOut,
    UserUpdateAdmin,
)
from app.modules.auth.dependencies import require_admin, require_superadmin
from app.modules.auth.models import User, UserRole
from app.modules.bookings.models import BookingStatus
from app.modules.bookings.schemas import BookingOut
from app.modules.facilities.models import FacilityType
from app.modules.facilities.schemas import DoctorCreate, FacilityOut
from app.modules.reviews.schemas import ReviewOut

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.patch("/facilities/{facility_id}/pricing", response_model=FacilityOut)
async def update_pricing(
    facility_id: uuid.UUID,
    payload: FacilityPricingUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    return await service.update_facility_pricing(db, user.id, facility_id, payload)


@router.patch("/facilities/{facility_id}/status", response_model=FacilityOut)
async def update_status(
    facility_id: uuid.UUID,
    payload: FacilityVerifyUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    return await service.update_facility_status(db, user.id, facility_id, payload)


@router.get("/audit-logs", response_model=list[AuditLogOut])
async def audit_logs(
    limit: int = 100, db: AsyncSession = Depends(get_db), user: User = Depends(require_superadmin)
):
    """Only SuperAdmin can view the audit trail, per spec section 3."""
    return await service.get_audit_logs(db, limit)


@router.get("/analytics/summary", response_model=AnalyticsSummaryOut)
async def analytics_summary(db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    return await service.get_analytics_summary(db)


@router.get("/bookings/export/pdf")
async def export_bookings_pdf(
    date: str | None = Query(default=None, description="Exact date filter, YYYY-MM-DD"),
    date_from: str | None = Query(default=None, description="Range start, YYYY-MM-DD"),
    date_to: str | None = Query(default=None, description="Range end, YYYY-MM-DD"),
    doctor_id: uuid.UUID | None = Query(default=None),
    facility_id: uuid.UUID | None = Query(default=None),
    status: BookingStatus | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Downloads a professionally formatted A4 PDF of bookings matching the
    given filters (date / date range / doctor / facility / status)."""
    filters = BookingExportFilter(
        date=date,
        date_from=date_from,
        date_to=date_to,
        doctor_id=doctor_id,
        facility_id=facility_id,
        status=status,
    )
    pdf_bytes = await service.export_bookings_pdf(db, filters)
    filename = f"bookings-export-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ============================================================================
# USER MANAGEMENT (Admin + SuperAdmin)
# ============================================================================

@router.get("/users", response_model=UserListOut)
async def list_users(
    role: UserRole | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    q: str | None = Query(default=None, description="Search by name, phone, or email"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    total, users = await service.list_users(db, role=role, is_active=is_active, q=q, limit=limit, offset=offset)
    return UserListOut(total=total, items=[UserAdminOut.model_validate(u) for u in users])


@router.get("/users/{user_id}", response_model=UserAdminOut)
async def get_user(user_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)):
    return await service.get_user(db, user_id)


@router.patch("/users/{user_id}", response_model=UserAdminOut)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdateAdmin,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_admin),
):
    """Edit any user's profile, activate/deactivate (ban/unban), or change
    role. Role changes and anything touching an Admin/SuperAdmin account
    are SuperAdmin-only — enforced in the service layer."""
    return await service.update_user(db, actor, user_id, payload)


@router.delete("/users/{user_id}", response_model=UserAdminOut)
async def deactivate_user(
    user_id: uuid.UUID, db: AsyncSession = Depends(get_db), actor: User = Depends(require_admin)
):
    """Soft-delete: deactivates the account (never a hard delete, since
    bookings/facilities reference the user id)."""
    return await service.deactivate_user(db, actor, user_id)


@router.post("/users", response_model=UserAdminOut, status_code=201)
async def create_admin_user(
    payload: AdminUserCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_superadmin),
):
    """SuperAdmin-only: directly create an Admin or SuperAdmin account.
    Public /auth/register always refuses these roles."""
    return await service.create_admin_user(db, actor, payload)


# ============================================================================
# MERCHANT / FACILITY MANAGEMENT (Admin + SuperAdmin)
# ============================================================================

@router.get("/facilities", response_model=FacilityListOut)
async def list_facilities_admin(
    facility_type: FacilityType | None = Query(default=None),
    is_verified: bool | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    city: str | None = Query(default=None),
    q: str | None = Query(default=None, description="Search by facility name or address"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Full facility list including unverified/inactive ones (the public
    /facilities/search endpoint only ever shows active facilities), with
    owner contact details and doctor count attached."""
    total, rows = await service.list_facilities_admin(
        db,
        facility_type=facility_type,
        is_verified=is_verified,
        is_active=is_active,
        city=city,
        q=q,
        limit=limit,
        offset=offset,
    )
    return FacilityListOut(total=total, items=[FacilityAdminOut.model_validate(r) for r in rows])


@router.get("/facilities/{facility_id}", response_model=FacilityAdminOut)
async def get_facility_admin(
    facility_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
):
    row = await service.get_facility_admin(db, facility_id)
    return FacilityAdminOut.model_validate(row)


@router.delete("/facilities/{facility_id}", response_model=FacilityOut)
async def deactivate_facility(
    facility_id: uuid.UUID, db: AsyncSession = Depends(get_db), actor: User = Depends(require_admin)
):
    """Soft-delete: deactivates the facility (never a hard delete)."""
    return await service.deactivate_facility(db, actor.id, facility_id)


@router.patch("/facilities/{facility_id}/owner", response_model=FacilityOut)
async def reassign_facility_owner(
    facility_id: uuid.UUID,
    payload: FacilityOwnerUpdate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_superadmin),
):
    """SuperAdmin-only: move a facility to a different merchant account
    (e.g. the original owner lost access to their phone/email)."""
    return await service.reassign_facility_owner(db, actor.id, facility_id, payload)


# ============================================================================
# FACILITY DRILL-DOWN: DOCTORS, REVIEWS, EARNINGS, DASHBOARD (Admin + SuperAdmin)
# ============================================================================

@router.get("/facilities/{facility_id}/doctors", response_model=list[DoctorAdminOut])
async def list_facility_doctors_admin(
    facility_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
):
    """Includes inactive/deactivated doctors, unlike the public
    /facilities/{id}/doctors endpoint."""
    return await service.list_doctors_admin(db, facility_id)


@router.post("/facilities/{facility_id}/doctors", response_model=DoctorAdminOut, status_code=201)
async def add_facility_doctor_admin(
    facility_id: uuid.UUID,
    payload: DoctorCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_admin),
):
    """Admin can add a doctor to any facility directly, without going
    through the owning merchant."""
    return await service.add_doctor_admin(db, actor.id, facility_id, payload)


@router.patch("/doctors/{doctor_id}", response_model=DoctorAdminOut)
async def update_doctor_admin(
    doctor_id: uuid.UUID,
    payload: DoctorAdminUpdate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_admin),
):
    return await service.update_doctor_admin(db, actor.id, doctor_id, payload)


@router.delete("/doctors/{doctor_id}", response_model=DoctorAdminOut)
async def deactivate_doctor_admin(
    doctor_id: uuid.UUID, db: AsyncSession = Depends(get_db), actor: User = Depends(require_admin)
):
    """Soft-delete: deactivates the doctor profile (never a hard delete)."""
    return await service.deactivate_doctor_admin(db, actor.id, doctor_id)


@router.get("/facilities/{facility_id}/reviews", response_model=FacilityReviewsOut)
async def facility_reviews_admin(
    facility_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
):
    """Includes hidden/moderated reviews, unlike the public reviews
    endpoints under /api/v1/reviews."""
    return await service.get_facility_reviews_admin(db, facility_id)


@router.get("/facilities/{facility_id}/earnings", response_model=FacilityEarningsOut)
async def facility_earnings_admin(
    facility_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
):
    """Facility's current earning balance, full ledger, withdrawal history,
    and outstanding (unsettled) cash commission still owed to the platform."""
    return await service.get_facility_earnings_admin(db, facility_id)


@router.get("/facilities/{facility_id}/dashboard", response_model=FacilityDashboardOut)
async def facility_dashboard_admin(
    facility_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
):
    """One-stop overview for a facility's admin detail page: profile,
    doctors, booking stats by status, revenue/commission, rating, and
    current earning balance."""
    return await service.get_facility_dashboard_admin(db, facility_id)


# ============================================================================
# USER DRILL-DOWN (Admin + SuperAdmin)
# ============================================================================

@router.get("/users/{user_id}/bookings", response_model=list[BookingOut])
async def user_bookings_admin(
    user_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
):
    return await service.get_user_bookings_admin(db, user_id)


@router.get("/users/{user_id}/reviews", response_model=list[ReviewOut])
async def user_reviews_admin(
    user_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
):
    return await service.get_user_reviews_admin(db, user_id)


@router.get("/users/{user_id}/rewards", response_model=UserRewardsOut)
async def user_rewards_admin(
    user_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
):
    return await service.get_user_rewards_admin(db, user_id)


@router.get("/users/{user_id}/dashboard", response_model=UserDashboardOut)
async def user_dashboard_admin(
    user_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
):
    """One-stop overview for a user's admin detail page: profile, booking
    stats, spend, reward balance, review/favorite counts, and (for
    merchants) how many facilities they own."""
    return await service.get_user_dashboard_admin(db, user_id)
