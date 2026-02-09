"""businesses: add ai_tags (JSONB)

Revision ID: j1d6f0g2h3i4
Revises: i0c5e8f9g1h2
Create Date: 2026-02-08

Adds nullable ai_tags column for home feed sections (e.g. ["date-night", "coffee"]).
Idempotent: only adds column if missing; does not alter or drop existing data.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "j1d6f0g2h3i4"
down_revision: Union[str, None] = "i0c5e8f9g1h2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "businesses",
        sa.Column("ai_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("businesses", "ai_tags")
