"""add booking_source to appointments; migrate ai_voice off appointment_type

Revision ID: f7a1c2d3e4b5
Revises: 46bfa1804b10
Create Date: 2026-08-21 15:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7a1c2d3e4b5"
down_revision: Union[str, None] = "46bfa1804b10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column("booking_source", sa.String(length=50), nullable=True),
    )
    op.create_index(
        op.f("ix_appointments_booking_source"),
        "appointments",
        ["booking_source"],
        unique=False,
    )
    # Move legacy channel marker out of appointment_type into booking_source
    op.execute(
        """
        UPDATE appointments
        SET booking_source = 'ai_voice',
            appointment_type = NULL
        WHERE LOWER(appointment_type) = 'ai_voice'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE appointments
        SET appointment_type = 'ai_voice'
        WHERE booking_source = 'ai_voice'
          AND (appointment_type IS NULL OR appointment_type = '')
        """
    )
    op.drop_index(op.f("ix_appointments_booking_source"), table_name="appointments")
    op.drop_column("appointments", "booking_source")
