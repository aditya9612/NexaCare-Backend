"""add technician and doctor verification fields to lab_reports

Revision ID: 7a8b9c0d1e2f
Revises: c2454a050e1c
Create Date: 2026-09-18 10:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7a8b9c0d1e2f"
down_revision: Union[str, None] = "c2454a050e1c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Adding technician verification fields
    op.add_column("lab_reports", sa.Column("technician_verified_by", sa.Integer(), nullable=True))
    op.add_column("lab_reports", sa.Column("technician_verified_at", sa.DateTime(), nullable=True))
    op.add_column("lab_reports", sa.Column("technician_remarks", sa.Text(), nullable=True))
    
    # Adding doctor verification fields
    op.add_column("lab_reports", sa.Column("doctor_verified_by", sa.Integer(), nullable=True))
    op.add_column("lab_reports", sa.Column("doctor_verified_at", sa.DateTime(), nullable=True))
    op.add_column("lab_reports", sa.Column("doctor_remarks", sa.Text(), nullable=True))

    # Foreign keys
    try:
        op.create_foreign_key(
            "fk_lab_reports_technician_verified_by_users",
            "lab_reports",
            "users",
            ["technician_verified_by"],
            ["id"],
        )
    except Exception:
        pass

    try:
        op.create_foreign_key(
            "fk_lab_reports_doctor_verified_by_users",
            "lab_reports",
            "users",
            ["doctor_verified_by"],
            ["id"],
        )
    except Exception:
        pass


def downgrade() -> None:
    try:
        op.drop_constraint("fk_lab_reports_doctor_verified_by_users", "lab_reports", type_="foreignkey")
    except Exception:
        pass

    try:
        op.drop_constraint("fk_lab_reports_technician_verified_by_users", "lab_reports", type_="foreignkey")
    except Exception:
        pass

    op.drop_column("lab_reports", "doctor_remarks")
    op.drop_column("lab_reports", "doctor_verified_at")
    op.drop_column("lab_reports", "doctor_verified_by")
    op.drop_column("lab_reports", "technician_remarks")
    op.drop_column("lab_reports", "technician_verified_at")
    op.drop_column("lab_reports", "technician_verified_by")
