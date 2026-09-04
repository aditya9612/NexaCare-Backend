"""merge migration heads

Revision ID: 405fd210ac69
Revises: 511be8fa0047, 9c2d3e4f5a6b
Create Date: 2026-09-02 12:19:08.420175

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = '405fd210ac69'
down_revision: Union[str, None] = ('511be8fa0047', '9c2d3e4f5a6b')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
