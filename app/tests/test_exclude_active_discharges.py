import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import select

from app.models.appointment_model import Appointment
from app.repositories.appointment_repository import AppointmentRepository
from app.services.appointment_service import AppointmentService
from app.services.discharge_service import DischargeService
from app.schemas.discharge_schema import DischargeInitiateRequest
from app.core.exceptions import ConflictException


@pytest.fixture
def repo():
    return AppointmentRepository(MagicMock())


# 1. Existing API request without the new parameter must behave exactly as before
def test_unfiltered_query_does_not_contain_not_exists(repo):
    q = repo._apply_filters(select(Appointment), admission_status="Admitted", hospital_id=6)
    compiled = str(q.compile(compile_kwargs={"literal_binds": True}))

    # Must contain admission_status and hospital_id
    assert "appointments.admission_status" in compiled
    assert "appointments.hospital_id = 6" in compiled

    # Must NOT contain discharges subquery
    assert "discharges" not in compiled.lower()
    assert "not (exists" not in compiled.lower()


# 2. With exclude_active_discharges=True, query contains NOT EXISTS subquery with PENDING_CLEARANCES and CLEARED
def test_exclude_active_discharges_sql_structure(repo):
    q = repo._apply_filters(
        select(Appointment),
        admission_status="Admitted",
        hospital_id=6,
        exclude_active_discharges=True,
    )
    compiled = str(q.compile(compile_kwargs={"literal_binds": True}))

    # Must contain NOT EXISTS
    assert "NOT (EXISTS" in compiled or "not (exists" in compiled.lower()
    assert "discharges" in compiled.lower()

    # Must check both PENDING_CLEARANCES and CLEARED
    assert "PENDING_CLEARANCES" in compiled
    assert "CLEARED" in compiled

    # Must check both appointment_id and hospital_id matching
    assert "discharges.appointment_id = appointments.id" in compiled
    assert "discharges.hospital_id = appointments.hospital_id" in compiled


# 3. Verify tenant isolation in NOT EXISTS subquery
def test_tenant_isolation_in_subquery(repo):
    q = repo._apply_filters(
        select(Appointment),
        hospital_id=10,
        exclude_active_discharges=True,
    )
    compiled = str(q.compile(compile_kwargs={"literal_binds": True}))

    # Appointment must have hospital_id filter
    assert "appointments.hospital_id = 10" in compiled
    # Subquery must correlate hospital_id with appointments.hospital_id
    assert "discharges.hospital_id = appointments.hospital_id" in compiled


# 4. Verify Service forwards exclude_active_discharges to Repository list_all and count_all
@pytest.mark.asyncio
async def test_appointment_service_forwards_exclude_active_discharges():
    mock_db = AsyncMock()
    mock_db.scalar = AsyncMock(return_value=0)
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    service = AppointmentService(mock_db)
    service.repo = MagicMock()
    service.repo.list_all = AsyncMock(return_value=[])
    service.repo.count_all = AsyncMock(return_value=0)
    service._resolve_and_validate_tenant_id = AsyncMock(return_value=6)

    with patch("app.repositories.discharge_repository.DischargeRepository.count_today_discharged", new_callable=AsyncMock) as mock_count:
        mock_count.return_value = 0
        await service.list_appointments(
            admission_status="Admitted",
            exclude_active_discharges=True,
            x_hospital_id=6,
        )

    # Check list_all was called with exclude_active_discharges=True
    service.repo.list_all.assert_called_once()
    assert service.repo.list_all.call_args.kwargs.get("exclude_active_discharges") is True

    # Check count_all was called with exclude_active_discharges=True
    service.repo.count_all.assert_any_call(
        patient_id=None,
        doctor_id=None,
        department_id=None,
        status=None,
        appointment_date=None,
        start_date=None,
        end_date=None,
        appointment_type=None,
        booking_source=None,
        admission_status="Admitted",
        triage_level=None,
        disposition=None,
        search=None,
        hospital_id=6,
        exclude_active_discharges=True,
    )


# 5. Verify default exclude_active_discharges is False in Service
@pytest.mark.asyncio
async def test_appointment_service_default_exclude_active_discharges_is_false():
    mock_db = AsyncMock()
    mock_db.scalar = AsyncMock(return_value=0)
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_db.scalars = AsyncMock(return_value=mock_scalars)

    service = AppointmentService(mock_db)
    service.repo = MagicMock()
    service.repo.list_all = AsyncMock(return_value=[])
    service.repo.count_all = AsyncMock(return_value=0)
    service._resolve_and_validate_tenant_id = AsyncMock(return_value=6)

    with patch("app.repositories.discharge_repository.DischargeRepository.count_today_discharged", new_callable=AsyncMock) as mock_count:
        mock_count.return_value = 0
        await service.list_appointments(
            admission_status="Admitted",
            x_hospital_id=6,
        )

    # Check list_all was called with exclude_active_discharges=False
    service.repo.list_all.assert_called_once()
    assert service.repo.list_all.call_args.kwargs.get("exclude_active_discharges") is False


# 6. Verify export_appointments remains clean without exclude_active_discharges
@pytest.mark.asyncio
async def test_appointment_service_export_does_not_modify_clean_interface():
    mock_db = AsyncMock()
    mock_db.scalar = AsyncMock(return_value=0)

    service = AppointmentService(mock_db)
    service.repo = MagicMock()
    service.repo.list_for_export = AsyncMock(return_value=[])
    service._resolve_and_validate_tenant_id = AsyncMock(return_value=6)
    service._generate_excel_export = MagicMock(return_value=b"fake_excel")

    mock_user = MagicMock()
    mock_user.role.name = "admin"

    with patch("app.repositories.hospital_repository.HospitalRepository.get_by_id", new_callable=AsyncMock) as mock_get_hosp:
        mock_get_hosp.return_value = MagicMock(name="Test Hospital", logo_url=None, address=None, phone=None, email=None)
        await service.export_appointments(
            format_type="excel",
            admission_status="Admitted",
            current_user=mock_user,
            x_hospital_id=6,
        )

    service.repo.list_for_export.assert_called_once()
    assert "exclude_active_discharges" not in service.repo.list_for_export.call_args.kwargs


# 7. Verify duplicate initiate_discharge still raises ConflictException (409)
@pytest.mark.asyncio
async def test_duplicate_discharge_initiation_raises_409():
    mock_db = AsyncMock()
    service = DischargeService(mock_db)
    service.repo = MagicMock()

    mock_existing_discharge = MagicMock()
    mock_existing_discharge.discharge_status = "PENDING_CLEARANCES"
    service.repo.get_by_appointment_id = AsyncMock(return_value=mock_existing_discharge)

    mock_appointment = MagicMock()
    mock_appointment.hospital_id = 6
    mock_appointment.admission_status = "Admitted"
    mock_appointment.appointment_status = "In-Progress"
    mock_appointment.patient_id = 103
    mock_appointment.doctor_id = 1

    service.appointment_repo = MagicMock()
    service.appointment_repo.get_by_id = AsyncMock(return_value=mock_appointment)

    req = DischargeInitiateRequest(
        appointment_id=47,
        diagnosis_at_discharge="Recovered",
        treatment_summary="Supportive therapy and hydration",
    )

    with pytest.raises(ConflictException) as exc_info:
        await service.initiate_discharge(req, doctor_user_id=1, hospital_id=6)

    assert "Discharge already initiated for appointment 47" in str(exc_info.value.detail)


# 8. Verify duplicate initiate_discharge with CLEARED status also raises ConflictException (409)
@pytest.mark.asyncio
async def test_cleared_discharge_initiation_raises_409():
    mock_db = AsyncMock()
    service = DischargeService(mock_db)
    service.repo = MagicMock()

    mock_existing_discharge = MagicMock()
    mock_existing_discharge.discharge_status = "CLEARED"
    service.repo.get_by_appointment_id = AsyncMock(return_value=mock_existing_discharge)

    mock_appointment = MagicMock()
    mock_appointment.hospital_id = 6
    mock_appointment.admission_status = "Admitted"
    mock_appointment.appointment_status = "In-Progress"
    mock_appointment.patient_id = 103
    mock_appointment.doctor_id = 1

    service.appointment_repo = MagicMock()
    service.appointment_repo.get_by_id = AsyncMock(return_value=mock_appointment)

    req = DischargeInitiateRequest(
        appointment_id=47,
        diagnosis_at_discharge="Recovered",
        treatment_summary="Supportive therapy and hydration",
    )

    with pytest.raises(ConflictException) as exc_info:
        await service.initiate_discharge(req, doctor_user_id=1, hospital_id=6)

    assert "Discharge already initiated for appointment 47" in str(exc_info.value.detail)
