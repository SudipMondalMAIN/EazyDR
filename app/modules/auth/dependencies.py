from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import ForbiddenError, UnauthorizedError
from app.core.database import get_db
from app.core.security import decode_token
from app.modules.auth.models import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not token:
        raise UnauthorizedError("Missing access token")
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise UnauthorizedError("Invalid or expired token")

    result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise UnauthorizedError("User not found or disabled")
    return user


def require_roles(*roles: UserRole):
    async def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise ForbiddenError(f"Requires one of roles: {[r.value for r in roles]}")
        return user

    return _dep


require_patient = require_roles(UserRole.PATIENT)
require_merchant = require_roles(UserRole.MERCHANT)
require_admin = require_roles(UserRole.ADMIN, UserRole.SUPERADMIN)
require_superadmin = require_roles(UserRole.SUPERADMIN)
