"""merge migration heads

Revision ID: e2d7635c10aa
Revises: 6649f4fddb98, d4e5f6a7b8c9
Create Date: 2026-08-17 12:49:27.208418

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = 'e2d7635c10aa'
down_revision: Union[str, None] = ('6649f4fddb98', 'd4e5f6a7b8c9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
