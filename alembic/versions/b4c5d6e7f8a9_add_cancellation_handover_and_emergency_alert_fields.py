"""add_cancellation_handover_and_emergency_alert_fields

Revision ID: b4c5d6e7f8a9
Revises: f9a8b7c6d5e4
Create Date: 2026-10-29 18:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, None] = "f9a8b7c6d5e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # 1. Nurse medication logs - cancellation fields
    nml_columns = [c["name"] for c in inspector.get_columns("nurse_medication_logs")]
    if "cancellation_reason" not in nml_columns:
        op.add_column("nurse_medication_logs", sa.Column("cancellation_reason", sa.Text(), nullable=True))
    if "cancelled_by" not in nml_columns:
        op.add_column(
            "nurse_medication_logs",
            sa.Column(
                "cancelled_by",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    if "cancelled_at" not in nml_columns:
        op.add_column("nurse_medication_logs", sa.Column("cancelled_at", sa.DateTime(), nullable=True))

    # 2. Nurse handover notes - incoming nurse and patient fields
    nhn_columns = [c["name"] for c in inspector.get_columns("nurse_handover_notes")]
    nhn_indexes = [idx["name"] for idx in inspector.get_indexes("nurse_handover_notes")]

    if "incoming_nurse_id" not in nhn_columns:
        op.add_column(
            "nurse_handover_notes",
            sa.Column(
                "incoming_nurse_id",
                sa.Integer(),
                sa.ForeignKey("nurses.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    if "ix_nurse_handover_notes_incoming_nurse_id" not in nhn_indexes:
        op.create_index(
            "ix_nurse_handover_notes_incoming_nurse_id",
            "nurse_handover_notes",
            ["incoming_nurse_id"],
        )

    if "patient_id" not in nhn_columns:
        op.add_column(
            "nurse_handover_notes",
            sa.Column(
                "patient_id",
                sa.Integer(),
                sa.ForeignKey("patients.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    if "ix_nurse_handover_notes_patient_id" not in nhn_indexes:
        op.create_index(
            "ix_nurse_handover_notes_patient_id",
            "nurse_handover_notes",
            ["patient_id"],
        )

    # 3. Emergency alerts - appointment field
    ea_columns = [c["name"] for c in inspector.get_columns("emergency_alerts")]
    ea_indexes = [idx["name"] for idx in inspector.get_indexes("emergency_alerts")]

    if "appointment_id" not in ea_columns:
        op.add_column(
            "emergency_alerts",
            sa.Column(
                "appointment_id",
                sa.Integer(),
                sa.ForeignKey("appointments.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    if "ix_emergency_alerts_appointment_id" not in ea_indexes:
        op.create_index(
            "ix_emergency_alerts_appointment_id",
            "emergency_alerts",
            ["appointment_id"],
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # 1. Emergency alerts - drop appointment field
    ea_columns = [c["name"] for c in inspector.get_columns("emergency_alerts")]
    ea_indexes = [idx["name"] for idx in inspector.get_indexes("emergency_alerts")]

    if "ix_emergency_alerts_appointment_id" in ea_indexes:
        op.drop_index("ix_emergency_alerts_appointment_id", table_name="emergency_alerts")
    if "appointment_id" in ea_columns:
        op.drop_column("emergency_alerts", "appointment_id")

    # 2. Nurse handover notes - drop patient and incoming nurse fields
    nhn_columns = [c["name"] for c in inspector.get_columns("nurse_handover_notes")]
    nhn_indexes = [idx["name"] for idx in inspector.get_indexes("nurse_handover_notes")]

    if "ix_nurse_handover_notes_patient_id" in nhn_indexes:
        op.drop_index("ix_nurse_handover_notes_patient_id", table_name="nurse_handover_notes")
    if "patient_id" in nhn_columns:
        op.drop_column("nurse_handover_notes", "patient_id")

    if "ix_nurse_handover_notes_incoming_nurse_id" in nhn_indexes:
        op.drop_index("ix_nurse_handover_notes_incoming_nurse_id", table_name="nurse_handover_notes")
    if "incoming_nurse_id" in nhn_columns:
        op.drop_column("nurse_handover_notes", "incoming_nurse_id")

    # 3. Nurse medication logs - drop cancellation fields
    nml_columns = [c["name"] for c in inspector.get_columns("nurse_medication_logs")]

    if "cancelled_at" in nml_columns:
        op.drop_column("nurse_medication_logs", "cancelled_at")
    if "cancelled_by" in nml_columns:
        op.drop_column("nurse_medication_logs", "cancelled_by")
    if "cancellation_reason" in nml_columns:
        op.drop_column("nurse_medication_logs", "cancellation_reason")

