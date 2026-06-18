"""Merge heads 842a57bf1313 and e8f4a2b1c903

Revision ID: 98c954715cb0
Revises: 842a57bf1313, e8f4a2b1c903
Create Date: 2026-06-18 11:56:26.531441

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = '98c954715cb0'
down_revision: Union[str, None] = ('842a57bf1313', 'e8f4a2b1c903')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
