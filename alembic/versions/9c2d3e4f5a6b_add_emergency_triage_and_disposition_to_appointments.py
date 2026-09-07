"""add emergency triage and disposition to appointments

Revision ID: 9c2d3e4f5a6b
Revises: 8a1b2c3d4e5f
Create Date: 2026-08-31 13:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9c2d3e4f5a6b"
down_revision: Union[str, None] = "8a1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add emergency triage and disposition fields to appointments table
    op.add_column("appointments", sa.Column("triage_level", sa.Integer(), nullable=True))
    op.create_index("ix_appointments_triage_level", "appointments", ["triage_level"], unique=False)

    op.add_column("appointments", sa.Column("triage_notes", sa.Text(), nullable=True))

    op.add_column("appointments", sa.Column("disposition", sa.String(50), nullable=True))
    op.create_index("ix_appointments_disposition", "appointments", ["disposition"], unique=False)

    op.add_column("appointments", sa.Column("referred_to", sa.String(255), nullable=True))
    op.add_column("appointments", sa.Column("referral_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("appointments", "referral_reason")
    op.drop_column("appointments", "referred_to")

    op.drop_index("ix_appointments_disposition", table_name="appointments")
    op.drop_column("appointments", "disposition")

    op.drop_column("appointments", "triage_notes")

    op.drop_index("ix_appointments_triage_level", table_name="appointments")
    op.drop_column("appointments", "triage_level")
