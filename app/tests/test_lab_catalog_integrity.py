import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from app.core.constants import UserRole
from app.core.exceptions import BadRequestException, NotFoundException
from app.models.lab_model import LabTest
from app.models.role_model import Role
from app.models.user_model import User
from app.models.department_model import Department
from app.schemas.lab_schema import LabTestCreate, LabTestUpdate
from app.services.lab_service import LabService
from app.repositories.lab_repository import LabTestRepository
from app.utils.pagination import build_paginated_result

def make_user(role_name: str, user_id: int = 1, hospital_id: int = 1, email: str = "test@example.com"):
    role = Role(id=1, name=role_name)
    user = User(
        id=user_id,
        user_code=f"USR-{user_id}",
        email=email,
        full_name="Test User",
        role_id=1,
        is_active=True,
        is_verified=True,
    )
    user.role = role
    user.hospital_id = hospital_id
    return user

def make_lab_test(test_id: int, name: str, code: str, category: str, dept_id: int | None = None, doc_id: int | None = None, hosp_id: int = 1):
    return LabTest(
        id=test_id,
        test_code=code,
        test_name=name,
        category=category,
        description="description",
        price=100.0,
        sample_type="blood",
        turnaround_hours=24,
        normal_range="Normal",
        is_active=True,
        department_id=dept_id,
        doctor_id=doc_id,
        hospital_id=hosp_id,
        created_at=datetime(2026, 10, 1),
        updated_at=datetime(2026, 10, 1),
    )

@pytest.mark.asyncio
async def test_lab_technician_sees_hospital_catalog_without_forced_restriction():
    db = AsyncMock()
    service = LabService(db)

    lab_tech = make_user("Lab Technician", user_id=123, hospital_id=1, email="tina@gmail.com")

    # Mock repository returning 4 tests (2 with dept_id=4, 2 with dept_id=None)
    mock_items = [
        make_lab_test(1, "Blood Glucose", "TST-01", "Biochemistry", dept_id=4, hosp_id=1),
        make_lab_test(2, "Complete Blood Count", "TST-02", "Hematology", dept_id=4, hosp_id=1),
        make_lab_test(3, "Total Bilirubin 3", "TST-03", "Microbiology", dept_id=None, hosp_id=1),
        make_lab_test(4, "Serum Albumin 3", "TST-04", "Immunology", dept_id=None, hosp_id=1),
    ]
    service.test_repo.list_all = AsyncMock(return_value=mock_items)
    service.test_repo.count_all = AsyncMock(return_value=4)

    res = await service.list_tests(page=1, size=20, current_user=lab_tech)

    assert len(res.items) == 4
    assert res.total == 4
    # Ensure hospital_id resolved to 1
    service.test_repo.list_all.assert_called_once()
    kwargs = service.test_repo.list_all.call_args.kwargs
    assert kwargs["hospital_id"] == 1
    assert kwargs["department_id"] is None

@pytest.mark.asyncio
async def test_hospital_admin_sees_all_hospital_tests():
    db = AsyncMock()
    service = LabService(db)

    hosp_admin = make_user(UserRole.HOSPITAL_ADMIN, user_id=168, hospital_id=1, email="hospital1.admin@nexacare.com")

    mock_items = [
        make_lab_test(1, "Blood Glucose", "TST-01", "Biochemistry", dept_id=4, hosp_id=1),
        make_lab_test(2, "Complete Blood Count", "TST-02", "Hematology", dept_id=4, hosp_id=1),
        make_lab_test(3, "Total Bilirubin 3", "TST-03", "Microbiology", dept_id=None, hosp_id=1),
        make_lab_test(4, "Serum Albumin 3", "TST-04", "Immunology", dept_id=None, hosp_id=1),
    ]
    service.test_repo.list_all = AsyncMock(return_value=mock_items)
    service.test_repo.count_all = AsyncMock(return_value=4)

    res = await service.list_tests(page=1, size=20, current_user=hosp_admin)

    assert len(res.items) == 4
    assert res.total == 4
    kwargs = service.test_repo.list_all.call_args.kwargs
    assert kwargs["hospital_id"] == 1
    assert kwargs["department_id"] is None

@pytest.mark.asyncio
async def test_optional_department_filter_is_passed_when_requested():
    db = AsyncMock()
    service = LabService(db)

    lab_tech = make_user("Lab Technician", user_id=123, hospital_id=1)
    service.test_repo.list_all = AsyncMock(return_value=[])
    service.test_repo.count_all = AsyncMock(return_value=0)

    # When explicit department_id is passed as query param
    await service.list_tests(page=1, size=20, department_id=4, current_user=lab_tech)

    kwargs = service.test_repo.list_all.call_args.kwargs
    assert kwargs["department_id"] == 4
    assert kwargs["hospital_id"] == 1

@pytest.mark.asyncio
async def test_create_test_without_department_id_succeeds():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute.return_value = mock_result
    service = LabService(db)

    lab_tech = make_user("Lab Technician", user_id=123, hospital_id=1)
    data = LabTestCreate(
        test_name="New Culture Test",
        category="Microbiology",
        price=450.0,
        sample_type="urine",
        turnaround_hours=48,
    )

    service.test_repo.get_by_name = AsyncMock(return_value=None)
    created_test = make_lab_test(10, "New Culture Test", "TST-10", "Microbiology", dept_id=None, hosp_id=1)
    service.test_repo.create = AsyncMock(return_value=created_test)
    service.audit_repo.create = AsyncMock()

    res = await service.create_test(data, user_id=lab_tech.id, current_user=lab_tech)

    assert res.id == 10
    assert res.test_name == "New Culture Test"
    assert res.department_id is None
    service.test_repo.create.assert_called_once()
    saved_obj = service.test_repo.create.call_args[0][0]
    assert saved_obj.hospital_id == 1
    assert saved_obj.department_id is None

@pytest.mark.asyncio
async def test_create_test_with_valid_department_id_validates_and_succeeds():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute.return_value = mock_result
    service = LabService(db)
    service._validate_department = AsyncMock()

    lab_tech = make_user("Lab Technician", user_id=123, hospital_id=1)
    data = LabTestCreate(
        test_name="Specific Dept Test",
        category="Biochemistry",
        price=200.0,
        sample_type="blood",
        department_id=4,
    )

    service.test_repo.get_by_name = AsyncMock(return_value=None)
    created_test = make_lab_test(11, "Specific Dept Test", "TST-11", "Biochemistry", dept_id=4, hosp_id=1)
    service.test_repo.create = AsyncMock(return_value=created_test)
    service.audit_repo.create = AsyncMock()

    res = await service.create_test(data, user_id=lab_tech.id, current_user=lab_tech)

    assert res.department_id == 4
    service._validate_department.assert_called_once_with(4)

@pytest.mark.asyncio
async def test_create_test_with_invalid_department_id_fails():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute.return_value = mock_result
    service = LabService(db)
    service._validate_department = AsyncMock(side_effect=NotFoundException("Department not found"))

    lab_tech = make_user("Lab Technician", user_id=123, hospital_id=1)
    data = LabTestCreate(
        test_name="Invalid Dept Test",
        category="Biochemistry",
        department_id=9999,
    )

    service.test_repo.get_by_name = AsyncMock(return_value=None)

    with pytest.raises(NotFoundException, match="Department not found"):
        await service.create_test(data, user_id=lab_tech.id, current_user=lab_tech)

@pytest.mark.asyncio
async def test_search_tests_tenant_and_doctor_scoping():
    db = AsyncMock()
    service = LabService(db)

    doc_user = make_user("Doctor", user_id=50, hospital_id=1)
    service.test_repo.search = AsyncMock(return_value=[])
    service.test_repo.count_search = AsyncMock(return_value=0)

    await service.search_tests("glucose", page=1, size=10, doctor_id=15, current_user=doc_user)

    kwargs = service.test_repo.search.call_args.kwargs
    assert kwargs["hospital_id"] == 1
    assert kwargs["doctor_id"] == 15
    assert kwargs["department_id"] is None
