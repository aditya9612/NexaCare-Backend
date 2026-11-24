"""Add clinical records permissions and assign to Doctor and Admin roles

Revision ID: b8a7c6d5e4f3
Revises: 9f8e7d6c5b4a
Create Date: 2026-11-18 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text

# revision identifiers, used by Alembic.
revision = 'b8a7c6d5e4f3'
down_revision = '9f8e7d6c5b4a'
branch_labels = None
depends_on = None

NEW_PERMISSIONS = [
    ("clinical_records:create", "clinical_records", "create", "Create clinical records"),
    ("clinical_records:read", "clinical_records", "read", "Read clinical records"),
    ("clinical_records:update", "clinical_records", "update", "Update clinical records"),
    ("clinical_records:delete", "clinical_records", "delete", "Delete clinical records"),
]

# Role assignment policy:
# - Doctor: create, read, update (NO delete permission on legal medical records)
# - Hospital Admin: create, read, update, delete
# - Super Admin: create, read, update, delete
ROLE_PERM_MAPPING = {
    "Doctor": ["clinical_records:create", "clinical_records:read", "clinical_records:update"],
    "Hospital Admin": ["clinical_records:create", "clinical_records:read", "clinical_records:update", "clinical_records:delete"],
    "Super Admin": ["clinical_records:create", "clinical_records:read", "clinical_records:update", "clinical_records:delete"],
}


def upgrade():
    conn = op.get_bind()

    # 1. Idempotently insert missing permissions
    for name, resource, action, desc in NEW_PERMISSIONS:
        existing = conn.execute(
            text("SELECT id FROM permissions WHERE name = :name"),
            {"name": name}
        ).fetchone()
        if not existing:
            conn.execute(
                text("""
                    INSERT INTO permissions (name, resource, action, description)
                    VALUES (:name, :resource, :action, :desc)
                """),
                {"name": name, "resource": resource, "action": action, "desc": desc}
            )

    # 2. Map permissions to intended system roles
    for role_name, perm_names in ROLE_PERM_MAPPING.items():
        role = conn.execute(
            text("SELECT id FROM roles WHERE name = :name AND is_system = 1 LIMIT 1"),
            {"name": role_name}
        ).fetchone()
        if not role:
            continue
        role_id = role[0]

        for p_name in perm_names:
            perm = conn.execute(
                text("SELECT id FROM permissions WHERE name = :name"),
                {"name": p_name}
            ).fetchone()
            if not perm:
                continue
            perm_id = perm[0]

            # Check existing mapping
            rp = conn.execute(
                text("SELECT id FROM role_permissions WHERE role_id = :role_id AND permission_id = :perm_id"),
                {"role_id": role_id, "perm_id": perm_id}
            ).fetchone()
            if not rp:
                conn.execute(
                    text("""
                        INSERT INTO role_permissions (role_id, permission_id)
                        VALUES (:role_id, :perm_id)
                    """),
                    {"role_id": role_id, "perm_id": perm_id}
                )


def downgrade():
    conn = op.get_bind()

    # Retrieve permission IDs for the 4 permissions
    perm_ids = []
    for name, _, _, _ in NEW_PERMISSIONS:
        row = conn.execute(
            text("SELECT id FROM permissions WHERE name = :name"),
            {"name": name}
        ).fetchone()
        if row:
            perm_ids.append(row[0])

    if perm_ids:
        # Delete only role_permissions associated with these permissions
        for pid in perm_ids:
            conn.execute(
                text("DELETE FROM role_permissions WHERE permission_id = :pid"),
                {"pid": pid}
            )

        # Delete the permissions
        for name, _, _, _ in NEW_PERMISSIONS:
            conn.execute(
                text("DELETE FROM permissions WHERE name = :name"),
                {"name": name}
            )
