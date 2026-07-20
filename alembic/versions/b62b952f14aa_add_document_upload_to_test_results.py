"""add_document_upload_to_test_results

Revision ID: b62b952f14aa
Revises: 38c1d7274a68
Create Date: 2026-07-06 09:54:03.145158

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b62b952f14aa"
down_revision: Union[str, None] = "38c1d7274a68"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "test_results",
        sa.Column("document_url", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("test_results", "document_url")