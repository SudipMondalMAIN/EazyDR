"""add support chat tables (chat_sessions, chat_messages)

Revision ID: c1d2e3f4a5b6
Revises: a7d5e0f3c821
Create Date: 2026-07-28
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "c1d2e3f4a5b6"
down_revision = "a7d5e0f3c821"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE chatsessionstatus AS ENUM ('BOT', 'WAITING_AGENT', 'WITH_AGENT', 'CLOSED');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """))
    bind.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE chatlanguage AS ENUM ('ENGLISH', 'HINDI', 'BENGALI');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """))
    bind.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE chatsendertype AS ENUM ('USER', 'BOT', 'AGENT', 'SYSTEM');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """))

    chatsessionstatus = postgresql.ENUM(
        "BOT", "WAITING_AGENT", "WITH_AGENT", "CLOSED", name="chatsessionstatus", create_type=False
    )
    chatlanguage = postgresql.ENUM("ENGLISH", "HINDI", "BENGALI", name="chatlanguage", create_type=False)
    chatsendertype = postgresql.ENUM("USER", "BOT", "AGENT", "SYSTEM", name="chatsendertype", create_type=False)

    if not op.get_bind().dialect.has_table(op.get_bind(), "chat_sessions"):
        op.create_table(
            "chat_sessions",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("status", chatsessionstatus, nullable=False, server_default="BOT"),
            sa.Column("language", chatlanguage, nullable=False, server_default="ENGLISH"),
            sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("escalation_reason", sa.String(255), nullable=True),
        )
        op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])
        op.create_index("ix_chat_sessions_status", "chat_sessions", ["status"])

    if not op.get_bind().dialect.has_table(op.get_bind(), "chat_messages"):
        op.create_table(
            "chat_messages",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column(
                "session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chat_sessions.id"), nullable=False
            ),
            sa.Column("sender_type", chatsendertype, nullable=False),
            sa.Column("sender_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("text", sa.Text(), nullable=False),
        )
        op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_messages_session_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_sessions_status", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_user_id", table_name="chat_sessions")
    op.drop_table("chat_sessions")

    postgresql.ENUM(name="chatsendertype").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="chatlanguage").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="chatsessionstatus").drop(op.get_bind(), checkfirst=True)
