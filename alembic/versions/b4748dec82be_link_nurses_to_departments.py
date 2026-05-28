"""link_nurses_to_departments

Revision ID: b4748dec82be
Revises: faa8a81398d2
Create Date: 2026-05-27 18:03:39.329108

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from sqlalchemy.dialects import mysql

revision: str = 'b4748dec82be'
down_revision: Union[str, None] = 'faa8a81398d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
