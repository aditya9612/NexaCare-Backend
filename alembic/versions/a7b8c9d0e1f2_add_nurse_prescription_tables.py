"""add_nurse_prescription_tables

Revision ID: a7b8c9d0e1f2
Revises: 292b3968f22a
Create Date: 2026-07-08 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "292b3968f22a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "nurse_prescriptions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("doctor_id", sa.Integer(), nullable=False),
        sa.Column("medicine_name", sa.String(length=255), nullable=False),
        sa.Column("dosage", sa.String(length=255), nullable=False),
        sa.Column("frequency", sa.String(length=255), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("meal_timing", sa.String(length=50), nullable=False),
        sa.Column("time_of_day", sa.Text(), nullable=True),
        sa.Column("times", sa.Text(), nullable=True),
        sa.Column("duration_value", sa.String(length=50), nullable=True),
        sa.Column("duration_unit", sa.String(length=50), nullable=True),
        sa.Column("special_instructions", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["doctor_id"], ["doctors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_nurse_prescriptions_created_at"),
        "nurse_prescriptions",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_nurse_prescriptions_doctor_id"),
        "nurse_prescriptions",
        ["doctor_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_nurse_prescriptions_id"), "nurse_prescriptions", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_nurse_prescriptions_patient_id"),
        "nurse_prescriptions",
        ["patient_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_nurse_prescriptions_status"),
        "nurse_prescriptions",
        ["status"],
        unique=False,
    )

    op.create_table(
        "nurse_medication_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("prescription_id", sa.Integer(), nullable=False),
        sa.Column("nurse_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("time_of_day_slot", sa.String(length=50), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["nurse_id"], ["nurses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["prescription_id"], ["nurse_prescriptions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_nurse_medication_logs_created_at"),
        "nurse_medication_logs",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_nurse_medication_logs_id"), "nurse_medication_logs", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_nurse_medication_logs_nurse_id"),
        "nurse_medication_logs",
        ["nurse_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_nurse_medication_logs_prescription_id"),
        "nurse_medication_logs",
        ["prescription_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_nurse_medication_logs_status"),
        "nurse_medication_logs",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_nurse_medication_logs_timestamp"),
        "nurse_medication_logs",
        ["timestamp"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_nurse_medication_logs_timestamp"), table_name="nurse_medication_logs"
    )
    op.drop_index(
        op.f("ix_nurse_medication_logs_status"), table_name="nurse_medication_logs"
    )
    op.drop_index(
        op.f("ix_nurse_medication_logs_prescription_id"),
        table_name="nurse_medication_logs",
    )
    op.drop_index(
        op.f("ix_nurse_medication_logs_nurse_id"), table_name="nurse_medication_logs"
    )
    op.drop_index(op.f("ix_nurse_medication_logs_id"), table_name="nurse_medication_logs")
    op.drop_index(
        op.f("ix_nurse_medication_logs_created_at"), table_name="nurse_medication_logs"
    )
    op.drop_table("nurse_medication_logs")

    op.drop_index(op.f("ix_nurse_prescriptions_status"), table_name="nurse_prescriptions")
    op.drop_index(
        op.f("ix_nurse_prescriptions_patient_id"), table_name="nurse_prescriptions"
    )
    op.drop_index(op.f("ix_nurse_prescriptions_id"), table_name="nurse_prescriptions")
    op.drop_index(
        op.f("ix_nurse_prescriptions_doctor_id"), table_name="nurse_prescriptions"
    )
    op.drop_index(
        op.f("ix_nurse_prescriptions_created_at"), table_name="nurse_prescriptions"
    )
    op.drop_table("nurse_prescriptions")
