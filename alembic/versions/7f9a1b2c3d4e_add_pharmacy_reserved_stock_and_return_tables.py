"""add pharmacy reserved stock and return tables

Revision ID: 7f9a1b2c3d4e
Revises: 0ae8c2d8282b
Create Date: 2026-08-27 15:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7f9a1b2c3d4e"
down_revision = "0ae8c2d8282b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # 1. Add reserved_quantity to medicines
    med_cols = [c["name"] for c in inspector.get_columns("medicines")]
    if "reserved_quantity" not in med_cols:
        op.add_column("medicines", sa.Column("reserved_quantity", sa.Integer(), nullable=False, server_default="0"))

    # 2. Add batch_number and dispensed_quantity to prescription_items
    rx_item_cols = [c["name"] for c in inspector.get_columns("prescription_items")]
    if "batch_number" not in rx_item_cols:
        op.add_column("prescription_items", sa.Column("batch_number", sa.String(100), nullable=True))
    if "dispensed_quantity" not in rx_item_cols:
        op.add_column("prescription_items", sa.Column("dispensed_quantity", sa.Integer(), nullable=False, server_default="0"))

    # 3. Add batch_number and returned_quantity to pharmacy_invoice_items
    inv_item_cols = [c["name"] for c in inspector.get_columns("pharmacy_invoice_items")]
    if "batch_number" not in inv_item_cols:
        op.add_column("pharmacy_invoice_items", sa.Column("batch_number", sa.String(100), nullable=True))
    if "returned_quantity" not in inv_item_cols:
        op.add_column("pharmacy_invoice_items", sa.Column("returned_quantity", sa.Integer(), nullable=False, server_default="0"))

    # 4. Create medicine_batches table
    tables = inspector.get_table_names()
    if "medicine_batches" not in tables:
        op.create_table(
            "medicine_batches",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("medicine_id", sa.Integer(), nullable=False),
            sa.Column("batch_number", sa.String(100), nullable=False),
            sa.Column("expiry_date", sa.Date(), nullable=False),
            sa.Column("stock_quantity", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reserved_quantity", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("unit_price", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), nullable=False),
            sa.ForeignKeyConstraint(["medicine_id"], ["medicines.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_med_batch_med", "medicine_batches", ["medicine_id"])
        op.create_index("idx_med_batch_expiry", "medicine_batches", ["expiry_date"])

    # 5. Create pharmacy_returns table
    if "pharmacy_returns" not in tables:
        op.create_table(
            "pharmacy_returns",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("return_number", sa.String(50), nullable=False, unique=True),
            sa.Column("invoice_id", sa.Integer(), nullable=False),
            sa.Column("patient_id", sa.Integer(), nullable=True),
            sa.Column("total_refund_amount", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("status", sa.String(50), nullable=False, server_default="completed"),
            sa.Column("processed_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["invoice_id"], ["pharmacy_invoices.id"]),
            sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_pharm_ret_inv", "pharmacy_returns", ["invoice_id"])
        op.create_index("idx_pharm_ret_pat", "pharmacy_returns", ["patient_id"])

    # 6. Create pharmacy_return_items table
    if "pharmacy_return_items" not in tables:
        op.create_table(
            "pharmacy_return_items",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("return_id", sa.Integer(), nullable=False),
            sa.Column("invoice_item_id", sa.Integer(), nullable=False),
            sa.Column("medicine_id", sa.Integer(), nullable=False),
            sa.Column("batch_number", sa.String(100), nullable=True),
            sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("unit_price", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("refund_amount", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), nullable=False),
            sa.ForeignKeyConstraint(["return_id"], ["pharmacy_returns.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["invoice_item_id"], ["pharmacy_invoice_items.id"]),
            sa.ForeignKeyConstraint(["medicine_id"], ["medicines.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_pharm_ret_item_ret", "pharmacy_return_items", ["return_id"])
        op.create_index("idx_pharm_ret_item_inv_item", "pharmacy_return_items", ["invoice_item_id"])
        op.create_index("idx_pharm_ret_item_med", "pharmacy_return_items", ["medicine_id"])


def downgrade() -> None:
    op.drop_table("pharmacy_return_items")
    op.drop_table("pharmacy_returns")
    op.drop_table("medicine_batches")
    op.drop_column("pharmacy_invoice_items", "returned_quantity")
    op.drop_column("pharmacy_invoice_items", "batch_number")
    op.drop_column("prescription_items", "dispensed_quantity")
    op.drop_column("prescription_items", "batch_number")
    op.drop_column("medicines", "reserved_quantity")
