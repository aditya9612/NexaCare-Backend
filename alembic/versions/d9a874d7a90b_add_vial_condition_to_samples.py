"""add vial_condition to samples

Revision ID: d9a874d7a90b
Revises: 3bbe62a6935a
Create Date: 2026-11-28 15:59:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd9a874d7a90b'
down_revision: Union[str, None] = '3bbe62a6935a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("samples", sa.Column("vial_condition", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("samples", "vial_condition")

