"""fix departments legacy columns

Revision ID: 44f92674840d
Revises: 484efc1c89dd
Create Date: 2026-06-30 15:47:49.684217
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "44f92674840d"
down_revision: Union[str, None] = "484efc1c89dd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    if _has_column("departments", "name") and not _has_column("departments", "department_name"):
        op.alter_column(
            "departments",
            "name",
            new_column_name="department_name",
            existing_type=sa.String(length=100),
            existing_nullable=False,
        )
    if _has_column("departments", "id") and _has_column("departments", "department_id"):
        op.execute("UPDATE departments SET department_id = id WHERE department_id IS NULL")
    


def downgrade() -> None:
    pass