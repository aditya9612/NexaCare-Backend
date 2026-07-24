"""Add guardian_patient_id for family patients under a phone account holder

Revision ID: c3d4e5f6a7b8
Revises: 7418f4b54f93
Create Date: 2026-07-23 13:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "7418f4b54f93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "patients",
        sa.Column("guardian_patient_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "patients",
        sa.Column("relationship_to_guardian", sa.String(length=50), nullable=True),
    )
    op.create_index(
        "ix_patients_guardian_patient_id",
        "patients",
        ["guardian_patient_id"],
    )
    op.create_foreign_key(
        "fk_patients_guardian_patient_id",
        "patients",
        "patients",
        ["guardian_patient_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_patients_guardian_patient_id", "patients", type_="foreignkey")
    op.drop_index("ix_patients_guardian_patient_id", table_name="patients")
    op.drop_column("patients", "relationship_to_guardian")
    op.drop_column("patients", "guardian_patient_id")
