import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import UserRole
from app.core.dependencies import require_permission, require_roles
from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.models.permission_model import Permission
from app.models.role_model import Role, RolePermission, RolePermissionOverride
from app.models.user_model import User
from app.repositories.rbac_repository import RBACRepository
from app.schemas.rbac_schema import RoleCreate, RolePermissionOverrideRequest, RoleUpdate
from app.services.module_service import ModuleService
from app.services.rbac_service import RBACService


@pytest.mark.asyncio
async def test_new_doctor_custom_role_clones_baseline_permissions():
    """Verify newly created custom role with base_role_type='DOCTOR' clones all baseline doctor permissions."""
    mock_db = AsyncMock(spec=AsyncSession)
    service = RBACService(mock_db)

    # Mock get_role_by_name returning None (role doesn't exist yet)
    service.repo.get_role_by_name = AsyncMock(return_value=None)

    # Mock newly created custom role
    created_custom_role = Role(
        id=50,
        name="Senior Cardiologist",
        hospital_id=101,
        base_role_type="DOCTOR",
        is_system=False,
    )
    service.repo.create_role = AsyncMock(return_value=created_custom_role)

    # Mock system Doctor role
    system_doctor_role = Role(
        id=7,
        name="Doctor",
        hospital_id=None,
        base_role_type="DOCTOR",
        is_system=True,
    )
    service.repo.get_system_role_by_archetype = AsyncMock(return_value=system_doctor_role)
    service.repo.clone_role_permissions = AsyncMock(return_value=31)
    service.audit_repo.create = AsyncMock()

    data = RoleCreate(
        name="Senior Cardiologist",
        description="Senior Cardiology Specialist",
        hospital_id=101,
        base_role_type="DOCTOR",
    )

    result = await service.create_role(data, user_id=1, hospital_id=101)

    assert result.id == 50
    assert result.name == "Senior Cardiologist"
    assert result.base_role_type == "DOCTOR"
    assert result.hospital_id == 101
    assert result.is_system is False

    # Verify archetype lookup and permission cloning were invoked
    service.repo.get_system_role_by_archetype.assert_awaited_once_with("DOCTOR")
    service.repo.clone_role_permissions.assert_awaited_once_with(7, 50)


@pytest.mark.asyncio
async def test_new_nurse_custom_role_clones_baseline_permissions():
    """Verify newly created custom role with base_role_type='NURSE' clones nurse baseline permissions."""
    mock_db = AsyncMock(spec=AsyncSession)
    service = RBACService(mock_db)

    service.repo.get_role_by_name = AsyncMock(return_value=None)
    created_custom_role = Role(
        id=51,
        name="Night Charge Nurse",
        hospital_id=101,
        base_role_type="NURSE",
        is_system=False,
    )
    service.repo.create_role = AsyncMock(return_value=created_custom_role)

    system_nurse_role = Role(id=9, name="Nurse", hospital_id=None, base_role_type="NURSE", is_system=True)
    service.repo.get_system_role_by_archetype = AsyncMock(return_value=system_nurse_role)
    service.repo.clone_role_permissions = AsyncMock(return_value=19)
    service.audit_repo.create = AsyncMock()

    data = RoleCreate(name="Night Charge Nurse", hospital_id=101, base_role_type="NURSE")
    result = await service.create_role(data, user_id=1, hospital_id=101)

    assert result.id == 51
    assert result.base_role_type == "NURSE"
    service.repo.get_system_role_by_archetype.assert_awaited_once_with("NURSE")
    service.repo.clone_role_permissions.assert_awaited_once_with(9, 51)


@pytest.mark.asyncio
async def test_empty_or_invalid_base_archetype_behavior():
    """Verify empty archetype clones zero permissions, and invalid archetype raises BadRequestException."""
    mock_db = AsyncMock(spec=AsyncSession)
    service = RBACService(mock_db)
    service.repo.get_role_by_name = AsyncMock(return_value=None)
    service.repo.get_system_role_by_archetype = AsyncMock()
    service.repo.clone_role_permissions = AsyncMock()
    service.audit_repo.create = AsyncMock()

    # 1. Invalid base archetype
    data_invalid = RoleCreate(name="Custom Astronaut", hospital_id=101, base_role_type="ASTRONAUT")
    with pytest.raises(BadRequestException) as exc:
        await service.create_role(data_invalid, user_id=1, hospital_id=101)
    assert "Invalid base archetype" in str(exc.value)

    # 2. Tenant role cannot use SUPER_ADMIN archetype
    data_sa = RoleCreate(name="Tenant Super Admin", hospital_id=101, base_role_type="SUPER_ADMIN")
    with pytest.raises(BadRequestException) as exc_sa:
        await service.create_role(data_sa, user_id=1, hospital_id=101)
    assert "SUPER_ADMIN" in str(exc_sa.value)


    # 3. Empty base archetype: role created but 0 permissions cloned
    role_empty = Role(id=52, name="Blank Role", hospital_id=101, base_role_type=None, is_system=False)
    service.repo.create_role = AsyncMock(return_value=role_empty)
    data_empty = RoleCreate(name="Blank Role", hospital_id=101, base_role_type=None)
    res_empty = await service.create_role(data_empty, user_id=1, hospital_id=101)
    assert res_empty.base_role_type is None
    service.repo.clone_role_permissions.assert_not_called()


@pytest.mark.asyncio
async def test_custom_role_with_additive_overrides():
    """Verify additive override expands effective permissions."""
    mock_db = AsyncMock(spec=AsyncSession)
    repo = RBACRepository(mock_db)

    # Base permissions from cloned doctor archetype
    base_perms = ["clinical_records:create", "clinical_records:read", "prescriptions:create"]
    repo.get_user_permissions = AsyncMock(return_value=base_perms)

    # Mock DB query for overrides: billing:read added (is_granted=True)
    mock_result = MagicMock()
    mock_result.all.return_value = [("billing:read", True)]
    mock_db.execute = AsyncMock(return_value=mock_result)

    effective = await repo.get_user_effective_permissions(role_id=50, hospital_id=101)

    assert "clinical_records:create" in effective
    assert "billing:read" in effective  # Additive override granted


@pytest.mark.asyncio
async def test_custom_role_with_subtractive_overrides():
    """Verify subtractive override revokes a baseline permission."""
    mock_db = AsyncMock(spec=AsyncSession)
    repo = RBACRepository(mock_db)

    base_perms = ["clinical_records:create", "clinical_records:read", "clinical_records:delete"]
    repo.get_user_permissions = AsyncMock(return_value=base_perms)

    # Mock DB query for overrides: clinical_records:delete revoked (is_granted=False)
    mock_result = MagicMock()
    mock_result.all.return_value = [("clinical_records:delete", False)]
    mock_db.execute = AsyncMock(return_value=mock_result)

    effective = await repo.get_user_effective_permissions(role_id=50, hospital_id=101)

    assert "clinical_records:create" in effective
    assert "clinical_records:delete" not in effective  # Explicitly revoked


@pytest.mark.asyncio
async def test_set_role_override_validations():
    """Verify validation on role override (system role immutable, cross-hospital forbidden, missing permission)."""
    mock_db = AsyncMock(spec=AsyncSession)
    service = RBACService(mock_db)

    # 1. System role cannot be overridden
    sys_role = Role(id=7, name="Doctor", is_system=True, hospital_id=None)
    service.repo.get_role_by_id = AsyncMock(return_value=sys_role)
    with pytest.raises(BadRequestException) as exc:
        await service.set_role_override(
            hospital_id=101,
            role_id=7,
            permission_id=1,
            is_granted=True,
            user_id=1,
        )
    assert "Cannot set overrides on immutable system roles" in str(exc.value)

    # 2. Cross-hospital role override forbidden
    other_hosp_role = Role(id=60, name="Other Doc", is_system=False, hospital_id=102)
    service.repo.get_role_by_id = AsyncMock(return_value=other_hosp_role)
    with pytest.raises(ForbiddenException) as exc_cross:
        await service.set_role_override(
            hospital_id=101,
            role_id=60,
            permission_id=1,
            is_granted=True,
            user_id=1,
        )
    assert "Cannot set overrides for another hospital's role" in str(exc_cross.value)

    # 3. Missing permission
    my_role = Role(id=50, name="My Doc", is_system=False, hospital_id=101)
    service.repo.get_role_by_id = AsyncMock(return_value=my_role)
    service.repo.get_permission_by_id = AsyncMock(return_value=None)
    with pytest.raises(NotFoundException) as exc_perm:
        await service.set_role_override(
            hospital_id=101,
            role_id=50,
            permission_id=9999,
            is_granted=True,
            user_id=1,
        )
    assert "Permission not found" in str(exc_perm.value)


@pytest.mark.asyncio
async def test_system_role_and_cross_hospital_update_delete_protection():
    """Verify system roles cannot be modified or deleted, and cross-hospital operations are forbidden."""
    mock_db = AsyncMock(spec=AsyncSession)
    service = RBACService(mock_db)

    sys_role = Role(id=7, name="Doctor", is_system=True, hospital_id=None)
    service.repo.get_role_by_id = AsyncMock(return_value=sys_role)

    # Attempt to update system role
    with pytest.raises(BadRequestException) as exc_up:
        await service.update_role(role_id=7, data=RoleUpdate(description="Hacked"), user_id=1, hospital_id=101)
    assert "System roles cannot be modified" in str(exc_up.value)

    # Attempt to delete system role
    with pytest.raises(BadRequestException) as exc_del:
        await service.delete_role(role_id=7, user_id=1, hospital_id=101)
    assert "System roles cannot be deleted" in str(exc_del.value)

    # Cross-hospital role update
    other_role = Role(id=60, name="Other Doc", is_system=False, hospital_id=102)
    service.repo.get_role_by_id = AsyncMock(return_value=other_role)
    with pytest.raises(ForbiddenException):
        await service.update_role(role_id=60, data=RoleUpdate(description="Hacked"), user_id=1, hospital_id=101)

    # Cross-hospital role delete
    with pytest.raises(ForbiddenException):
        await service.delete_role(role_id=60, user_id=1, hospital_id=101)


@pytest.mark.asyncio
async def test_module_entitlement_disabled_blocks_permission():
    """Verify require_permission blocks access when module entitlement is disabled even if user has permission."""
    mock_db = AsyncMock(spec=AsyncSession)
    user = User(id=10, hospital_id=101, role_id=50, is_active=True)
    user.role = Role(id=50, name="Doctor", is_system=False, hospital_id=101)

    # User has effective permission appointments:create
    with patch(
        "app.repositories.rbac_repository.RBACRepository.get_user_effective_permissions",
        new_callable=AsyncMock,
        return_value={"appointments:create"},
    ), patch(
        "app.services.module_service.ModuleService.is_module_active",
        new_callable=AsyncMock,
        return_value=False,  # Module is deactivated for this hospital!
    ):
        checker = require_permission("appointments", "create")
        with pytest.raises(ForbiddenException) as exc:
            await checker(db=mock_db, user=user)
        assert "is not activated for this hospital" in str(exc.value)


@pytest.mark.asyncio
async def test_existing_custom_role_compatibility():
    """Verify that existing custom roles without base archetype retain their empty effective permissions."""
    mock_db = AsyncMock(spec=AsyncSession)
    repo = RBACRepository(mock_db)

    # Existing custom role 34 (PAT_NOTIF) has no direct permissions and no overrides
    repo.get_user_permissions = AsyncMock(return_value=[])
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    effective = await repo.get_user_effective_permissions(role_id=34, hospital_id=None)
    assert effective == set()
