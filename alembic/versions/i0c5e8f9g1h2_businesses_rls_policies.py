"""businesses: RLS policies for authenticated (iOS) upserts

Revision ID: i0c5e8f9g1h2
Revises: h9b2d6e7f8g0
Create Date: 2026-02-01

Enables RLS on public.businesses (if not already) and adds policies so
authenticated users (e.g. mobile app with anon key + JWT) can SELECT, INSERT,
and UPDATE. Fixes "new row violates row-level security policy" when the iOS
app upserts Google Places businesses.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "i0c5e8f9g1h2"
down_revision: Union[str, None] = "h9b2d6e7f8g0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Policy names we create; drop before create so migration is idempotent.
POLICY_NAMES = (
    "businesses_select_authenticated",
    "businesses_insert_authenticated",
    "businesses_update_authenticated",
)


def upgrade() -> None:
    conn = op.get_bind()
    # Enable RLS (idempotent).
    conn.execute(sa.text("ALTER TABLE public.businesses ENABLE ROW LEVEL SECURITY"))
    # Drop our policies if they exist so we can re-run safely.
    for name in POLICY_NAMES:
        conn.execute(sa.text(f'DROP POLICY IF EXISTS "{name}" ON public.businesses'))
    # Allow authenticated users to read all businesses.
    conn.execute(
        sa.text(
            """
            CREATE POLICY businesses_select_authenticated
            ON public.businesses
            FOR SELECT
            TO authenticated
            USING (true)
            """
        )
    )
    # Allow authenticated users to insert (e.g. iOS Google Places upsert).
    conn.execute(
        sa.text(
            """
            CREATE POLICY businesses_insert_authenticated
            ON public.businesses
            FOR INSERT
            TO authenticated
            WITH CHECK (true)
            """
        )
    )
    # Allow authenticated users to update (e.g. refresh rating, photo_url, price_level).
    conn.execute(
        sa.text(
            """
            CREATE POLICY businesses_update_authenticated
            ON public.businesses
            FOR UPDATE
            TO authenticated
            USING (true)
            WITH CHECK (true)
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    for name in POLICY_NAMES:
        conn.execute(sa.text(f'DROP POLICY IF EXISTS "{name}" ON public.businesses'))
    # Do not disable RLS; other systems may rely on it.
