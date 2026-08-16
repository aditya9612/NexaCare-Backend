"""add_soft_delete_to_purchases

Revision ID: 65c4e208c1be
Revises: b340001aad77
Create Date: 2026-08-07 16:32:58.080364

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = '65c4e208c1be'
down_revision: Union[str, None] = 'b340001aad77'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {
        column["name"]
        for column in inspector.get_columns("purchases")
    }

    if "is_deleted" not in columns:
        op.add_column(
            "purchases",
            sa.Column(
                "is_deleted",
                sa.Boolean(),
                nullable=False,
                server_default="0"
            )
        )
    if "deleted_at" not in columns:
        op.add_column(
            "purchases",
            sa.Column(
                "deleted_at",
                sa.DateTime(),
                nullable=True
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {
        column["name"]
        for column in inspector.get_columns("purchases")
    }

    if "is_deleted" in columns:
        op.drop_column("purchases", "is_deleted")
    if "deleted_at" in columns:
        op.drop_column("purchases", "deleted_at")
