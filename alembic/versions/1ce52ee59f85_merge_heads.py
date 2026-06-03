"""merge heads

Revision ID: 1ce52ee59f85
Revises: 3b601468c86f, 06b170ef9061
Create Date: 2026-06-03 10:54:44.438365

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = '1ce52ee59f85'
down_revision: Union[str, None] = ('3b601468c86f', '06b170ef9061')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
