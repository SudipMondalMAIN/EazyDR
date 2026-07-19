import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import require_patient
from app.modules.auth.models import User
from app.modules.favorites import service
from app.modules.favorites.schemas import FavoriteCreate, FavoriteOut

router = APIRouter(prefix="/api/v1/favorites", tags=["favorites"])


@router.post("", response_model=FavoriteOut, status_code=201)
async def add_favorite(
    payload: FavoriteCreate, db: AsyncSession = Depends(get_db), user: User = Depends(require_patient)
):
    favorite = await service.add_favorite(db, user.id, payload)
    return FavoriteOut(id=favorite.id, target_type=favorite.target_type, target_id=favorite.target_id)


@router.get("/me", response_model=list[FavoriteOut])
async def my_favorites(db: AsyncSession = Depends(get_db), user: User = Depends(require_patient)):
    return await service.list_favorites_for_user(db, user.id)


@router.delete("/{favorite_id}", status_code=204)
async def remove_favorite(
    favorite_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_patient)
):
    await service.remove_favorite(db, user.id, favorite_id)
