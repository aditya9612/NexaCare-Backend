"""add batch_number_to_medicines

Revision ID: 2f49ae75d53f
Revises: 292b3968f22a
Create Date: 2026-06-29 12:14:35.800391

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = '2f49ae75d53f'
down_revision: Union[str, None] = '292b3968f22a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
    "medicines",
    sa.Column("batch_number", sa.String(length=100), nullable=True)
)


def downgrade() -> None:
        op.drop_column("medicines", "batch_number")
        
    
