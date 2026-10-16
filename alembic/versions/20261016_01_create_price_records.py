"""Create price_records table.

Revision ID: 20261016_01
Revises:
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261016_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "price_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("price", sa.Numeric(precision=28, scale=10), nullable=False),
        sa.Column("timestamp", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_price_records_ticker_timestamp",
        "price_records",
        ["ticker", "timestamp"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_price_records_ticker_timestamp",
        table_name="price_records",
    )
    op.drop_table("price_records")
