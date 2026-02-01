"""businesses: address, state, latitude, longitude, ai_notes

Revision ID: d5f9a2c3e1b4
Revises: c4e8f2a1b5d0
Create Date: 2026-02-01

Adds columns for Supabase/iOS alignment and AI chat context:
- address TEXT (nullable): full or primary address from Google Places
- state TEXT (nullable): state/region
- latitude DOUBLE PRECISION (nullable)
- longitude DOUBLE PRECISION (nullable)
- ai_notes TEXT (nullable): AI-generated summary for chat context (top items, halal notes, etc.)

Existing address_full, lat, lng remain for backward compatibility.
All new columns nullable; iOS will backfill from Google Places.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5f9a2c3e1b4"
down_revision: Union[str, None] = "c4e8f2a1b5d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("businesses", sa.Column("address", sa.Text(), nullable=True))
    op.add_column("businesses", sa.Column("state", sa.Text(), nullable=True))
    op.add_column("businesses", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("businesses", sa.Column("longitude", sa.Float(), nullable=True))
    op.add_column("businesses", sa.Column("ai_notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("businesses", "ai_notes")
    op.drop_column("businesses", "longitude")
    op.drop_column("businesses", "latitude")
    op.drop_column("businesses", "state")
    op.drop_column("businesses", "address")
