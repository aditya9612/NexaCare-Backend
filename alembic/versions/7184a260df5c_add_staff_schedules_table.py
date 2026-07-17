"""Add staff_schedules table

Revision ID: 7184a260df5c
Revises: c4ae81de4724
Create Date: 2026-07-17 17:05:37.161735

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = '7184a260df5c'
down_revision: Union[str, None] = 'c4ae81de4724'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Add department_code to departments
    # ------------------------------------------------------------------
    op.add_column(
        "departments",
        sa.Column("department_code", sa.String(length=20), nullable=True),
    )
    op.create_index(
        op.f("ix_departments_department_code"),
        "departments",
        ["department_code"],
        unique=True,
    )

    # ------------------------------------------------------------------
    # Add remarks to lab_reports
    # ------------------------------------------------------------------
    op.add_column(
        "lab_reports",
        sa.Column("remarks", sa.Text(), nullable=True),
    )

    # ------------------------------------------------------------------
    # Create staff_schedules table
    # ------------------------------------------------------------------
    op.create_table(
        "staff_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("staff_id", sa.Integer(), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("slot_duration_minutes", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["staff_id"],
            ["staff.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        op.f("ix_staff_schedules_staff_id"),
        "staff_schedules",
        ["staff_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_staff_schedules_day_of_week"),
        "staff_schedules",
        ["day_of_week"],
        unique=False,
    )
    op.create_index(
        op.f("ix_staff_schedules_created_at"),
        "staff_schedules",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    # ------------------------------------------------------------------
    # Drop staff_schedules
    # ------------------------------------------------------------------
    op.drop_index(
        op.f("ix_staff_schedules_created_at"),
        table_name="staff_schedules",
    )
    op.drop_index(
        op.f("ix_staff_schedules_day_of_week"),
        table_name="staff_schedules",
    )
    op.drop_index(
        op.f("ix_staff_schedules_staff_id"),
        table_name="staff_schedules",
    )
    op.drop_table("staff_schedules")

    # ------------------------------------------------------------------
    # Remove remarks from lab_reports
    # ------------------------------------------------------------------
    op.drop_column("lab_reports", "remarks")

    # ------------------------------------------------------------------
    # Remove department_code from departments
    # ------------------------------------------------------------------
    op.drop_index(
        op.f("ix_departments_department_code"),
        table_name="departments",
    )
    op.drop_column("departments", "department_code")