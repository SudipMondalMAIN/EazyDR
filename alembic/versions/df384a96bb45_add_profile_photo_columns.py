"""add profile photo columns to users and facilities

Revision ID: df384a96bb45
Revises:
Create Date: 2026-07-19

Adds photo_storage_key to `users` (patient/merchant/admin profile photo)
and to `facilities` (merchant/pharmacy/chamber photo). `doctors` already
had this column.

NOTE: `down_revision` is left as None because no prior migration exists
in this repo yet. If you already have an earlier revision applied to
your database, update `down_revision` below to point to it before
running `alembic upgrade head`.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "df384a96bb45"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("photo_storage_key", sa.String(length=255), nullable=True))
    op.add_column("facilities", sa.Column("photo_storage_key", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("facilities", "photo_storage_key")
    op.drop_column("users", "photo_storage_key")
