"""add_nurse_code_and_updated_at

Revision ID: c91f3e8d2a01
Revises: b4748dec82be
Create Date: 2026-05-27 18:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c91f3e8d2a01'
down_revision: Union[str, None] = 'b4748dec82be'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add nurse_code column (unique, indexed)
    op.add_column('nurses', sa.Column('nurse_code', sa.String(50), nullable=True))
    op.create_unique_constraint('uq_nurses_nurse_code', 'nurses', ['nurse_code'])
    op.create_index('ix_nurses_nurse_code', 'nurses', ['nurse_code'], unique=True)

    # Populate existing rows with a generated nurse_code
    op.execute(
        "UPDATE nurses SET nurse_code = CONCAT('NRS-', DATE_FORMAT(NOW(), '%Y%m%d'), SUBSTRING(MD5(RAND()), 1, 6)) WHERE nurse_code IS NULL"
    )

    # Make nurse_code NOT NULL after backfilling
    op.alter_column('nurses', 'nurse_code', nullable=False, existing_type=sa.String(50))

    # Add updated_at column if it doesn't exist yet
    op.add_column('nurses', sa.Column('updated_at', sa.DateTime(), nullable=True))
    op.execute("UPDATE nurses SET updated_at = created_at WHERE updated_at IS NULL")
    op.alter_column('nurses', 'updated_at', nullable=False, existing_type=sa.DateTime())


def downgrade() -> None:
    op.drop_index('ix_nurses_nurse_code', table_name='nurses')
    op.drop_constraint('uq_nurses_nurse_code', 'nurses', type_='unique')
    op.drop_column('nurses', 'nurse_code')
    op.drop_column('nurses', 'updated_at')
