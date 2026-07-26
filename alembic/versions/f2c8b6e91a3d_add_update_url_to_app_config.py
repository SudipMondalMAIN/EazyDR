"""add update_url to app_config

Revision ID: f2c8b6e91a3d
Revises: e7a1c9d4f210
Create Date: 2026-07-27

Adds `update_url` to `app_config` — the Play Store / App Store link the
force-update screen's "Update Now" button opens. Blank means the button
stays hidden client-side. See app/modules/app_config/.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f2c8b6e91a3d"
down_revision = "e7a1c9d4f210"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_config",
        sa.Column("update_url", sa.String(length=500), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("app_config", "update_url")
