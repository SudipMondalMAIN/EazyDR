import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.admin import service
from app.modules.admin.schemas import (
    AnalyticsSummaryOut,
    AuditLogOut,
    BookingExportFilter,
    FacilityPricingUpdate,
    FacilityVerifyUpdate,
)
from app.modules.auth.dependencies import require_admin, require_superadmin
from app.modules.auth.models import User
from app.modules.bookings.models import BookingStatus
from app.modules.facilities.schemas import FacilityOut

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
