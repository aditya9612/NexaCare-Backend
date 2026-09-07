"""add_admission_number_to_appointments

Revision ID: e644c56e5bde
Revises: 56422ffac90d
Create Date: 2026-08-25 13:32:11.205221

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = 'e644c56e5bde'
down_revision: Union[str, None] = '56422ffac90d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    columns = [c["name"] for c in insp.get_columns("appointments")]
    if "admission_number" not in columns:
        op.add_column("appointments", sa.Column("admission_number", sa.String(length=50), nullable=True))
        op.create_index(op.f("ix_appointments_admission_number"), "appointments", ["admission_number"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_appointments_admission_number"), table_name="appointments")
    op.drop_column("appointments", "admission_number")
