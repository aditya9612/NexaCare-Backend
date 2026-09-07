"""merge main and faq-ai heads

Revision ID: c2454a050e1c
Revises: 405fd210ac69, 6e628fdd70ba
Create Date: 2026-09-07 11:49:47.292010

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = 'c2454a050e1c'
down_revision: Union[str, None] = ('405fd210ac69', '6e628fdd70ba')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
