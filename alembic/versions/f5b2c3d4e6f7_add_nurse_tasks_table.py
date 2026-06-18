"""add_nurse_tasks_table

Revision ID: f5b2c3d4e6f7
Revises: e4a1b2c3d4e5
Create Date: 2026-06-07 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f5b2c3d4e6f7"
down_revision: Union[str, None] = "e4a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "nurse_tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("nurse_id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("priority", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["nurse_id"], ["nurses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_nurse_tasks_id"), "nurse_tasks", ["id"], unique=False)
    op.create_index(op.f("ix_nurse_tasks_nurse_id"), "nurse_tasks", ["nurse_id"], unique=False)
    op.create_index(op.f("ix_nurse_tasks_patient_id"), "nurse_tasks", ["patient_id"], unique=False)
    op.create_index(op.f("ix_nurse_tasks_due_date"), "nurse_tasks", ["due_date"], unique=False)
    op.create_index(op.f("ix_nurse_tasks_priority"), "nurse_tasks", ["priority"], unique=False)
    op.create_index(op.f("ix_nurse_tasks_status"), "nurse_tasks", ["status"], unique=False)
    op.create_index(op.f("ix_nurse_tasks_created_at"), "nurse_tasks", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_nurse_tasks_created_at"), table_name="nurse_tasks")
    op.drop_index(op.f("ix_nurse_tasks_status"), table_name="nurse_tasks")
    op.drop_index(op.f("ix_nurse_tasks_priority"), table_name="nurse_tasks")
    op.drop_index(op.f("ix_nurse_tasks_due_date"), table_name="nurse_tasks")
    op.drop_index(op.f("ix_nurse_tasks_patient_id"), table_name="nurse_tasks")
    op.drop_index(op.f("ix_nurse_tasks_nurse_id"), table_name="nurse_tasks")
    op.drop_index(op.f("ix_nurse_tasks_id"), table_name="nurse_tasks")
    op.drop_table("nurse_tasks")
