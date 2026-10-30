from datetime import date, datetime
from unittest.mock import AsyncMock, patch
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.dependencies import get_current_active_user, get_current_user
from app.schemas.patient_schema import PatientCreateResponse, PatientResponse


class FakeUser:
    id = 9991
    role_id = 1
    hospital_id = 1
    is_active = True
    is_verified = True
    email = "admin_patient_test@test.com"

    class role:
        name = "hospital_admin"


@pytest.fixture(autouse=True)
def setup_overrides():
    fake_user = FakeUser()
    app.dependency_overrides[get_current_active_user] = lambda: fake_user
    app.dependency_overrides[get_current_user] = lambda: fake_user
    yield
    app.dependency_overrides.pop(get_current_active_user, None)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_create_patient_multipart_with_weight_and_blood_pressure():
    fake_user = FakeUser()
    mock_response = PatientCreateResponse.model_construct(
        id=201,
        patient_code="PAT_201",
        first_name="Rohan",
        last_name="Sharma",
        diagnosis="Regular Checkup",
        weight=72.5,
        blood_pressure="120/80",
        status="active",
        medical_history=None,
        bed_history=[],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with patch("app.core.dependencies.require_permission") as mock_perm:
            mock_perm.return_value = lambda: fake_user
            with patch("app.api.v1.routes.patient_routes.PatientService") as mock_service_cls:
                mock_service_inst = mock_service_cls.return_value
                mock_service_inst.create = AsyncMock(return_value=mock_response)

                form_data = {
                    "first_name": "Rohan",
                    "last_name": "Sharma",
                    "diagnosis": "Regular Checkup",
                    "weight": "72.5",
                    "blood_pressure": "120/80",
                }
                files = {
                    "consent_form": ("consent.pdf", b"%PDF-dummy content", "application/pdf")
                }

                resp = await ac.post("/api/v1/patients", data=form_data, files=files)
                assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"

                body = resp.json()
                assert body["success"] is True
                assert body["data"]["weight"] == 72.5
                assert body["data"]["blood_pressure"] == "120/80"

                # Verify PatientCreate received by service has parsed weight and blood_pressure
                call_args = mock_service_inst.create.call_args
                patient_data_arg = call_args[0][0]
                assert patient_data_arg.first_name == "Rohan"
                assert patient_data_arg.last_name == "Sharma"
                assert patient_data_arg.diagnosis == "Regular Checkup"
                assert patient_data_arg.weight == 72.5
                assert patient_data_arg.blood_pressure == "120/80"
                assert call_args[1]["consent_file"] is not None


@pytest.mark.asyncio
async def test_create_patient_multipart_optional_empty_weight_and_bp():
    fake_user = FakeUser()
    mock_response = PatientCreateResponse.model_construct(
        id=202,
        patient_code="PAT_202",
        first_name="Priya",
        last_name="Patil",
        diagnosis="Consultation",
        weight=None,
        blood_pressure=None,
        status="active",
        medical_history=None,
        bed_history=[],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with patch("app.core.dependencies.require_permission") as mock_perm:
            mock_perm.return_value = lambda: fake_user
            with patch("app.api.v1.routes.patient_routes.PatientService") as mock_service_cls:
                mock_service_inst = mock_service_cls.return_value
                mock_service_inst.create = AsyncMock(return_value=mock_response)

                form_data = {
                    "first_name": "Priya",
                    "last_name": "Patil",
                    "diagnosis": "Consultation",
                    "weight": "",
                    "blood_pressure": "",
                }

                resp = await ac.post("/api/v1/patients", data=form_data)
                assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"

                call_args = mock_service_inst.create.call_args
                patient_data_arg = call_args[0][0]
                assert patient_data_arg.first_name == "Priya"
                assert patient_data_arg.weight is None
                assert patient_data_arg.blood_pressure is None


@pytest.mark.asyncio
async def test_create_patient_json_with_weight_and_blood_pressure():
    fake_user = FakeUser()
    mock_response = PatientCreateResponse.model_construct(
        id=203,
        patient_code="PAT_203",
        first_name="Amit",
        last_name="Kumar",
        diagnosis="OPD Visit",
        weight=68.0,
        blood_pressure="118/76",
        status="active",
        medical_history=None,
        bed_history=[],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with patch("app.core.dependencies.require_permission") as mock_perm:
            mock_perm.return_value = lambda: fake_user
            with patch("app.api.v1.routes.patient_routes.PatientService") as mock_service_cls:
                mock_service_inst = mock_service_cls.return_value
                mock_service_inst.create = AsyncMock(return_value=mock_response)

                json_payload = {
                    "first_name": "Amit",
                    "last_name": "Kumar",
                    "diagnosis": "OPD Visit",
                    "weight": 68.0,
                    "blood_pressure": "118/76",
                }

                resp = await ac.post("/api/v1/patients", json=json_payload)
                assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"

                call_args = mock_service_inst.create.call_args
                patient_data_arg = call_args[0][0]
                assert patient_data_arg.weight == 68.0
                assert patient_data_arg.blood_pressure == "118/76"


@pytest.mark.asyncio
async def test_update_patient_multipart_with_weight_and_blood_pressure():
    fake_user = FakeUser()
    mock_response = PatientResponse.model_construct(
        id=201,
        patient_code="PAT_201",
        first_name="Rohan",
        last_name="Sharma",
        diagnosis="Regular Checkup",
        weight=75.0,
        blood_pressure="130/85",
        status="active",
        medical_history=None,
        bed_history=[],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with patch("app.core.dependencies.require_permission") as mock_perm:
            mock_perm.return_value = lambda: fake_user
            with patch("app.api.v1.routes.patient_routes.PatientService") as mock_service_cls:
                mock_service_inst = mock_service_cls.return_value
                mock_service_inst.update = AsyncMock(return_value=mock_response)

                form_data = {
                    "weight": "75.0",
                    "blood_pressure": "130/85",
                }

                resp = await ac.put("/api/v1/patients/201", data=form_data)
                assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

                call_args = mock_service_inst.update.call_args
                patient_id_arg = call_args[0][0]
                patient_update_arg = call_args[0][1]
                assert patient_id_arg == 201
                assert patient_update_arg.weight == 75.0
                assert patient_update_arg.blood_pressure == "130/85"
