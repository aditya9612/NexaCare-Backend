"""add is_active to expense_categories

Revision ID: 54940cc7f704
Revises: 2446367a2858
Create Date: 2026-07-08 18:52:30.701593

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

from sqlalchemy.dialects import mysql

revision: str = '54940cc7f704'
down_revision: Union[str, None] = '2446367a2858'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {
        column["name"]
        for column in inspector.get_columns("expense_categories")
    }

    if "is_active" not in columns:
        op.add_column(
            "expense_categories",
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default="1"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {
        column["name"]
        for column in inspector.get_columns("expense_categories")
    }

    if "is_active" in columns:
        op.drop_column("expense_categories", "is_active")
