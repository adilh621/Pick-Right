"""users external_auth_uid UUID NOT NULL unique

Revision ID: c4e8f2a1b5d0
Revises: b121fc885833
Create Date: 2026-01-30

Enforces strict 1:1 between Supabase auth user (JWT sub) and public.users:
- external_auth_uid: cast to UUID, NOT NULL, unique constraint.
Assumes any orphan public.users rows have been removed and nulls backfilled.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c4e8f2a1b5d0"
down_revision: Union[str, None] = "b121fc885833"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop existing unique index so we can alter the column type
    op.drop_index(op.f("ix_users_external_auth_uid"), table_name="users")

    # Cast column to UUID and set NOT NULL (no nulls allowed; backfill done separately)
    op.alter_column(
        "users",
        "external_auth_uid",
        type_=postgresql.UUID(as_uuid=True),
        postgresql_using="external_auth_uid::uuid",
        existing_nullable=True,
        nullable=False,
    )

    # Named unique constraint and index for lookups
    op.create_unique_constraint(
        "uq_users_external_auth_uid",
        "users",
        ["external_auth_uid"],
    )
    op.create_index(
        op.f("ix_users_external_auth_uid"),
        "users",
        ["external_auth_uid"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_users_external_auth_uid"), table_name="users")
    op.drop_constraint("uq_users_external_auth_uid", "users", type_="unique")

    op.alter_column(
        "users",
        "external_auth_uid",
        type_=sa.String(),
        postgresql_using="external_auth_uid::text",
        existing_nullable=False,
        nullable=True,
    )

    op.create_index(
        op.f("ix_users_external_auth_uid"),
        "users",
        ["external_auth_uid"],
        unique=True,
    )
