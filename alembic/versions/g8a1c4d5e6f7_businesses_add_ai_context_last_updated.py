"""businesses: add ai_context_last_updated

Revision ID: g8a1c4d5e6f7
Revises: f7b0c3d4e5f6
Create Date: 2026-02-01

Adds nullable ai_context_last_updated (TIMESTAMP WITH TIME ZONE) for TTL
on when to regenerate Business.ai_context (e.g. 24h).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g8a1c4d5e6f7"
down_revision: Union[str, None] = "f7b0c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "businesses",
        sa.Column("ai_context_last_updated", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("businesses", "ai_context_last_updated")
