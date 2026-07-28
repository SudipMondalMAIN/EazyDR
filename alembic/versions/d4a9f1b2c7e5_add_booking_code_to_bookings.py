"""add booking_code to bookings

Human-facing booking identifier shown in the app instead of the raw UUID
`id` — format EZD{YY}{MM}{DD}{SEQ:05d}, e.g. "EZD26072800001" for the 1st
booking created on 2026-07-28. Backfills existing rows with codes derived
from their `created_at` date (in Asia/Kolkata), numbered in creation order
within each day, before making the column NOT NULL + UNIQUE.

Revision ID: d4a9f1b2c7e5
Revises: c1d2e3f4a5b6
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d4a9f1b2c7e5"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bookings", sa.Column("booking_code", sa.String(length=20), nullable=True))

    # Backfill: for each existing booking, derive the code from its
    # created_at date (converted to Asia/Kolkata, matching how the app
    # generates codes for new bookings) and a per-day sequence in
    # creation order. Done in raw SQL so it works regardless of row count.
    op.execute(
        """
        WITH numbered AS (
            SELECT
                id,
                'EZD' || to_char(created_at AT TIME ZONE 'Asia/Kolkata', 'YYMMDD')
                    || lpad(
                        ROW_NUMBER() OVER (
                            PARTITION BY to_char(created_at AT TIME ZONE 'Asia/Kolkata', 'YYMMDD')
                            ORDER BY created_at, id
                        )::text, 5, '0'
                    ) AS new_code
            FROM bookings
        )
        UPDATE bookings
        SET booking_code = numbered.new_code
        FROM numbered
        WHERE bookings.id = numbered.id
        """
    )

    op.alter_column("bookings", "booking_code", nullable=False)
    op.create_unique_constraint("uq_bookings_booking_code", "bookings", ["booking_code"])
    op.create_index("ix_bookings_booking_code", "bookings", ["booking_code"])


def downgrade() -> None:
    op.drop_index("ix_bookings_booking_code", table_name="bookings")
    op.drop_constraint("uq_bookings_booking_code", "bookings", type_="unique")
    op.drop_column("bookings", "booking_code")
