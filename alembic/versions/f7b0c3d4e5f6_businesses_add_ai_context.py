"""businesses: add ai_context (JSONB)

Revision ID: f7b0c3d4e5f6
Revises: e6a1b2c3d4e5
Create Date: 2026-02-01

Adds nullable ai_context column for structured LLM snapshot / AI context
on business detail pages. No AI logic yet; column ready for future use.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f7b0c3d4e5f6"
down_revision: Union[str, None] = "e6a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "businesses",
        sa.Column("ai_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("businesses", "ai_context")
