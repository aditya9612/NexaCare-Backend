"""create_departments_table

Revision ID: 519ed7d6166e
Revises: 
Create Date: 2026-05-27 17:28:59.539906

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from sqlalchemy.dialects import mysql

revision: str = '519ed7d6166e'
down_revision: Union[str, None] = '180acdfb2046'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

