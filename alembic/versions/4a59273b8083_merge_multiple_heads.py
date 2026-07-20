"""merge_multiple_heads

Revision ID: 4a59273b8083
Revises: 0ee4d206a321, 54940cc7f704, d9144b0be309
Create Date: 2026-07-10 12:50:53.849195

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = '4a59273b8083'
down_revision: Union[str, None] = ('0ee4d206a321', '54940cc7f704')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
