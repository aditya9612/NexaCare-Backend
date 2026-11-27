"""add_emergency_alert_status_and_ack

Revision ID: 3bbe62a6935a
Revises: 9f8e7d6c5b4a
Create Date: 2026-11-26 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3bbe62a6935a"
down_revision: Union[str, None] = "9f8e7d6c5b4a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    ea_columns = [c["name"] for c in inspector.get_columns("emergency_alerts")]
    ea_indexes = [idx["name"] for idx in inspector.get_indexes("emergency_alerts")]

    if "status" not in ea_columns:
        op.add_column(
            "emergency_alerts",
            sa.Column("status", sa.String(length=50), server_default="pending", nullable=False),
        )
    if "ix_emergency_alerts_status" not in ea_indexes:
        op.create_index("ix_emergency_alerts_status", "emergency_alerts", ["status"])

    if "acknowledged_at" not in ea_columns:
        op.add_column(
            "emergency_alerts",
            sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        )

    if "acknowledged_by" not in ea_columns:
        op.add_column(
            "emergency_alerts",
            sa.Column(
                "acknowledged_by",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    if "ix_emergency_alerts_acknowledged_by" not in ea_indexes:
        op.create_index("ix_emergency_alerts_acknowledged_by", "emergency_alerts", ["acknowledged_by"])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    ea_columns = [c["name"] for c in inspector.get_columns("emergency_alerts")]
    ea_indexes = [idx["name"] for idx in inspector.get_indexes("emergency_alerts")]

    if "ix_emergency_alerts_acknowledged_by" in ea_indexes:
        op.drop_index("ix_emergency_alerts_acknowledged_by", table_name="emergency_alerts")
    if "acknowledged_by" in ea_columns:
        op.drop_column("emergency_alerts", "acknowledged_by")

    if "acknowledged_at" in ea_columns:
        op.drop_column("emergency_alerts", "acknowledged_at")

    if "ix_emergency_alerts_status" in ea_indexes:
        op.drop_index("ix_emergency_alerts_status", table_name="emergency_alerts")
    if "status" in ea_columns:
        op.drop_column("emergency_alerts", "status")

