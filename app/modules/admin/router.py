import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.admin import service
from app.modules.admin.schemas import (
    AnalyticsSummaryOut,
    AuditLogOut,
    FacilityPricingUpdate,
    FacilityVerifyUpdate,
)
from app.modules.auth.dependencies import require_admin, require_superadmin
from app.modules.auth.models import User
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
