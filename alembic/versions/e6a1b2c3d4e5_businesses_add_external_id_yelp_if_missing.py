"""businesses: add external_id_yelp if missing

Revision ID: e6a1b2c3d4e5
Revises: d5f9a2c3e1b4
Create Date: 2026-02-01

Adds external_id_yelp column and index if they do not exist (e.g. DB created
without running initial schema or column was dropped). Uses IF NOT EXISTS
so safe to run on DBs that already have the column.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e6a1b2c3d4e5"
down_revision: Union[str, None] = "d5f9a2c3e1b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    # PostgreSQL: add column only if it doesn't exist
    conn.execute(
        sa.text(
            "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS external_id_yelp VARCHAR"
        )
    )
    # Create index only if it doesn't exist (ignore error if exists)
    conn.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS ix_businesses_external_id_yelp
            ON businesses (external_id_yelp)
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_businesses_external_id_yelp"), table_name="businesses"
    )
    op.drop_column("businesses", "external_id_yelp")
