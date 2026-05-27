"""link_doctors_to_departments

Revision ID: faa8a81398d2
Revises: 519ed7d6166e
Create Date: 2026-05-27 17:58:50.767211

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from sqlalchemy.dialects import mysql

revision: str = 'faa8a81398d2'
down_revision: Union[str, None] = '519ed7d6166e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

