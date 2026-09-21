import pytest
from unittest.mock import AsyncMock, MagicMock
from app.core.exceptions import BadRequestException
from app.models.lab_model import LabTest
from app.repositories.lab_repository import LabTestRepository
from app.schemas.lab_schema import LabTestCreate
from app.services.lab_service import LabService


@pytest.mark.asyncio
async def test_create_lab_test_success_when_unique():
    mock_db = AsyncMock()
    service = LabService(mock_db)

    service._validate_department = AsyncMock()
    service._validate_doctor_department = AsyncMock()
    service._is_admin_user = AsyncMock(return_value=True)

    from datetime import datetime
    new_test = LabTest(
        id=10,
        test_code="LT010",
        test_name="Unique Lab Test",
        category="General",
        price=300.0,
        sample_type="blood",
        turnaround_hours=24,
        is_active=True,
        is_deleted=False,
        created_at=datetime(2026, 9, 18, 10, 0, 0),
        updated_at=datetime(2026, 9, 18, 10, 0, 0),
    )
    service.test_repo = AsyncMock()
    service.test_repo.get_by_name.return_value = None
    service.test_repo.create.return_value = new_test
    service.audit_repo = AsyncMock()

    payload = LabTestCreate(
        test_name="Unique Lab Test",
        category="General",
        price=300.0,
        department_id=1,
    )

    result = await service.create_test(payload, user_id=1)
    assert result.test_name == "Unique Lab Test"
    service.test_repo.get_by_name.assert_called_once_with("Unique Lab Test")


@pytest.mark.asyncio
async def test_create_lab_test_duplicate_name_raises_bad_request():
    mock_db = AsyncMock()
    service = LabService(mock_db)
    
    service._validate_department = AsyncMock()
    service._validate_doctor_department = AsyncMock()
    service._is_admin_user = AsyncMock(return_value=True)

    existing_test = LabTest(id=1, test_code="LT001", test_name="Complete Blood Count", is_deleted=False)
    service.test_repo = AsyncMock()
    service.test_repo.get_by_name.return_value = existing_test

    payload = LabTestCreate(
        test_name="complete blood count",
        category="Hematology",
        price=500.0,
        department_id=1,
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.create_test(payload, user_id=1)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "A lab test with this name already exists."
    service.test_repo.get_by_name.assert_called_once_with("complete blood count")


@pytest.mark.asyncio
async def test_repository_get_by_name_multiple_rows_does_not_raise_multiple_results_found():
    """Verify that get_by_name uses scalars().first() and does not raise MultipleResultsFound when multiple duplicate rows exist."""
    test1 = LabTest(id=1, test_code="LT001", test_name="Duplicate Test", is_deleted=False)
    test2 = LabTest(id=2, test_code="LT002", test_name="Duplicate Test", is_deleted=False)

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = test1

    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    repo = LabTestRepository(mock_db)
    result = await repo.get_by_name("Duplicate Test")

    assert result == test1
    mock_db.execute.assert_called_once()
