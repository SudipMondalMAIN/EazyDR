import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.modules.facilities.service import get_doctor, get_facility
from app.modules.favorites.models import Favorite, FavoriteTargetType
from app.modules.favorites.schemas import FavoriteCreate, FavoriteOut


async def add_favorite(db: AsyncSession, user_id: uuid.UUID, payload: FavoriteCreate) -> Favorite:
    # Confirms the target actually exists (raises NotFoundError otherwise)
    # before saving a favorite that would otherwise dangle.
    if payload.target_type == FavoriteTargetType.DOCTOR:
        await get_doctor(db, payload.target_id)
    else:
        await get_facility(db, payload.target_id)

    favorite = Favorite(user_id=user_id, target_type=payload.target_type, target_id=payload.target_id)
    db.add(favorite)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ConflictError("Already in your favorites")
    await db.refresh(favorite)
    return favorite


async def remove_favorite(db: AsyncSession, user_id: uuid.UUID, favorite_id: uuid.UUID) -> None:
    result = await db.execute(select(Favorite).where(Favorite.id == favorite_id))
    favorite = result.scalar_one_or_none()
    if not favorite:
        raise NotFoundError("Favorite not found")
    if favorite.user_id != user_id:
        raise ForbiddenError("Not your favorite")
    await db.delete(favorite)
    await db.commit()


async def list_favorites_for_user(db: AsyncSession, user_id: uuid.UUID) -> list[FavoriteOut]:
    result = await db.execute(
        select(Favorite).where(Favorite.user_id == user_id).order_by(Favorite.created_at.desc())
    )
    favorites = list(result.scalars().all())

    out: list[FavoriteOut] = []
    for fav in favorites:
        name, subtitle = None, None
        try:
            if fav.target_type == FavoriteTargetType.DOCTOR:
                doctor = await get_doctor(db, fav.target_id)
                name, subtitle = doctor.full_name, doctor.specialty
            else:
                facility = await get_facility(db, fav.target_id)
                name, subtitle = facility.name, facility.city
        except NotFoundError:
            # Target was deleted after being favorited — still show the
            # favorite row (client can offer to remove it) rather than
            # failing the whole list.
            name, subtitle = None, None

        out.append(
            FavoriteOut(id=fav.id, target_type=fav.target_type, target_id=fav.target_id, name=name, subtitle=subtitle)
        )
    return out
