import asyncio
from sqlalchemy import select
from app.core.database import AsyncSessionLocal, engine
from app.core.constants import PermissionAction, UserRole
from app.models.permission_model import Permission
from app.models.role_model import Role, RolePermission

# List of all modules/resources and actions to create permissions for
RESOURCE_MODULES = [
    "users", "roles", "permissions", "patients", "doctors", "nurses", "staff", "appointments", "dashboard",
    "billing", "pharmacy", "lab", "inventory", "ai_chat", "voice_reminder", "whatsapp", "analytics", 
    "departments", "bed_allocation", "icu_telemetry", "expense", "vendor"
]

ACTIONS = [
    PermissionAction.CREATE,
    PermissionAction.READ,
    PermissionAction.UPDATE,
    PermissionAction.DELETE,
    PermissionAction.EXPORT,
    PermissionAction.APPROVE,
    PermissionAction.ASSIGN
]

async def seed_missing_permissions():
    print("Connecting to the database and seeding missing permissions...")
    async with AsyncSessionLocal() as session:
        # 1. Fetch existing roles
        roles_result = await session.execute(select(Role))
        roles = {role.name: role for role in roles_result.scalars().all()}
        
        super_admin = roles.get(UserRole.SUPER_ADMIN)
        hospital_admin = roles.get(UserRole.HOSPITAL_ADMIN)
        
        if not super_admin or not hospital_admin:
            print("❌ Super Admin or Hospital Admin roles not found. Please ensure basic seeding is complete.")
            return

        # 2. Collect all target permissions
        total_created = 0
        total_assigned = 0
        
        for resource in RESOURCE_MODULES:
            for action in ACTIONS:
                perm_name = f"{resource}:{action}"
                
                # Check if permission exists
                perm_check = await session.execute(
                    select(Permission).where(Permission.name == perm_name)
                )
                perm = perm_check.scalar_one_or_none()
                
                if not perm:
                    # Create new permission
                    perm = Permission(
                        name=perm_name,
                        resource=resource,
                        action=action,
                        description=f"{action.capitalize()} {resource.replace('_', ' ').capitalize()}"
                    )
                    session.add(perm)
                    await session.flush()  # populate ID
                    total_created += 1
                
                # 3. Assign to Super Admin
                sa_rp_check = await session.execute(
                    select(RolePermission).where(
                        RolePermission.role_id == super_admin.id,
                        RolePermission.permission_id == perm.id
                    )
                )
                if not sa_rp_check.scalar_one_or_none():
                    session.add(RolePermission(role_id=super_admin.id, permission_id=perm.id))
                    total_assigned += 1
                
                # 4. Assign to Hospital Admin
                ha_rp_check = await session.execute(
                    select(RolePermission).where(
                        RolePermission.role_id == hospital_admin.id,
                        RolePermission.permission_id == perm.id
                    )
                )
                if not ha_rp_check.scalar_one_or_none():
                    session.add(RolePermission(role_id=hospital_admin.id, permission_id=perm.id))
                    total_assigned += 1

        await session.commit()
        print(f"✅ Seeding Complete! Created {total_created} new permissions and completed {total_assigned} role assignments.")

if __name__ == "__main__":
    asyncio.run(seed_missing_permissions())
