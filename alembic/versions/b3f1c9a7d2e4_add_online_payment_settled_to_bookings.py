"""add online_payment_settled to bookings

Revision ID: b3f1c9a7d2e4
Revises:
Create Date: 2026-07-24

Adds `online_payment_settled` to `bookings` so online (gateway) payments
have their own settlement flag, mirroring `cash_commission_settled` for
cash bookings. This keeps cash and online settlement tracked separately
and prevents an online booking's facility-earning credit from being
applied more than once.

NOTE: `down_revision` is left as None to match the existing migrations in
this repo (none of them chain off a prior revision yet). If you already
have an earlier revision applied to your database, update `down_revision`
below to point to it before running `alembic upgrade head`.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b3f1c9a7d2e4"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bookings",
        sa.Column("online_payment_settled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("bookings", "online_payment_settled")
