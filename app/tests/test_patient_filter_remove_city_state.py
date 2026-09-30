import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock

from app.main import app
from app.core.dependencies import get_current_active_user, get_current_user
from app.schemas.patient_schema import PatientResponse
from app.utils.pagination import build_paginated_result


@pytest.mark.asyncio
async def test_openapi_schema_patient_filter_city_state_removed():
    """Verify that city and state parameters are absent from OpenAPI schema for GET /api/v1/patients/filter."""
    openapi = app.openapi()
    filter_path = openapi["paths"].get("/api/v1/patients/filter")
    assert filter_path is not None, "Endpoint /api/v1/patients/filter must exist in OpenAPI schema"

    get_op = filter_path.get("get")
    assert get_op is not None, "GET operation for /api/v1/patients/filter must exist"

    param_names = [p["name"] for p in get_op.get("parameters", []) if p["in"] == "query"]
    
    assert "city" not in param_names, "'city' should not be present in OpenAPI query parameters for /api/v1/patients/filter"
    assert "state" not in param_names, "'state' should not be present in OpenAPI query parameters for /api/v1/patients/filter"

    # Confirm expected filter parameters exist
    for expected_param in ["gender", "blood_group", "status", "page", "size"]:
        assert expected_param in param_names, f"Expected '{expected_param}' query parameter to be present in OpenAPI schema"


@pytest.mark.asyncio
async def test_filter_patients_endpoint_execution():
    """Verify that GET /api/v1/patients/filter works properly with remaining filters and does not pass city/state."""
    class FakeUser:
        id = 9998
        role_id = 1
        hospital_id = 1
        is_active = True
        is_verified = True
        email = "admin_filter_test@test.com"

        class role:
            name = "super_admin"

    fake_user = FakeUser()
    app.dependency_overrides[get_current_active_user] = lambda: fake_user
    app.dependency_overrides[get_current_user] = lambda: fake_user

    mock_patient = PatientResponse.model_construct(
        id=101,
        patient_code="PAT_101",
        first_name="John",
        last_name="Doe",
        gender="Male",
        blood_group="A+",
        status="active",
        city="Mumbai",
        state="Maharashtra",
        medical_history=None,
        bed_history=[],
    )
    mock_result = build_paginated_result([mock_patient], 1, 1, 10)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with patch("app.core.dependencies.require_permission") as mock_perm:
            mock_perm.return_value = lambda: fake_user
            with patch(
                "app.repositories.rbac_repository.RBACRepository.get_user_permissions",
                new=AsyncMock(return_value=["patients:read"]),
            ):
                with patch("app.api.v1.routes.patient_routes.PatientService") as mock_service_cls:
                    mock_service_inst = mock_service_cls.return_value
                    mock_service_inst.filter_patients = AsyncMock(return_value=mock_result)

                    resp = await ac.get("/api/v1/patients/filter?gender=Male&blood_group=A%2B&status=active&page=1&size=10")

                    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
                    body = resp.json()
                    assert body["success"] is True
                    assert body["data"]["total"] == 1

                    # Verify call kwargs to PatientService.filter_patients
                    mock_service_inst.filter_patients.assert_called_once()
                    kwargs = mock_service_inst.filter_patients.call_args.kwargs

                    assert kwargs["gender"] == "Male"
                    assert kwargs["blood_group"] == "A+"
                    assert kwargs["status"] == "active"
                    assert kwargs["page"] == 1
                    assert kwargs["size"] == 10
                    assert "city" not in kwargs
                    assert "state" not in kwargs

    app.dependency_overrides.clear()
