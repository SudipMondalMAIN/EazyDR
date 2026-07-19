import uuid

from pydantic import BaseModel

from app.modules.favorites.models import FavoriteTargetType


class FavoriteCreate(BaseModel):
    target_type: FavoriteTargetType
    target_id: uuid.UUID


class FavoriteOut(BaseModel):
    id: uuid.UUID
    target_type: FavoriteTargetType
    target_id: uuid.UUID
    # Resolved display fields, filled in by the service layer so the app
    # doesn't need a second round-trip per favorite just to show a name.
    name: str | None = None
    subtitle: str | None = None

    class Config:
        from_attributes = True
