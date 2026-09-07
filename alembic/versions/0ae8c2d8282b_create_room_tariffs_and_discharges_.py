"""create_room_tariffs_and_discharges_tables

Revision ID: 0ae8c2d8282b
Revises: e644c56e5bde
Create Date: 2026-08-25 15:38:18.001910

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



revision: str = '0ae8c2d8282b'
down_revision: Union[str, None] = 'e644c56e5bde'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = insp.get_table_names()

    if "room_tariffs" not in tables:
        op.create_table(
            "room_tariffs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("room_type", sa.String(length=50), nullable=False),
            sa.Column("daily_rate", sa.Float(), nullable=False),
            sa.Column("nursing_charge_per_day", sa.Float(), nullable=False, server_default=sa.text("0.0")),
            sa.Column("doctor_visit_charge", sa.Float(), nullable=False, server_default=sa.text("0.0")),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_room_tariffs_room_type"), "room_tariffs", ["room_type"], unique=True)

    if "discharges" not in tables:
        op.create_table(
            "discharges",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("discharge_number", sa.String(length=50), nullable=False),
            sa.Column("appointment_id", sa.Integer(), nullable=False),
            sa.Column("patient_id", sa.Integer(), nullable=False),
            sa.Column("doctor_id", sa.Integer(), nullable=False),
            sa.Column("bed_id", sa.Integer(), nullable=True),
            sa.Column("admission_date", sa.DateTime(), nullable=False),
            sa.Column("discharge_date", sa.DateTime(), nullable=False),
            sa.Column("diagnosis_at_admission", sa.String(length=255), nullable=True),
            sa.Column("diagnosis_at_discharge", sa.String(length=255), nullable=False),
            sa.Column("treatment_summary", sa.Text(), nullable=False),
            sa.Column("condition_on_discharge", sa.String(length=100), nullable=False, server_default="Stable"),
            sa.Column("post_medications", sa.Text(), nullable=True),
            sa.Column("home_care_instructions", sa.Text(), nullable=True),
            sa.Column("follow_up_date", sa.Date(), nullable=True),
            sa.Column("pharmacy_cleared", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("pharmacy_cleared_by", sa.Integer(), nullable=True),
            sa.Column("pharmacy_cleared_at", sa.DateTime(), nullable=True),
            sa.Column("pharmacy_notes", sa.Text(), nullable=True),
            sa.Column("billing_cleared", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("billing_cleared_by", sa.Integer(), nullable=True),
            sa.Column("billing_cleared_at", sa.DateTime(), nullable=True),
            sa.Column("billing_id", sa.Integer(), nullable=True),
            sa.Column("billing_notes", sa.Text(), nullable=True),
            sa.Column("payment_cleared", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("payment_cleared_by", sa.Integer(), nullable=True),
            sa.Column("payment_cleared_at", sa.DateTime(), nullable=True),
            sa.Column("payment_notes", sa.Text(), nullable=True),
            sa.Column("doctor_approved", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("doctor_approved_by", sa.Integer(), nullable=True),
            sa.Column("doctor_approved_at", sa.DateTime(), nullable=True),
            sa.Column("discharge_status", sa.String(length=50), nullable=False, server_default="PENDING_CLEARANCES"),
            sa.Column("gate_pass_number", sa.String(length=50), nullable=True),
            sa.Column("discharge_notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["appointment_id"], ["appointments.id"]),
            sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
            sa.ForeignKeyConstraint(["doctor_id"], ["doctors.id"]),
            sa.ForeignKeyConstraint(["bed_id"], ["beds.id"]),
            sa.ForeignKeyConstraint(["billing_id"], ["billings.id"]),
            sa.ForeignKeyConstraint(["pharmacy_cleared_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["billing_cleared_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["payment_cleared_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["doctor_approved_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_discharges_discharge_number"), "discharges", ["discharge_number"], unique=True)
        op.create_index(op.f("ix_discharges_appointment_id"), "discharges", ["appointment_id"], unique=False)
        op.create_index(op.f("ix_discharges_patient_id"), "discharges", ["patient_id"], unique=False)
        op.create_index(op.f("ix_discharges_doctor_id"), "discharges", ["doctor_id"], unique=False)
        op.create_index(op.f("ix_discharges_discharge_status"), "discharges", ["discharge_status"], unique=False)
        op.create_index(op.f("ix_discharges_gate_pass_number"), "discharges", ["gate_pass_number"], unique=True)


def downgrade() -> None:
    op.drop_table("discharges")
    op.drop_table("room_tariffs")
