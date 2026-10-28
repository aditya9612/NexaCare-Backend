import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime

from app.core.constants import LabReportStatus, UserRole
from app.core.dependencies import get_current_active_user, get_current_user
from app.core.exceptions import BadRequestException, ForbiddenException
from app.main import app
from app.models.lab_model import LabReport, TestOrder as LabTestOrder
from app.models.role_model import Role
from app.models.user_model import User
from app.schemas.lab_schema import LabReportApprove, LabReportResponse
from app.services.lab_service import LabService
from app.utils.helpers import utc_now


def build_test_user(role_name: str, user_id: int = 1) -> User:
    role = Role(id=1, name=role_name, description=f"{role_name} role")
    user = User(
        id=user_id,
        user_code=f"U_TEST_{user_id}",
        email=f"user{user_id}@test.com",
        full_name=f"Test {role_name}",
        role_id=role.id,
        is_active=True,
        is_verified=True,
        hashed_password="hashed_password",
    )
    user.role = role
    return user


def override_current_user(user: User):
    async def _get_user():
        return user

    app.dependency_overrides[get_current_active_user] = _get_user
    app.dependency_overrides[get_current_user] = _get_user


def test_lab_report_approve_schema_exposes_only_canonical_remarks():
    """Verify that LabReportApprove request schema exposes only the canonical 'remarks' field
    and does NOT expose the duplicate 'remark' field in its model_fields.
    """
    fields = list(LabReportApprove.model_fields.keys())
    assert "remarks" in fields, "Canonical 'remarks' field must be present in schema fields"
    assert "remark" not in fields, "Duplicate 'remark' field must NOT be in schema fields"
    assert fields == ["approved", "remarks"], f"Expected only ['approved', 'remarks'], got {fields}"

    # Verify instantiation with canonical field
    approve_data = LabReportApprove(approved=True, remarks="Report verified and approved")
    assert approve_data.approved is True
    assert approve_data.remarks == "Report verified and approved"

    # Verify backward-compatibility fallback if someone passes 'remark'
    legacy_data = LabReportApprove.model_validate({"approved": True, "remark": "Legacy remark"})
    assert legacy_data.approved is True
    assert legacy_data.remarks == "Legacy remark"


def test_lab_report_approve_openapi_schema_no_duplicate_remark():
    """Verify that FastAPI generated OpenAPI/Swagger documentation schema for
    PUT /api/v1/lab/reports/{report_id}/approve exposes only 'remarks' and not 'remark'.
    """
    openapi = app.openapi()
    schema_props = openapi["components"]["schemas"]["LabReportApprove"]["properties"]

    assert "remarks" in schema_props, "OpenAPI schema must expose 'remarks'"
    assert "remark" not in schema_props, "OpenAPI schema must NOT expose duplicate 'remark'"
    assert set(schema_props.keys()) == {"approved", "remarks"}

    # Verify the PUT route references LabReportApprove
    route_spec = openapi["paths"]["/api/v1/lab/reports/{report_id}/approve"]["put"]
    req_body_schema = route_spec["requestBody"]["content"]["application/json"]["schema"]
    assert req_body_schema["$ref"] == "#/components/schemas/LabReportApprove"


@pytest.mark.asyncio
async def test_approve_lab_report_api_endpoint(client):
    """Verify that PUT /api/v1/lab/reports/{report_id}/approve:
    1. Accepts the canonical 'remarks' field.
    2. Successfully calls the service with the remarks.
    3. Returns the approved report response with remarks.
    """
    user = build_test_user(UserRole.DOCTOR)
    override_current_user(user)

    now = utc_now()
    mock_response = LabReportResponse(
        id=10,
        test_order_id=5,
        report_number="REP-20261027-0010",
        status="approved",
        summary="Report verified and approved",
        remarks="Report verified and approved",
        doctor_remarks="Report verified and approved",
        technician_remarks="Sample collected and analyzed",
        approved_by=user.id,
        approved_at=now,
        doctor_verified_by=user.id,
        doctor_verified_at=now,
        created_at=now,
    )

    mock_service = AsyncMock()
    mock_service.approve_report = AsyncMock(return_value=mock_response)

    with patch("app.core.dependencies.RBACRepository.get_user_permissions", return_value={"lab:approve"}), \
         patch("app.api.v1.routes.lab_routes.LabService", return_value=mock_service):

        response = await client.put(
            "/api/v1/lab/reports/10/approve",
            json={"approved": True, "remarks": "Report verified and approved"},
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Lab report processed"
        assert data["data"]["status"] == "approved"
        assert data["data"]["remarks"] == "Report verified and approved"
        assert data["data"]["doctor_remarks"] == "Report verified and approved"
        assert data["data"]["approved_by"] == user.id

        # Verify that mock_service.approve_report received LabReportApprove with remarks
        mock_service.approve_report.assert_called_once()
        call_args = mock_service.approve_report.call_args
        assert call_args[0][0] == 10  # report_id
        approve_arg: LabReportApprove = call_args[0][1]
        assert approve_arg.approved is True
        assert approve_arg.remarks == "Report verified and approved"


@pytest.mark.asyncio
async def test_approve_report_service_saves_remarks_to_database():
    """Verify that LabService.approve_report correctly updates report.remarks,
    report.doctor_remarks, and report.summary in the database model.
    """
    mock_db = AsyncMock()
    service = LabService(mock_db)

    doctor_user = build_test_user(UserRole.DOCTOR, user_id=42)

    now = utc_now()
    # Report in TECHNICIAN_VERIFIED state (prerequisite for doctor approval)
    report = LabReport(
        id=15,
        test_order_id=7,
        report_number="REP-TEST-15",
        status=LabReportStatus.TECHNICIAN_VERIFIED,
        technician_verified_by=1,
        technician_verified_at=now,
        technician_remarks="Tech OK",
        remarks=None,
        doctor_remarks=None,
        summary=None,
        created_at=now,
    )

    order = LabTestOrder(
        id=7,
        order_number="ORD-TEST-7",
        patient_id=1,
        doctor_id=42,
        lab_test_id=1,
        status="in_progress",
    )

    service.report_repo = AsyncMock()
    service.report_repo.get_by_id = AsyncMock(return_value=report)
    service.report_repo.update = AsyncMock(side_effect=lambda r: r)

    service.order_repo = AsyncMock()
    service.order_repo.get_by_id = AsyncMock(return_value=order)
    service.order_repo.update = AsyncMock(side_effect=lambda o: o)

    service.audit_repo = AsyncMock()
    service.audit_repo.create = AsyncMock()

    service._generate_report_pdf = AsyncMock(return_value="/reports/REP-TEST-15.pdf")

    approve_data = LabReportApprove(
        approved=True,
        remarks="Excellent report, all parameters within expected range.",
    )

    resp = await service.approve_report(report_id=15, data=approve_data, current_user=doctor_user)

    assert resp.status == LabReportStatus.APPROVED
    assert report.status == LabReportStatus.APPROVED
    assert report.approved_by == 42
    assert report.doctor_verified_by == 42
    assert report.doctor_verified_at is not None
    assert report.approved_at is not None

    # Verify that remarks are saved in report.remarks, report.doctor_remarks, and report.summary
    assert report.remarks == "Excellent report, all parameters within expected range."
    assert report.doctor_remarks == "Excellent report, all parameters within expected range."
    assert report.summary == "Excellent report, all parameters within expected range."

    assert resp.remarks == "Excellent report, all parameters within expected range."
    assert resp.doctor_remarks == "Excellent report, all parameters within expected range."
    assert resp.summary == "Excellent report, all parameters within expected range."


@pytest.mark.asyncio
async def test_approve_lab_report_permission_and_role_authorization(client):
    """Verify authorization constraints:
    1. User without 'lab:approve' permission is rejected with 403 Forbidden.
    2. Non-doctor / non-admin user is rejected with 403 Forbidden.
    """
    # 1. Missing permission
    user = build_test_user(UserRole.DOCTOR)
    override_current_user(user)

    with patch("app.core.dependencies.RBACRepository.get_user_permissions", return_value={"lab:read"}):
        resp = await client.put(
            "/api/v1/lab/reports/1/approve",
            json={"approved": True, "remarks": "Approved"},
        )
        assert resp.status_code == 403, f"Expected 403 when permission missing, got {resp.status_code}"

    # 2. Lab Technician role cannot approve/verify as doctor
    tech_user = build_test_user("Lab Technician")
    override_current_user(tech_user)

    with patch("app.core.dependencies.RBACRepository.get_user_permissions", return_value={"lab:approve"}):
        resp = await client.put(
            "/api/v1/lab/reports/1/approve",
            json={"approved": True, "remarks": "Approved"},
        )
        assert resp.status_code == 403, f"Expected 403 for non-doctor role, got {resp.status_code}"


@pytest.mark.asyncio
async def test_approve_report_requires_technician_verification_first():
    """Verify strict sequential workflow: Report must be TECHNICIAN_VERIFIED first."""
    mock_db = AsyncMock()
    service = LabService(mock_db)
    doctor_user = build_test_user(UserRole.DOCTOR, user_id=42)

    # Draft report (not technician verified)
    draft_report = LabReport(
        id=20,
        test_order_id=8,
        report_number="REP-DRAFT-20",
        status=LabReportStatus.DRAFT,
    )

    service.report_repo = AsyncMock()
    service.report_repo.get_by_id = AsyncMock(return_value=draft_report)

    with pytest.raises(BadRequestException) as exc_info:
        await service.approve_report(
            report_id=20,
            data=LabReportApprove(approved=True, remarks="Premature approval"),
            current_user=doctor_user,
        )

    assert "Report must be verified by Lab Technician first" in str(exc_info.value)
