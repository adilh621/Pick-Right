"""businesses: add photo_reference and photo_url

Revision ID: k2e7g1h3i4j5
Revises: j1d6f0g2h3i4
Create Date: 2026-02-08

Adds nullable photo_reference and photo_url so home-feed cards show images
without requiring the user to tap into details first.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "k2e7g1h3i4j5"
down_revision: Union[str, None] = "j1d6f0g2h3i4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("businesses")}

    if "photo_reference" not in cols:
        op.add_column(
            "businesses",
            sa.Column("photo_reference", sa.String(), nullable=True),
        )

    if "photo_url" not in cols:
        op.add_column(
            "businesses",
            sa.Column("photo_url", sa.String(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("businesses")}

    if "photo_url" in cols:
        op.drop_column("businesses", "photo_url")

    if "photo_reference" in cols:
        op.drop_column("businesses", "photo_reference")
