"""business_chat_messages table

Revision ID: h9b2d6e7f8g0
Revises: g8a1c4d5e6f7
Create Date: 2026-02-01

Adds business_chat_messages table for conversation history between
user and AI about a specific business (user_id, business_id, role, content, created_at).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "h9b2d6e7f8g0"
down_revision: Union[str, None] = "g8a1c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "business_chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
    )
    op.create_index(
        "ix_business_chat_messages_user_id",
        "business_chat_messages",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_business_chat_messages_business_id",
        "business_chat_messages",
        ["business_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_business_chat_messages_business_id", table_name="business_chat_messages")
    op.drop_index("ix_business_chat_messages_user_id", table_name="business_chat_messages")
    op.drop_table("business_chat_messages")
