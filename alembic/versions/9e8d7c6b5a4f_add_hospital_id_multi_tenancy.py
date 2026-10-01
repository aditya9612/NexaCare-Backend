"""add hospital_id to core operational tables for multi-tenancy

Revision ID: 9e8d7c6b5a4f
Revises: 7a8b9c0d1e2f
Create Date: 2026-09-29 14:20:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = "9e8d7c6b5a4f"
down_revision: Union[str, None] = "7a8b9c0d1e2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = [
    "patients",
    "departments",
    "doctors",
    "staff",
    "nurses",
    "appointments",
    "floors",
    "rooms",
    "beds",
    "bed_activity_logs",
    "billings",
    "medicines",
    "prescriptions",
    "pharmacy_invoices",
    "pharmacy_returns",
    "suppliers",
    "purchases",
    "lab_tests",
    "test_orders",
    "discharges",
    "expense_categories",
    "expenses",
    "vendors",
    "audit_logs",
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
                try:
                    op.create_foreign_key(
                        f"fk_{table}_hospital_id_hospitals",
                        table,
                        "hospitals",
                        ["hospital_id"],
                        ["id"],
                        ondelete="SET NULL",
                    )
                except Exception:
                    pass

    # Backfill hospital_id from existing hospital if available
    try:
        if "hospitals" in existing_tables:
            result = conn.execute(sa.text("SELECT id FROM hospitals ORDER BY id ASC LIMIT 1")).fetchone()
            if result:
                first_hospital_id = result[0]
                for table in TABLES:
                    if table in existing_tables:
                        conn.execute(
                            sa.text(f"UPDATE {table} SET hospital_id = :hid WHERE hospital_id IS NULL"),
                            {"hid": first_hospital_id},
                        )
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
                    op.drop_constraint(f"fk_{table}_hospital_id_hospitals", table, type_="foreignkey")
                except Exception:
                    pass
                try:
                    op.drop_index(f"ix_{table}_hospital_id", table_name=table)
                except Exception:
                    pass
                op.drop_column(table, "hospital_id")
