"""add meal_timing and time_of_day to prescription_items

Revision ID: f1a2b3c4d5e6
Revises: e7f8a9b0c1d2
Create Date: 2026-10-07 12:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("prescription_items")]
    if "meal_timing" not in columns:
        op.add_column("prescription_items", sa.Column("meal_timing", sa.String(length=50), nullable=True))
    if "time_of_day" not in columns:
        op.add_column("prescription_items", sa.Column("time_of_day", sa.String(length=50), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("prescription_items")]
    if "time_of_day" in columns:
        op.drop_column("prescription_items", "time_of_day")
    if "meal_timing" in columns:
        op.drop_column("prescription_items", "meal_timing")
