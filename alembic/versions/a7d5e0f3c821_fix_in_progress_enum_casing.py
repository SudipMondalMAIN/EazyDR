"""fix in_progress enum casing on bookingstatus

Revision ID: a7d5e0f3c821
Revises: f2c8b6e91a3d
Create Date: 2026-07-27

The `bookingstatus` Postgres enum stores Python enum *member names*
(PENDING, CONFIRMED, CHECKED_IN, COMPLETED, CANCELLED, NO_SHOW) because
`mapped_column(Enum(BookingStatus))` has no `values_callable`, so
SQLAlchemy defaults to `.name`, not `.value`. A previous migration
(a24eeb0e7be0) added the new consultation status as lowercase
'in_progress' — matching the enum's *value*, not its *name* — so any row
actually set to IN_PROGRESS by application code writes/reads
'IN_PROGRESS' and there was no such label, breaking every query that
touches a row in that state (e.g. GET /bookings/my).

This adds the correctly-cased 'IN_PROGRESS' label and repoints any row
that got stuck as the old mis-cased 'in_progress' onto it. The old
lowercase label is left in the enum type afterwards (Postgres cannot
drop enum values) but should never be written again.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "a7d5e0f3c821"
down_revision = "f2c8b6e91a3d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside the same transaction as
    # code that uses the new value, so it needs its own autocommit block.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE bookingstatus ADD VALUE IF NOT EXISTS 'IN_PROGRESS'")

    op.execute(
        "UPDATE bookings SET status = 'IN_PROGRESS' WHERE status = 'in_progress'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE bookings SET status = 'in_progress' WHERE status = 'IN_PROGRESS'"
    )
    # Postgres cannot drop enum values — 'IN_PROGRESS' stays in the type.
