"""add start_date to prescriptions

Revision ID: c8d1e2f3a4b5
Revises: e3bd4423a766
Create Date: 2026-10-24 12:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8d1e2f3a4b5"
down_revision: Union[str, None] = "e3bd4423a766"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("prescriptions")]
    if "start_date" not in columns:
        op.add_column("prescriptions", sa.Column("start_date", sa.Date(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("prescriptions")]
    if "start_date" in columns:
        op.drop_column("prescriptions", "start_date")
