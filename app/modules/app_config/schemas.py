import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class NavItem(BaseModel):
    key: str                       # stable identifier, e.g. "wallet"
    label: str                     # display name, e.g. "Rewards"
    icon: str                      # icon name the frontend's icon set understands
    order: int                     # render order, ascending
    visible: bool = True
    screen: str                    # route/screen name to open on tap


class NavConfigUpdate(BaseModel):
    nav_config: list[NavItem]


class ThemeConfigUpdate(BaseModel):
    theme_mode: str | None = Field(default=None, pattern="^(light|dark)$")
    primary_color: str | None = None
    secondary_color: str | None = None


class VersionControlUpdate(BaseModel):
    min_app_version: str | None = None
    force_update: bool | None = None
    update_message: str | None = None
    update_url: str | None = None


class AppConfigOut(BaseModel):
    nav_config: list[NavItem]
    theme_mode: str
    primary_color: str
    secondary_color: str
    min_app_version: str
    force_update: bool
    update_message: str
    update_url: str

    class Config:
        from_attributes = True


class NotificationBroadcastCreate(BaseModel):
    title: str = Field(max_length=150)
    body: str = Field(max_length=1000)


class NotificationBroadcastOut(BaseModel):
    id: uuid.UUID
    title: str
    body: str
    recipients_count: int
    push_success_count: int
    created_at: datetime

    class Config:
        from_attributes = True
