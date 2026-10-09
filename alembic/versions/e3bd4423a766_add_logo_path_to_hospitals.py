"""add_logo_path_to_hospitals

Revision ID: e3bd4423a766
Revises: e7f8a9b0c1d2
Create Date: 2026-10-07 12:49:18.811912

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = 'e3bd4423a766'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('hospitals', sa.Column('logo_path', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('hospitals', 'logo_path')
