"""add_patient_vitals_table

Revision ID: e4a1b2c3d4e5
Revises: d37ebcb2dc69
Create Date: 2026-06-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4a1b2c3d4e5"
down_revision: Union[str, None] = "d37ebcb2dc69"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "patient_vitals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("nurse_id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("blood_pressure", sa.String(length=20), nullable=False),
        sa.Column("pulse_rate", sa.Integer(), nullable=False),
        sa.Column("oxygen_saturation", sa.Float(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["nurse_id"], ["nurses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_patient_vitals_id"), "patient_vitals", ["id"], unique=False)
    op.create_index(op.f("ix_patient_vitals_nurse_id"), "patient_vitals", ["nurse_id"], unique=False)
    op.create_index(
        op.f("ix_patient_vitals_patient_id"), "patient_vitals", ["patient_id"], unique=False
    )
    op.create_index(
        op.f("ix_patient_vitals_recorded_at"), "patient_vitals", ["recorded_at"], unique=False
    )
    op.create_index(
        op.f("ix_patient_vitals_created_at"), "patient_vitals", ["created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_patient_vitals_created_at"), table_name="patient_vitals")
    op.drop_index(op.f("ix_patient_vitals_recorded_at"), table_name="patient_vitals")
    op.drop_index(op.f("ix_patient_vitals_patient_id"), table_name="patient_vitals")
    op.drop_index(op.f("ix_patient_vitals_nurse_id"), table_name="patient_vitals")
    op.drop_index(op.f("ix_patient_vitals_id"), table_name="patient_vitals")
    op.drop_table("patient_vitals")
