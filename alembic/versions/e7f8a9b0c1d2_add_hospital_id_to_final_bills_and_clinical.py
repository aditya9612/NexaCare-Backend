"""add hospital_id to ipd_final_bills and clinical tables

Revision ID: e7f8a9b0c1d2
Revises: 9e8d7c6b5a4f
Create Date: 2026-09-29 18:25:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "9e8d7c6b5a4f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = [
    "ipd_final_bills",
    "doctor_schedules",
    "doctor_medical_records",
    "clinical_records",
    "nurse_patient_assignments",
    "nurse_shifts",
    "nurse_tasks",
    "nurse_medication_logs",
    "nurse_attendance",
    "patient_vitals",
    "patient_diagnoses",
    "patient_documents",
    "treatment_notes",
    "payments",
    "vendor_payments",
    "samples",
    "test_results",
    "lab_reports",
    "inventory_items",
    "notifications",
]


def upgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    existing_tables = set(inspector.get_table_names())

    for table in TABLES:
        if table in existing_tables:
            columns = [col["name"] for col in inspector.get_columns(table)]
            if "hospital_id" not in columns:
                op.add_column(table, sa.Column("hospital_id", sa.Integer(), nullable=True))
                try:
                    op.create_index(f"ix_{table}_hospital_id", table, ["hospital_id"])
                except Exception:
                    pass

    # Backfill ipd_final_bills.hospital_id from discharges or patients
    try:
        conn.execute(sa.text("""
            UPDATE ipd_final_bills f
            JOIN discharges d ON f.discharge_id = d.id
            SET f.hospital_id = d.hospital_id
            WHERE f.hospital_id IS NULL AND d.hospital_id IS NOT NULL
        """))
        conn.execute(sa.text("""
            UPDATE ipd_final_bills f
            JOIN patients p ON f.patient_id = p.id
            SET f.hospital_id = p.hospital_id
            WHERE f.hospital_id IS NULL AND p.hospital_id IS NOT NULL
        """))
    except Exception:
        pass


def downgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    existing_tables = set(inspector.get_table_names())

    for table in TABLES:
        if table in existing_tables:
            columns = [col["name"] for col in inspector.get_columns(table)]
            if "hospital_id" in columns:
                try:
                    op.drop_index(f"ix_{table}_hospital_id", table_name=table)
                except Exception:
                    pass
                op.drop_column(table, "hospital_id")
