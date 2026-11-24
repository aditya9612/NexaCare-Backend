import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import UserRole
from app.core.exceptions import BadRequestException, ForbiddenException
from app.models.hospital_model import Hospital
from app.models.role_model import Role
from app.models.user_model import User
from app.services.module_service import (
    ALL_MODULES,
    COMMERCIAL_MODULES,
    FOUNDATIONAL_MODULES,
    ModuleService,
)
from app.services.rbac_service import RBACService
from app.schemas.rbac_schema import RoleCreate


@pytest.mark.asyncio
async def test_module_catalog_has_18_canonical_modules():
    assert len(ALL_MODULES) == 18
    assert len(FOUNDATIONAL_MODULES) == 14
    assert len(COMMERCIAL_MODULES) == 4
    assert "ICU_TELEMETRY" in FOUNDATIONAL_MODULES
    assert "VOICE_ASSISTANT" in COMMERCIAL_MODULES
    assert "VOICE_REMIND" in COMMERCIAL_MODULES
    assert "AI_ASSISTANT" in COMMERCIAL_MODULES
    assert "WHATSAPP" in COMMERCIAL_MODULES


@pytest.mark.asyncio
async def test_prerequisite_dag_validation():
    mock_db = AsyncMock(spec=AsyncSession)
    service = ModuleService(mock_db)

    # APPOINTMENTS requires PATIENT_MGMT and DOCTOR_MGMT
    with pytest.raises(BadRequestException) as exc:
        service.validate_prerequisites("APPOINTMENTS", {"PATIENT_MGMT"})
    assert "DOCTOR_MGMT" in str(exc.value)

    # Valid prerequisites
    service.validate_prerequisites("APPOINTMENTS", {"PATIENT_MGMT", "DOCTOR_MGMT"})

    # VOICE_REMIND requires APPOINTMENTS
    with pytest.raises(BadRequestException):
        service.validate_prerequisites("VOICE_REMIND", set())
    service.validate_prerequisites("VOICE_REMIND", {"APPOINTMENTS"})

    # VOICE_ASSISTANT requires VOICE_REMIND
    with pytest.raises(BadRequestException):
        service.validate_prerequisites("VOICE_ASSISTANT", set())
    service.validate_prerequisites("VOICE_ASSISTANT", {"VOICE_REMIND"})


@pytest.mark.asyncio
async def test_foundational_module_grandfathered_by_default():
    mock_db = AsyncMock(spec=AsyncSession)
    service = ModuleService(mock_db)

    # Mock DB repo returning empty set (simulating hospital without rows)
    service.repo.get_active_module_codes = AsyncMock(return_value=set())

    # Foundational module returns True by default
    is_patient_active = await service.is_module_active(101, "PATIENT_MGMT")
    assert is_patient_active is True

    # Commercial module returns False by default
    is_voice_active = await service.is_module_active(101, "VOICE_REMIND")
    assert is_voice_active is False

    # Global Super Admin request (hospital_id=None) always returns True
    assert await service.is_module_active(None, "VOICE_REMIND") is True


@pytest.mark.asyncio
async def test_custom_role_scoped_to_hospital():
    mock_db = AsyncMock(spec=AsyncSession)
    rbac_service = RBACService(mock_db)

    rbac_service.repo.get_role_by_name = AsyncMock(return_value=None)
    created_role = Role(
        id=99,
        name="Senior Triage Nurse",
        hospital_id=101,
        base_role_type="NURSE",
        is_system=False,
    )
    rbac_service.repo.create_role = AsyncMock(return_value=created_role)

    role_data = RoleCreate(
        name="Senior Triage Nurse",
        base_role_type="NURSE",
        description="Custom oncology nurse",
    )
    res = await rbac_service.create_role(role_data, user_id=1, hospital_id=101)

    assert res.id == 99
    assert res.hospital_id == 101
    assert res.base_role_type == "NURSE"
    assert res.is_system is False


@pytest.mark.asyncio
async def test_base_role_type_archetype_matching():
    from app.core.dependencies import require_roles

    custom_doctor_role = Role(id=50, name="Junior Resident", base_role_type="DOCTOR", is_system=False)
    user = User(id=10, email="resident@hospital.com", role=custom_doctor_role, is_active=True)

    # Should match require_roles(DOCTOR) via base_role_type
    checker = require_roles(UserRole.DOCTOR)
    checked_user = await checker(user=user)
    assert checked_user.id == 10

    # Non-matching role should raise ForbiddenException
    checker_nurse = require_roles(UserRole.NURSE, allow_admin=False)
    with pytest.raises(ForbiddenException):
        await checker_nurse(user=user)


@pytest.mark.asyncio
async def test_require_permission_with_delta_overrides():
    from app.core.dependencies import require_permission

    mock_db = AsyncMock(spec=AsyncSession)
    user = User(id=10, hospital_id=101, role_id=5, is_active=True)
    user.role = Role(id=5, name="Doctor", is_system=True)

    # Mock effective permissions: has clinical_records:create, but clinical_records:delete is revoked
    with patch(
        "app.repositories.rbac_repository.RBACRepository.get_user_effective_permissions",
        new_callable=AsyncMock,
        return_value={"clinical_records:create", "clinical_records:update"},
    ), patch(
        "app.services.module_service.ModuleService.is_module_active",
        new_callable=AsyncMock,
        return_value=True,
    ):
        checker_create = require_permission("clinical_records", "create")
        res_user = await checker_create(db=mock_db, user=user)
        assert res_user.id == 10

        checker_delete = require_permission("clinical_records", "delete")
        with pytest.raises(ForbiddenException) as exc:
            await checker_delete(db=mock_db, user=user)
        assert "Missing permission: clinical_records:delete" in str(exc.value)


@pytest.mark.asyncio
async def test_hospital_admin_clinical_bypass_eliminated():
    from app.core.dependencies import require_permission

    mock_db = AsyncMock(spec=AsyncSession)
    hosp_admin_user = User(id=2, hospital_id=101, is_active=True)
    hosp_admin_user.role = Role(id=4, name="Hospital Admin", is_system=True)

    with patch(
        "app.repositories.rbac_repository.RBACRepository.get_user_effective_permissions",
        new_callable=AsyncMock,
        return_value=set(),
    ), patch(
        "app.services.module_service.ModuleService.is_module_active",
        new_callable=AsyncMock,
        return_value=True,
    ):
        # Hospital Admin can access administrative / billing read by default
        admin_checker = require_permission("billing", "read")
        res_user = await admin_checker(db=mock_db, user=hosp_admin_user)
        assert res_user.id == 2

        # Hospital Admin CANNOT perform clinical note creation without explicit clinical permission!
        clinical_checker = require_permission("clinical_records", "create")
        with pytest.raises(ForbiddenException):
            await clinical_checker(db=mock_db, user=hosp_admin_user)


@pytest.mark.asyncio
async def test_celery_voice_call_aborted_when_module_inactive():
    from app.models.voice_model import VoiceCall
    from app.tasks.voice_tasks import _execute_voice_call

    call_obj = VoiceCall(id=77, hospital_id=101, call_status="SCHEDULED")

    with patch("app.tasks.voice_tasks.AsyncSessionLocal") as mock_session_local:
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=call_obj)
        mock_session_local.return_value.__aenter__.return_value = mock_session

        with patch("app.services.module_service.ModuleService.is_module_active", new_callable=AsyncMock, return_value=False):
            await _execute_voice_call(77)

            # Call status should be updated to CANCELLED_NOT_ENTITLED and committed
            assert call_obj.call_status == "CANCELLED_NOT_ENTITLED"
            mock_session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_celery_whatsapp_send_aborted_when_module_inactive():
    from app.models.whatsapp_model import WhatsAppMessage
    from app.models.patient_model import Patient
    from app.tasks.whatsapp_tasks import _send_message

    msg_obj = WhatsAppMessage(id=88, patient_id=500, delivery_status="PENDING")
    patient_obj = Patient(id=500, hospital_id=101)

    with patch("app.tasks.whatsapp_tasks.AsyncSessionLocal") as mock_session_local:
        mock_session = AsyncMock()
        def get_side_effect(model, pk):
            if model == WhatsAppMessage:
                return msg_obj
            if model == Patient:
                return patient_obj
            return None
        mock_session.get = AsyncMock(side_effect=get_side_effect)
        mock_session_local.return_value.__aenter__.return_value = mock_session

        with patch("app.services.module_service.ModuleService.is_module_active", new_callable=AsyncMock, return_value=False):
            await _send_message(88)

            assert msg_obj.delivery_status == "CANCELLED_NOT_ENTITLED"
            mock_session.commit.assert_awaited()
