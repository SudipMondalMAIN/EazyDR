"""add consultation fields and in_progress status to bookings

Revision ID: a24eeb0e7be0
Revises:
Create Date: 2026-07-24

Adds `consultation_started_at` / `consultation_completed_at` to `bookings`
and adds the `in_progress` value to the `bookingstatus` enum, for the
Start Consultation / Complete Consultation flow.

NOTE: `down_revision` is left as None to match the existing migrations in
this repo (none of them chain off a prior revision yet). If you already
have an earlier revision applied to your database, update `down_revision`
below to point to it before running `alembic upgrade head`.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a24eeb0e7be0"
down_revision = "147bf7719b77"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE bookingstatus ADD VALUE IF NOT EXISTS 'in_progress'")
    op.add_column(
        "bookings", sa.Column("consultation_started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "bookings", sa.Column("consultation_completed_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("bookings", "consultation_completed_at")
    op.drop_column("bookings", "consultation_started_at")
    # Postgres cannot drop a single enum value; leaving 'in_progress' in
    # place on downgrade is intentional (matches this repo's convention of
    # not attempting enum-value removal).
