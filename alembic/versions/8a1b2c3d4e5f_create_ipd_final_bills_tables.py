"""create ipd final bills tables

Revision ID: 8a1b2c3d4e5f
Revises: b7d5f0e9c1a2
Create Date: 2026-08-27 18:43:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8a1b2c3d4e5f"
down_revision: Union[str, None] = "b7d5f0e9c1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    # 1. Create ipd_final_bills table
    if "ipd_final_bills" not in tables:
        op.create_table(
            "ipd_final_bills",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("bill_number", sa.String(50), nullable=False, unique=True),
            sa.Column("discharge_id", sa.Integer(), nullable=False),
            sa.Column("patient_id", sa.Integer(), nullable=False),
            sa.Column("appointment_id", sa.Integer(), nullable=False),
            sa.Column("doctor_id", sa.Integer(), nullable=False),
            sa.Column("bed_id", sa.Integer(), nullable=True),
            
            # Component subtotals
            sa.Column("bed_charges", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("doctor_charges", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("lab_charges", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("radiology_charges", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("pharmacy_charges", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("procedure_charges", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("prior_opd_charges", sa.Float(), nullable=False, server_default="0.0"),
            
            # Financial calculations
            sa.Column("gross_total", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("discount_amount", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("discount_reason", sa.String(255), nullable=True),
            sa.Column("tax_rate", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("tax_amount", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("net_total", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("advance_adjusted", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("balance_amount", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("refund_amount", sa.Float(), nullable=False, server_default="0.0"),
            
            # Status & Settlement
            sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
            sa.Column("payment_mode", sa.String(50), nullable=True, server_default="Cash"),
            sa.Column("settled_at", sa.DateTime(), nullable=True),
            sa.Column("settled_by", sa.Integer(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            
            # Timestamps
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            
            sa.ForeignKeyConstraint(["discharge_id"], ["discharges.id"]),
            sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
            sa.ForeignKeyConstraint(["appointment_id"], ["appointments.id"]),
            sa.ForeignKeyConstraint(["doctor_id"], ["doctors.id"]),
            sa.ForeignKeyConstraint(["bed_id"], ["beds.id"]),
            sa.ForeignKeyConstraint(["settled_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_ipd_bill_num", "ipd_final_bills", ["bill_number"])
        op.create_index("idx_ipd_bill_disch", "ipd_final_bills", ["discharge_id"])
        op.create_index("idx_ipd_bill_pat", "ipd_final_bills", ["patient_id"])
        op.create_index("idx_ipd_bill_apt", "ipd_final_bills", ["appointment_id"])

    # 2. Create ipd_final_bill_items table
    if "ipd_final_bill_items" not in tables:
        op.create_table(
            "ipd_final_bill_items",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("final_bill_id", sa.Integer(), nullable=False),
            sa.Column("item_type", sa.String(50), nullable=False),
            sa.Column("item_name", sa.String(255), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("unit_price", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("tax_rate", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("total_price", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("reference_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), nullable=False),
            
            sa.ForeignKeyConstraint(["final_bill_id"], ["ipd_final_bills.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_ipd_bill_items_bill", "ipd_final_bill_items", ["final_bill_id"])
        op.create_index("idx_ipd_bill_items_type", "ipd_final_bill_items", ["item_type"])

    # 3. Add final_bill_id column to discharges table
    disch_cols = [c["name"] for c in inspector.get_columns("discharges")]
    if "final_bill_id" not in disch_cols:
        op.add_column("discharges", sa.Column("final_bill_id", sa.Integer(), nullable=True))
        op.create_foreign_key("fk_discharges_final_bill", "discharges", "ipd_final_bills", ["final_bill_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_discharges_final_bill", "discharges", type_="foreignkey")
    op.drop_column("discharges", "final_bill_id")
    op.drop_table("ipd_final_bill_items")
    op.drop_table("ipd_final_bills")
