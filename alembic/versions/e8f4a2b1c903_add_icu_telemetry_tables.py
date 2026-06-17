"""add_icu_telemetry_tables

Revision ID: e8f4a2b1c903
Revises: d37ebcb2dc69
Create Date: 2026-06-12 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8f4a2b1c903"
down_revision: Union[str, None] = "d37ebcb2dc69"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "icu_devices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("bed_id", sa.Integer(), nullable=False),
        sa.Column("device_serial", sa.String(length=100), nullable=False),
        sa.Column("api_key_hash", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["bed_id"], ["beds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_icu_devices_api_key_hash"), "icu_devices", ["api_key_hash"], unique=True)
    op.create_index(op.f("ix_icu_devices_bed_id"), "icu_devices", ["bed_id"], unique=False)
    op.create_index(op.f("ix_icu_devices_created_at"), "icu_devices", ["created_at"], unique=False)
    op.create_index(op.f("ix_icu_devices_device_serial"), "icu_devices", ["device_serial"], unique=True)
    op.create_index(op.f("ix_icu_devices_is_active"), "icu_devices", ["is_active"], unique=False)

    op.create_table(
        "icu_vital_readings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("bed_id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=True),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.Column("heart_rate", sa.Float(), nullable=True),
        sa.Column("systolic_bp", sa.Float(), nullable=True),
        sa.Column("diastolic_bp", sa.Float(), nullable=True),
        sa.Column("spo2", sa.Float(), nullable=True),
        sa.Column("respiratory_rate", sa.Float(), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("ecg_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["bed_id"], ["beds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["icu_devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_icu_vital_readings_bed_id"), "icu_vital_readings", ["bed_id"], unique=False)
    op.create_index(op.f("ix_icu_vital_readings_created_at"), "icu_vital_readings", ["created_at"], unique=False)
    op.create_index(op.f("ix_icu_vital_readings_device_id"), "icu_vital_readings", ["device_id"], unique=False)
    op.create_index(op.f("ix_icu_vital_readings_patient_id"), "icu_vital_readings", ["patient_id"], unique=False)
    op.create_index(op.f("ix_icu_vital_readings_recorded_at"), "icu_vital_readings", ["recorded_at"], unique=False)
    op.create_index(
        "ix_icu_vital_readings_bed_recorded",
        "icu_vital_readings",
        ["bed_id", "recorded_at"],
        unique=False,
    )

    op.create_table(
        "icu_telemetry_alerts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("bed_id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=True),
        sa.Column("vital_reading_id", sa.Integer(), nullable=False),
        sa.Column("vital_type", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("threshold_min", sa.Float(), nullable=True),
        sa.Column("threshold_max", sa.Float(), nullable=True),
        sa.Column("acknowledged_by", sa.Integer(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["acknowledged_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["bed_id"], ["beds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["vital_reading_id"], ["icu_vital_readings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_icu_telemetry_alerts_bed_id"), "icu_telemetry_alerts", ["bed_id"], unique=False)
    op.create_index(op.f("ix_icu_telemetry_alerts_created_at"), "icu_telemetry_alerts", ["created_at"], unique=False)
    op.create_index(op.f("ix_icu_telemetry_alerts_patient_id"), "icu_telemetry_alerts", ["patient_id"], unique=False)
    op.create_index(op.f("ix_icu_telemetry_alerts_severity"), "icu_telemetry_alerts", ["severity"], unique=False)
    op.create_index(op.f("ix_icu_telemetry_alerts_status"), "icu_telemetry_alerts", ["status"], unique=False)
    op.create_index(op.f("ix_icu_telemetry_alerts_vital_reading_id"), "icu_telemetry_alerts", ["vital_reading_id"], unique=False)
    op.create_index(op.f("ix_icu_telemetry_alerts_vital_type"), "icu_telemetry_alerts", ["vital_type"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_icu_telemetry_alerts_vital_type"), table_name="icu_telemetry_alerts")
    op.drop_index(op.f("ix_icu_telemetry_alerts_vital_reading_id"), table_name="icu_telemetry_alerts")
    op.drop_index(op.f("ix_icu_telemetry_alerts_status"), table_name="icu_telemetry_alerts")
    op.drop_index(op.f("ix_icu_telemetry_alerts_severity"), table_name="icu_telemetry_alerts")
    op.drop_index(op.f("ix_icu_telemetry_alerts_patient_id"), table_name="icu_telemetry_alerts")
    op.drop_index(op.f("ix_icu_telemetry_alerts_created_at"), table_name="icu_telemetry_alerts")
    op.drop_index(op.f("ix_icu_telemetry_alerts_bed_id"), table_name="icu_telemetry_alerts")
    op.drop_table("icu_telemetry_alerts")

    op.drop_index("ix_icu_vital_readings_bed_recorded", table_name="icu_vital_readings")
    op.drop_index(op.f("ix_icu_vital_readings_recorded_at"), table_name="icu_vital_readings")
    op.drop_index(op.f("ix_icu_vital_readings_patient_id"), table_name="icu_vital_readings")
    op.drop_index(op.f("ix_icu_vital_readings_device_id"), table_name="icu_vital_readings")
    op.drop_index(op.f("ix_icu_vital_readings_created_at"), table_name="icu_vital_readings")
    op.drop_index(op.f("ix_icu_vital_readings_bed_id"), table_name="icu_vital_readings")
    op.drop_table("icu_vital_readings")

    op.drop_index(op.f("ix_icu_devices_is_active"), table_name="icu_devices")
    op.drop_index(op.f("ix_icu_devices_device_serial"), table_name="icu_devices")
    op.drop_index(op.f("ix_icu_devices_created_at"), table_name="icu_devices")
    op.drop_index(op.f("ix_icu_devices_bed_id"), table_name="icu_devices")
    op.drop_index(op.f("ix_icu_devices_api_key_hash"), table_name="icu_devices")
    op.drop_table("icu_devices")
