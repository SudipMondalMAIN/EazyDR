"""add facility profile fields (phone, email, description, working_hours)

Revision ID: 147bf7719b77
Revises: df384a96bb45
Create Date: 2026-07-24

Adds editable profile columns to `facilities` needed for merchant
self-service facility/profile management (name/address were already
editable at the DB level; phone/email/description/working_hours were
missing entirely).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "147bf7719b77"
down_revision = "df384a96bb45"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("facilities", sa.Column("phone", sa.String(length=15), nullable=True))
    op.add_column("facilities", sa.Column("email", sa.String(length=255), nullable=True))
    op.add_column("facilities", sa.Column("description", sa.String(length=2000), nullable=True))
    op.add_column("facilities", sa.Column("working_hours", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("facilities", "working_hours")
    op.drop_column("facilities", "description")
    op.drop_column("facilities", "email")
    op.drop_column("facilities", "phone")
