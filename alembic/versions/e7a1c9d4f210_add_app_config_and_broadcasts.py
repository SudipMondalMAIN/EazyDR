"""add app_config and notification_broadcasts tables

Revision ID: e7a1c9d4f210
Revises: b3f1c9a7d2e4
Create Date: 2026-07-26

Adds the `app_config` single-row table (bottom nav, theme, force-update
version gate) and `notification_broadcasts` (history of admin-sent custom
notifications). See app/modules/app_config/.

Chained onto b3f1c9a7d2e4 (add_online_payment_settled_to_bookings), the
current head of this repo's migration chain.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "e7a1c9d4f210"
down_revision = "b3f1c9a7d2e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_config",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("nav_config", sa.JSON(), nullable=False),
        sa.Column("theme_mode", sa.String(length=10), nullable=False, server_default="light"),
        sa.Column("primary_color", sa.String(length=20), nullable=False, server_default="#0A84FF"),
        sa.Column("secondary_color", sa.String(length=20), nullable=False, server_default="#34C759"),
        sa.Column("min_app_version", sa.String(length=20), nullable=False, server_default="1.0.0"),
        sa.Column("force_update", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "update_message", sa.String(length=500), nullable=False,
            server_default="A new version is available. Please update to continue.",
        ),
    )

    op.create_table(
        "notification_broadcasts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=150), nullable=False),
        sa.Column("body", sa.String(length=1000), nullable=False),
        sa.Column("recipients_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("push_success_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_notification_broadcasts_actor_user_id", "notification_broadcasts", ["actor_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_notification_broadcasts_actor_user_id", table_name="notification_broadcasts")
    op.drop_table("notification_broadcasts")
    op.drop_table("app_config")