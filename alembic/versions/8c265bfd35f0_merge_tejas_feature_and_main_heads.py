"""merge_tejas_feature_and_main_heads

Revision ID: 8c265bfd35f0
Revises: b8a7c6d5e4f3, e1a2b3c4d5e6
Create Date: 2026-11-24 10:07:32.070086

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = '8c265bfd35f0'
down_revision: Union[str, None] = ('b8a7c6d5e4f3', 'e1a2b3c4d5e6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
