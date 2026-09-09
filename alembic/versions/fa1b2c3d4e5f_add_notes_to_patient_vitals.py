"""add_notes_to_patient_vitals

Revision ID: fa1b2c3d4e5f
Revises: 405fd210ac69
Create Date: 2026-09-03 14:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "fa1b2c3d4e5f"
down_revision: Union[str, None] = "405fd210ac69"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("patient_vitals")]
    if "notes" not in columns:
        op.add_column("patient_vitals", sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("patient_vitals")]
    if "notes" in columns:
        op.drop_column("patient_vitals", "notes")
