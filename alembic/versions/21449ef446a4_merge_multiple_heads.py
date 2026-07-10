"""merge_multiple_heads

Revision ID: 21449ef446a4
Revises: 0ee4d206a321, 54940cc7f704
Create Date: 2026-07-10 10:57:19.903895

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = '21449ef446a4'
down_revision: Union[str, None] = ('0ee4d206a321', '54940cc7f704')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
