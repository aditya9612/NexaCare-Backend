"""add collection date and volume to samples

Revision ID: 02bb5646252f
Revises: 44f92674840d
Create Date: 2026-07-01 09:58:42.032122

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = '02bb5646252f'
down_revision: Union[str, None] = '44f92674840d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("samples", sa.Column("collection_date", sa.DateTime(), nullable=True))
    op.add_column("samples", sa.Column("volume", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("samples", "volume")
    op.drop_column("samples", "collection_date")
