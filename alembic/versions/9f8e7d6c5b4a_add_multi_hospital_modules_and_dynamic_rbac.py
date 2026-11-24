"""add_multi_hospital_modules_and_dynamic_rbac

Revision ID: 9f8e7d6c5b4a
Revises: 0c0455c0724a
Create Date: 2026-11-17 13:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = '9f8e7d6c5b4a'
down_revision: Union[str, None] = '0c0455c0724a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CANONICAL_MODULES = [
    ("PATIENT_MGMT", "Patient Management", "FOUNDATIONAL", "Core clinical records, vitals, documents"),
    ("DOCTOR_MGMT", "Doctor Management", "FOUNDATIONAL", "Doctor directory, profiles, schedules"),
    ("NURSE_MGMT", "Nurse Management", "FOUNDATIONAL", "Nurse stations, shifts, patient updates"),
    ("STAFF_MGMT", "Staff Management", "FOUNDATIONAL", "Hospital staff directory and departments"),
    ("APPOINTMENTS", "Appointments & Queues", "FOUNDATIONAL", "Scheduling, token generation, triage"),
    ("BILLING", "Billing & Tariffs", "FOUNDATIONAL", "Invoices, payments, room tariffs, discharge bills"),
    ("PHARMACY", "Pharmacy & Dispensary", "FOUNDATIONAL", "Medications, inventory, prescriptions"),
    ("LABORATORY", "Laboratory & Diagnostics", "FOUNDATIONAL", "Diagnostic tests, orders, lab reports"),
    ("INVENTORY", "Hospital Inventory", "FOUNDATIONAL", "Stock items, consumables, vendors"),
    ("BED_MGMT", "Bed Allocation", "FOUNDATIONAL", "Wards, rooms, bed status, inpatient care"),
    ("ICU_TELEMETRY", "ICU Telemetry", "FOUNDATIONAL", "Bedside monitor vital reading and alerts"),
    ("REPORTS", "Reports & Analytics", "FOUNDATIONAL", "Clinical, administrative, and financial reporting"),
    ("SETTINGS", "Hospital Settings", "FOUNDATIONAL", "Operational rules, tenant configurations, RBAC"),
    ("NOTIFICATIONS", "Notifications", "FOUNDATIONAL", "In-app notifications and real-time alerts"),
    ("VOICE_REMIND", "Voice Call Reminders", "COMMERCIAL", "Automated outbound voice call reminders"),
    ("VOICE_ASSISTANT", "Voice AI Assistant", "COMMERCIAL", "Interactive voice appointment booking agent"),
    ("AI_ASSISTANT", "AI Clinical Copilot", "COMMERCIAL", "AI chatbot, clinical notes summarization, FAQ"),
    ("WHATSAPP", "WhatsApp Messaging", "COMMERCIAL", "WhatsApp notifications and appointment alerts"),
]

FOUNDATIONAL_CODES = [m[0] for m in CANONICAL_MODULES if m[2] == "FOUNDATIONAL"]


def upgrade() -> None:
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    tables = inspector.get_table_names()

    # 1. Create modules table if not exists
    if "modules" not in tables:
        op.create_table(
            "modules",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("code", sa.String(length=50), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("tier", sa.String(length=20), nullable=False, server_default="FOUNDATIONAL"),
            sa.Column("description", sa.String(length=255), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
            sa.UniqueConstraint("code", name="uq_modules_code"),
        )
        op.create_index("ix_modules_code", "modules", ["code"])

    # 2. Create hospital_modules table if not exists
    if "hospital_modules" not in tables:
        op.create_table(
            "hospital_modules",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("hospital_id", sa.Integer(), sa.ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False),
            sa.Column("module_code", sa.String(length=50), sa.ForeignKey("modules.code", ondelete="CASCADE"), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
            sa.Column("activated_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
            sa.UniqueConstraint("hospital_id", "module_code", name="uq_hospital_module"),
        )
        op.create_index("ix_hospital_modules_lookup", "hospital_modules", ["hospital_id", "is_active"])

    # 3. Create role_permission_overrides table if not exists
    if "role_permission_overrides" not in tables:
        op.create_table(
            "role_permission_overrides",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("hospital_id", sa.Integer(), sa.ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False),
            sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
            sa.Column("permission_id", sa.Integer(), sa.ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("is_granted", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("hospital_id", "role_id", "permission_id", name="uq_hospital_role_override"),
        )
        op.create_index("ix_role_overrides_lookup", "role_permission_overrides", ["hospital_id", "role_id"])

    # 4. Enhance roles table
    role_cols = [col["name"] for col in inspector.get_columns("roles")]
    if "hospital_id" not in role_cols:
        op.add_column("roles", sa.Column("hospital_id", sa.Integer(), sa.ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=True))
        op.create_index("ix_roles_hospital_id", "roles", ["hospital_id"])
    if "base_role_type" not in role_cols:
        op.add_column("roles", sa.Column("base_role_type", sa.String(length=50), nullable=True))
        op.create_index("ix_roles_base_role_type", "roles", ["base_role_type"])
    if "is_system" not in role_cols:
        op.add_column("roles", sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("0")))
        op.create_index("ix_roles_is_system", "roles", ["is_system"])

    # 5. Enhance insurances table (Blocker B-03 resolution: nullable=True)
    if "insurances" in tables:
        ins_cols = [col["name"] for col in inspector.get_columns("insurances")]
        if "hospital_id" not in ins_cols:
            op.add_column("insurances", sa.Column("hospital_id", sa.Integer(), sa.ForeignKey("hospitals.id", ondelete="SET NULL"), nullable=True))
            op.create_index("ix_insurances_hospital_id", "insurances", ["hospital_id"])

    # 5b. Enhance room_tariffs table (F-01 resolution)
    if "room_tariffs" in tables:
        rt_cols = [col["name"] for col in inspector.get_columns("room_tariffs")]
        if "hospital_id" not in rt_cols:
            op.add_column("room_tariffs", sa.Column("hospital_id", sa.Integer(), sa.ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=True))
            op.create_index("ix_room_tariffs_hospital_id", "room_tariffs", ["hospital_id"])

        for idx in inspector.get_indexes("room_tariffs"):
            if idx["name"] == "ix_room_tariffs_room_type" and idx.get("unique"):
                try:
                    op.drop_index("ix_room_tariffs_room_type", table_name="room_tariffs")
                    op.create_index("ix_room_tariffs_room_type", "room_tariffs", ["room_type"], unique=False)
                except Exception:
                    pass

        rt_uqs = [c["name"] for c in inspector.get_unique_constraints("room_tariffs")]
        if "uq_room_tariffs_hospital_room_type" not in rt_uqs:
            try:
                op.create_unique_constraint("uq_room_tariffs_hospital_room_type", "room_tariffs", ["hospital_id", "room_type"])
            except Exception:
                pass

    # 5c. Enhance transaction_history table (F-01 resolution)
    if "transaction_history" in tables:
        th_cols = [col["name"] for col in inspector.get_columns("transaction_history")]
        if "hospital_id" not in th_cols:
            op.add_column("transaction_history", sa.Column("hospital_id", sa.Integer(), sa.ForeignKey("hospitals.id", ondelete="SET NULL"), nullable=True))
            op.create_index("ix_transaction_history_hospital_id", "transaction_history", ["hospital_id"])

    # 6. Seed master modules catalog
    for code, name, tier, desc in CANONICAL_MODULES:
        conn.execute(
            sa.text(
                "INSERT INTO modules (code, name, tier, description, is_active, created_at, updated_at) "
                "VALUES (:code, :name, :tier, :desc, 1, NOW(), NOW()) "
                "ON DUPLICATE KEY UPDATE name = :name, tier = :tier, description = :desc"
            ),
            {"code": code, "name": name, "tier": tier, "desc": desc},
        )

    # 7. Grandfather all existing hospitals with foundational modules (Blocker B-02 resolution)
    # Batch backfill to prevent lock timeouts
    hosp_res = conn.execute(sa.text("SELECT id FROM hospitals")).fetchall()
    for row in hosp_res:
        hosp_id = row[0]
        for f_code in FOUNDATIONAL_CODES:
            conn.execute(
                sa.text(
                    "INSERT IGNORE INTO hospital_modules (hospital_id, module_code, is_active, status, activated_at, created_at, updated_at) "
                    "VALUES (:hosp_id, :code, 1, 'ACTIVE', NOW(), NOW(), NOW())"
                ),
                {"hosp_id": hosp_id, "code": f_code},
            )

    # 8. Mark all pre-existing roles as system templates
    conn.execute(sa.text("UPDATE roles SET is_system = 1 WHERE hospital_id IS NULL"))

    # Map canonical base_role_type archetypes for pre-existing system roles
    role_archetype_map = {
        "Doctor": "DOCTOR",
        "Nurse": "NURSE",
        "Receptionist": "RECEPTIONIST",
        "Pharmacist": "PHARMACIST",
        "Lab Technician": "LAB_TECHNICIAN",
        "Accountant": "ACCOUNTANT",
        "Hospital Admin": "HOSPITAL_ADMIN",
        "Super Admin": "SUPER_ADMIN",
        "Patient": "PATIENT",
    }
    for r_name, b_type in role_archetype_map.items():
        conn.execute(
            sa.text("UPDATE roles SET base_role_type = :b_type WHERE name = :r_name AND base_role_type IS NULL"),
            {"b_type": b_type, "r_name": r_name},
        )


def downgrade() -> None:
    # Forward-only recovery: do not drop tables or columns to prevent data loss
    pass
