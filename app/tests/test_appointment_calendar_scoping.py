from datetime import date, time, datetime
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sqlalchemy import select

from app.models.appointment_model import Appointment
from app.models.doctor_model import Doctor
from app.models.patient_model import Patient
from app.models.role_model import Role
from app.models.user_model import User
from app.repositories.appointment_repository import AppointmentRepository
from app.services.appointment_service import AppointmentService


def _create_mock_user(user_id: int, role_name: str, hospital_id: int | None = None) -> User:
    role = MagicMock(spec=Role)
    role.name = role_name
    user = MagicMock(spec=User)
    user.id = user_id
    user.role = role
    user.hospital_id = hospital_id
    return user


def _create_dummy_appointment(appt_id: int, doctor_id: int, patient_id: int, appt_date: date) -> Appointment:
    appt = Appointment(
        id=appt_id,
        appointment_number=f"APT-{appt_id}",
        doctor_id=doctor_id,
        patient_id=patient_id,
        department_id=1,
        appointment_date=appt_date,
        appointment_time=time(10, 0),
        appointment_type="OPD",
        booking_source="staff",
        appointment_status="Confirmed",
        symptoms=None,
        notes=None,
        token_number=1,
        consultation_type="in_person",
        reminder_sent=False,
        created_at=datetime(2026, 10, 1, 10, 0),
        updated_at=None,
        check_in_time=None,
        check_out_time=None,
        queue_token=None,
        queue_status=None,
        admission_status=None,
        admission_number=None,
        admission_recommended=False,
        admission_reason=None,
        expected_los=None,
        recommended_ward=None,
        triage_level=None,
        triage_notes=None,
        disposition=None,
        referred_to=None,
        referral_reason=None,
    )
    return appt


# ==============================================================================
# Service Level Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_doctor_sees_only_own_appointments():
    """Logged-in Doctor should automatically have their appointments scoped to their doctor_id."""
    mock_db = AsyncMock()
    service = AppointmentService(mock_db)

    doctor_user = _create_mock_user(user_id=101, role_name="Doctor")
    mock_doctor = MagicMock(spec=Doctor)
    mock_doctor.id = 12
    mock_doctor.user_id = 101

    service.doctor_repo.get_by_user_id = AsyncMock(return_value=mock_doctor)
    dummy_appt = _create_dummy_appointment(appt_id=1, doctor_id=12, patient_id=1, appt_date=date(2026, 10, 10))
    service.repo.get_calendar = AsyncMock(return_value=[dummy_appt])

    start = date(2026, 10, 1)
    end = date(2026, 10, 31)
    results = await service.get_calendar(start_date=start, end_date=end, current_user=doctor_user)

    service.doctor_repo.get_by_user_id.assert_awaited_once_with(101)
    service.repo.get_calendar.assert_awaited_once_with(
        start_date=start,
        end_date=end,
        doctor_id=12,
        patient_id=None,
    )
    assert len(results) == 1
    assert results[0].doctor_id == 12


@pytest.mark.asyncio
async def test_doctor_querying_other_doctor_is_blocked():
    """Logged-in Doctor cannot access another doctor's appointments even if explicit doctor_id is passed."""
    mock_db = AsyncMock()
    service = AppointmentService(mock_db)

    doctor_user = _create_mock_user(user_id=101, role_name="Doctor")
    mock_doctor = MagicMock(spec=Doctor)
    mock_doctor.id = 12
    mock_doctor.user_id = 101

    service.doctor_repo.get_by_user_id = AsyncMock(return_value=mock_doctor)
    service.repo.get_calendar = AsyncMock()

    start = date(2026, 10, 1)
    end = date(2026, 10, 31)
    # Doctor 12 queries doctor 99 (another doctor)
    results = await service.get_calendar(
        start_date=start,
        end_date=end,
        doctor_id=99,
        current_user=doctor_user,
    )

    assert results == []
    service.repo.get_calendar.assert_not_called()


@pytest.mark.asyncio
async def test_doctor_user_without_doctor_profile_returns_empty():
    """If Doctor user has no associated doctor row in DB, returns empty list."""
    mock_db = AsyncMock()
    service = AppointmentService(mock_db)

    doctor_user = _create_mock_user(user_id=999, role_name="Doctor")
    service.doctor_repo.get_by_user_id = AsyncMock(return_value=None)
    service.repo.get_calendar = AsyncMock()

    results = await service.get_calendar(
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 31),
        current_user=doctor_user,
    )

    assert results == []
    service.repo.get_calendar.assert_not_called()


@pytest.mark.asyncio
async def test_patient_sees_only_own_appointments():
    """Logged-in Patient should be scoped to their resolved patient IDs."""
    mock_db = AsyncMock()
    service = AppointmentService(mock_db)

    patient_user = _create_mock_user(user_id=202, role_name="Patient")
    dummy_appt = _create_dummy_appointment(appt_id=2, doctor_id=15, patient_id=5, appt_date=date(2026, 10, 15))
    service.repo.get_calendar = AsyncMock(return_value=[dummy_appt])

    start = date(2026, 10, 1)
    end = date(2026, 10, 31)

    with patch("app.services.patient_service.PatientService._resolve_allowed_patient_ids", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.return_value = [5, 6]

        results = await service.get_calendar(start_date=start, end_date=end, current_user=patient_user)

        service.repo.get_calendar.assert_awaited_once_with(
            start_date=start,
            end_date=end,
            doctor_id=None,
            patient_id=[5, 6],
        )
        assert len(results) == 1
        assert results[0].patient_id == 5


@pytest.mark.asyncio
async def test_patient_with_explicit_doctor_filter():
    """Logged-in Patient filtering by a specific doctor gets scoped by both patient_id and doctor_id."""
    mock_db = AsyncMock()
    service = AppointmentService(mock_db)

    patient_user = _create_mock_user(user_id=202, role_name="Patient")
    dummy_appt = _create_dummy_appointment(appt_id=3, doctor_id=20, patient_id=5, appt_date=date(2026, 10, 20))
    service.repo.get_calendar = AsyncMock(return_value=[dummy_appt])

    start = date(2026, 10, 1)
    end = date(2026, 10, 31)

    with patch("app.services.patient_service.PatientService._resolve_allowed_patient_ids", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.return_value = [5]

        results = await service.get_calendar(
            start_date=start,
            end_date=end,
            doctor_id=20,
            current_user=patient_user,
        )

        service.repo.get_calendar.assert_awaited_once_with(
            start_date=start,
            end_date=end,
            doctor_id=20,
            patient_id=[5],
        )
        assert len(results) == 1
        assert results[0].doctor_id == 20


@pytest.mark.asyncio
async def test_patient_without_allowed_patient_ids_returns_empty():
    """If Patient user has no allowed patient records, returns empty list without querying."""
    mock_db = AsyncMock()
    service = AppointmentService(mock_db)

    patient_user = _create_mock_user(user_id=303, role_name="Patient")
    service.repo.get_calendar = AsyncMock()

    with patch("app.services.patient_service.PatientService._resolve_allowed_patient_ids", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.return_value = []

        results = await service.get_calendar(
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 31),
            current_user=patient_user,
        )

        assert results == []
        service.repo.get_calendar.assert_not_called()


@pytest.mark.asyncio
async def test_admin_role_preserves_unscoped_calendar_behavior():
    """Admin / non-scoped role retains previous behavior (optional doctor_id, no patient constraint)."""
    mock_db = AsyncMock()
    service = AppointmentService(mock_db)

    admin_user = _create_mock_user(user_id=1, role_name="Hospital Admin")
    dummy_appt = _create_dummy_appointment(appt_id=4, doctor_id=7, patient_id=99, appt_date=date(2026, 10, 5))
    service.repo.get_calendar = AsyncMock(return_value=[dummy_appt])

    start = date(2026, 10, 1)
    end = date(2026, 10, 31)

    # 1. Without doctor_id
    await service.get_calendar(start_date=start, end_date=end, current_user=admin_user)
    service.repo.get_calendar.assert_awaited_with(
        start_date=start,
        end_date=end,
        doctor_id=None,
        patient_id=None,
    )

    # 2. With explicit doctor_id
    await service.get_calendar(start_date=start, end_date=end, doctor_id=7, current_user=admin_user)
    service.repo.get_calendar.assert_awaited_with(
        start_date=start,
        end_date=end,
        doctor_id=7,
        patient_id=None,
    )


# ==============================================================================
# Repository Level SQL Verification Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_repo_get_calendar_sql_structure():
    """Verify repository executes query with correct WHERE conditions and joined loads."""
    mock_db = AsyncMock()
    repo = AppointmentRepository(mock_db)

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    start = date(2026, 10, 1)
    end = date(2026, 10, 15)

    # Call with doctor_id and patient_id list
    await repo.get_calendar(start_date=start, end_date=end, doctor_id=42, patient_id=[10, 20])

    mock_db.execute.assert_awaited_once()
    called_query = mock_db.execute.call_args[0][0]
    compiled_sql = str(called_query.compile(compile_kwargs={"literal_binds": True})).lower()

    # Verify date range
    assert "appointments.appointment_date >= '2026-10-01'" in compiled_sql
    assert "appointments.appointment_date <= '2026-10-15'" in compiled_sql
    # Verify doctor_id
    assert "appointments.doctor_id = 42" in compiled_sql
    # Verify patient_id in (10, 20)
    assert "appointments.patient_id in (10, 20)" in compiled_sql


@pytest.mark.asyncio
async def test_repo_get_calendar_empty_patient_id_returns_empty_list():
    """Repository immediately returns empty list if an empty patient_id list is passed."""
    mock_db = AsyncMock()
    repo = AppointmentRepository(mock_db)

    results = await repo.get_calendar(
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 15),
        patient_id=[],
    )

    assert results == []
    mock_db.execute.assert_not_called()


# ==============================================================================
# Route Layer Verification Test
# ==============================================================================

@pytest.mark.asyncio
async def test_calendar_route_passes_current_user_to_service():
    """Route must pass current_user to AppointmentService.get_calendar."""
    from app.api.v1.routes.appointment_routes import calendar_view

    mock_db = AsyncMock()
    current_user = _create_mock_user(user_id=55, role_name="Doctor")

    with patch.object(AppointmentService, "get_calendar", new_callable=AsyncMock) as mock_get_calendar:
        mock_get_calendar.return_value = []

        response = await calendar_view(
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 7),
            db=mock_db,
            current_user=current_user,
            doctor_id=None,
            _=current_user,
        )

        mock_get_calendar.assert_awaited_once_with(
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 7),
            doctor_id=None,
            current_user=current_user,
        )
        assert response.message == "Calendar data"
        assert response.data == []
