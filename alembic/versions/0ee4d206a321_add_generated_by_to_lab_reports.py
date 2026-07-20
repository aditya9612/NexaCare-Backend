"""add generated_by to lab_reports

Revision ID: 0ee4d206a321
Revises: b62b952f14aa
Create Date: 2026-07-08 23:44:25.856023

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0ee4d206a321"
down_revision: Union[str, None] = "b62b952f14aa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lab_reports",
        sa.Column("generated_by", sa.Integer(), nullable=True),
    )

    op.create_foreign_key(
        "fk_lab_reports_generated_by_users",
        "lab_reports",
        "users",
        ["generated_by"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_lab_reports_generated_by_users",
        "lab_reports",
        type_="foreignkey",
    )

    op.drop_column("lab_reports", "generated_by")