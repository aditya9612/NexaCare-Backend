import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from app.services.branding_resolver_service import BrandingResolverService
from app.services.analytics_service import AnalyticsService
from app.services.discharge_service import DischargeService
from app.services.staff_service import StaffService
from app.schemas.analytics_schema import ExportReportRequest
from app.core.exceptions import BadRequestException, ForbiddenException
from app.utils.pdf_generator import env


# =====================================================================
# 1. BrandingResolverService Hardening Tests
# =====================================================================

@pytest.mark.asyncio
async def test_branding_resolver_rejects_bool_true():
    service = BrandingResolverService(db=AsyncMock())
    with pytest.raises(BadRequestException, match="Invalid hospital ID"):
        await service.resolve_branding(hospital_id=True)


@pytest.mark.asyncio
async def test_branding_resolver_rejects_bool_false():
    service = BrandingResolverService(db=AsyncMock())
    with pytest.raises(BadRequestException, match="Invalid hospital ID"):
        await service.resolve_branding(hospital_id=False)


@pytest.mark.asyncio
async def test_branding_resolver_rejects_zero():
    service = BrandingResolverService(db=AsyncMock())
    with pytest.raises(BadRequestException, match="Invalid hospital ID"):
        await service.resolve_branding(hospital_id=0)


@pytest.mark.asyncio
async def test_branding_resolver_rejects_negative():
    service = BrandingResolverService(db=AsyncMock())
    with pytest.raises(BadRequestException, match="Invalid hospital ID"):
        await service.resolve_branding(hospital_id=-5)


@pytest.mark.asyncio
async def test_branding_resolver_rejects_string():
    service = BrandingResolverService(db=AsyncMock())
    with pytest.raises(BadRequestException, match="Invalid hospital ID"):
        await service.resolve_branding(hospital_id="1")


@pytest.mark.asyncio
async def test_branding_resolver_non_super_admin_none_hospital_id():
    service = BrandingResolverService(db=AsyncMock())
    user = MagicMock()
    user.role.name = "hospital_admin"
    user.hospital_id = None
    with pytest.raises(ForbiddenException, match="Tenant hospital context is required"):
        await service.resolve_branding(current_user=user)


@pytest.mark.asyncio
async def test_branding_resolver_non_super_admin_invalid_user_hospital_id():
    service = BrandingResolverService(db=AsyncMock())
    user = MagicMock()
    user.role.name = "doctor"
    user.hospital_id = -2
    with pytest.raises(ForbiddenException, match="Invalid tenant hospital context"):
        await service.resolve_branding(current_user=user)


@pytest.mark.asyncio
async def test_branding_resolver_cross_tenant_access_denied():
    service = BrandingResolverService(db=AsyncMock())
    user = MagicMock()
    user.role.name = "nurse"
    user.hospital_id = 10
    with pytest.raises(ForbiddenException, match="Access denied"):
        await service.resolve_branding(hospital_id=20, current_user=user)


@pytest.mark.asyncio
async def test_branding_resolver_super_admin_invalid_active_hospital_id():
    service = BrandingResolverService(db=AsyncMock())
    user = MagicMock()
    user.role.name = "super_admin"
    user.active_hospital_id = False
    with pytest.raises(BadRequestException, match="Invalid active hospital ID"):
        await service.resolve_branding(current_user=user)


# =====================================================================
# 2. AnalyticsService Export Spoofing Defense Tests
# =====================================================================

@pytest.mark.asyncio
async def test_analytics_request_export_strips_client_hospital_id_when_none():
    mock_db = AsyncMock()
    service = AnalyticsService(db=mock_db)
    
    captured_exports = []
    async def fake_create_export(export_obj):
        export_obj.id = 101
        captured_exports.append(export_obj)
        return export_obj

    service.repo.create_export = AsyncMock(side_effect=fake_create_export)

    req = ExportReportRequest(
        report_type="revenue",
        filters={"hospital_id": 999, "start_date": "2026-01-01"}
    )
    with patch("app.tasks.analytics_tasks.generate_export.delay") as mock_delay:
        res = await service.request_export(req, user_id=1, hospital_id=None)
        assert res.export_id == 101
        assert len(captured_exports) == 1
        stored_filters = json.loads(captured_exports[0].filters)
        assert "hospital_id" not in stored_filters
        assert stored_filters["start_date"] == "2026-01-01"
        mock_delay.assert_called_once_with(101, hospital_id=None)


@pytest.mark.asyncio
async def test_analytics_request_export_overwrites_client_hospital_id():
    mock_db = AsyncMock()
    service = AnalyticsService(db=mock_db)
    
    captured_exports = []
    async def fake_create_export(export_obj):
        export_obj.id = 102
        captured_exports.append(export_obj)
        return export_obj

    service.repo.create_export = AsyncMock(side_effect=fake_create_export)

    req = ExportReportRequest(
        report_type="revenue",
        filters={"hospital_id": 999, "start_date": "2026-01-01"}
    )
    with patch("app.tasks.analytics_tasks.generate_export.delay") as mock_delay:
        res = await service.request_export(req, user_id=1, hospital_id=42)
        assert res.export_id == 102
        assert len(captured_exports) == 1
        stored_filters = json.loads(captured_exports[0].filters)
        assert stored_filters["hospital_id"] == 42
        mock_delay.assert_called_once_with(102, hospital_id=42)


@pytest.mark.asyncio
async def test_analytics_request_export_excel_strips_client_hospital_id_when_none():
    mock_db = AsyncMock()
    service = AnalyticsService(db=mock_db)
    
    captured_exports = []
    async def fake_create_export(export_obj):
        export_obj.id = 103
        captured_exports.append(export_obj)
        return export_obj

    service.repo.create_export = AsyncMock(side_effect=fake_create_export)

    req = ExportReportRequest(
        report_type="occupancy",
        filters={"hospital_id": 888}
    )
    with patch("app.tasks.analytics_tasks.generate_export.delay") as mock_delay:
        res = await service.request_export_excel(req, user_id=2, hospital_id=None)
        assert res.export_id == 103
        stored_filters = json.loads(captured_exports[0].filters)
        assert "hospital_id" not in stored_filters
        mock_delay.assert_called_once_with(103, hospital_id=None)


@pytest.mark.asyncio
async def test_analytics_request_export_excel_overwrites_client_hospital_id():
    mock_db = AsyncMock()
    service = AnalyticsService(db=mock_db)
    
    captured_exports = []
    async def fake_create_export(export_obj):
        export_obj.id = 104
        captured_exports.append(export_obj)
        return export_obj

    service.repo.create_export = AsyncMock(side_effect=fake_create_export)

    req = ExportReportRequest(
        report_type="occupancy",
        filters={"hospital_id": 888}
    )
    with patch("app.tasks.analytics_tasks.generate_export.delay") as mock_delay:
        res = await service.request_export_excel(req, user_id=2, hospital_id=55)
        assert res.export_id == 104
        stored_filters = json.loads(captured_exports[0].filters)
        assert stored_filters["hospital_id"] == 55
        mock_delay.assert_called_once_with(104, hospital_id=55)


# =====================================================================
# 3. StaffService Nurse Enrichment & Welcome Notification Tests
# =====================================================================

@pytest.mark.asyncio
async def test_staff_enrich_nurse_info_single():
    mock_db = AsyncMock()
    mock_row = MagicMock()
    mock_row.license_number = "RN-99999"
    mock_row.shift = "NIGHT"
    
    mock_result = MagicMock()
    mock_result.first.return_value = mock_row
    mock_db.execute = AsyncMock(return_value=mock_result)

    service = StaffService(db=mock_db)
    staff = MagicMock()
    staff.role_name = "Nurse"
    staff.email = "nurse@hospital.com"
    staff.hospital_id = 1

    enriched = await service._enrich_nurse_info(staff)
    assert enriched.license_number == "RN-99999"
    assert enriched.shift == "NIGHT"


@pytest.mark.asyncio
async def test_staff_enrich_nurse_info_bulk():
    mock_db = AsyncMock()
    mock_row1 = MagicMock()
    mock_row1.email = "nurse1@hospital.com"
    mock_row1.license_number = "RN-001"
    mock_row1.shift = "DAY"

    mock_row2 = MagicMock()
    mock_row2.email = "nurse2@hospital.com"
    mock_row2.license_number = "RN-002"
    mock_row2.shift = "EVENING"

    mock_result = MagicMock()
    mock_result.all.return_value = [mock_row1, mock_row2]
    mock_db.execute = AsyncMock(return_value=mock_result)

    service = StaffService(db=mock_db)
    s1 = MagicMock()
    s1.role_name = "Nurse"
    s1.email = "nurse1@hospital.com"
    s1.hospital_id = 1

    s2 = MagicMock()
    s2.role_name = "Nurse"
    s2.email = "nurse2@hospital.com"
    s2.hospital_id = 1

    s3 = MagicMock()
    s3.role_name = "Doctor"
    s3.email = "doc@hospital.com"
    s3.hospital_id = 1

    await service._enrich_nurse_info_bulk([s1, s2, s3])
    assert s1.license_number == "RN-001"
    assert s1.shift == "DAY"
    assert s2.license_number == "RN-002"
    assert s2.shift == "EVENING"


@pytest.mark.asyncio
async def test_staff_notify_onboarding_welcome_failure_is_non_fatal():
    mock_db = AsyncMock()
    mock_db.scalar = AsyncMock(return_value=True)
    service = StaffService(db=mock_db)
    service.dept_repo = MagicMock()
    service.dept_repo.get_by_id = AsyncMock(return_value=None)

    staff = MagicMock()
    staff.id = 1
    staff.full_name = "Jane Doe"
    staff.staff_code = "STF001"
    staff.role_name = "Nurse"
    staff.department_id = None
    staff.hospital_id = 10

    user = MagicMock()
    user.id = 2
    user.hospital_id = 10
    user.email = "jane@example.com"
    user.phone = "1234567890"

    with patch("app.services.notification_service.NotificationService.notify_staff_onboarding_welcome", side_effect=RuntimeError("Notification failure")):
        # Must not raise an exception
        await service._notify_staff_onboarding_welcome_safely(staff, user)


# =====================================================================
# 4. DischargeService Billing Clearance State Capture Tests
# =====================================================================

@pytest.mark.asyncio
async def test_discharge_clear_billing_was_billing_cleared_capture():
    mock_db = AsyncMock()
    service = DischargeService(db=mock_db)
    
    mock_discharge = MagicMock()
    mock_discharge.id = 1
    mock_discharge.discharge_status = "PENDING"
    mock_discharge.billing_cleared = False
    mock_discharge.doctor_cleared = True
    mock_discharge.nursing_cleared = True
    mock_discharge.pharmacy_cleared = True
    mock_discharge.final_bill_id = 99
    mock_discharge.final_summary = "Ready"
    mock_discharge.status = "PENDING"
    mock_discharge.admission = MagicMock()
    mock_discharge.admission.bed = MagicMock()

    service.repo.get_by_id = AsyncMock(return_value=mock_discharge)
    service.repo.update = AsyncMock(return_value=mock_discharge)
    service._check_and_update_cleared_status = MagicMock()
    service._notify_discharge_billing_cleared_safely = AsyncMock()

    with patch("app.schemas.discharge_schema.DischargeResponse.model_validate", return_value=mock_discharge):
        result = await service.clear_billing(discharge_id=1, user_id=5)
        assert result.billing_cleared is True
        assert mock_discharge.billing_cleared is True
        assert mock_discharge.billing_cleared_by == 5
        service._notify_discharge_billing_cleared_safely.assert_awaited_once_with(mock_discharge)


# =====================================================================
# 5. Invoice Template & PDF Generator Hardening Tests
# =====================================================================

def test_invoice_template_whitespace_hospital_name_renders_fallback():
    template = env.get_template("invoice_template.html")
    html = template.render(
        invoice_number="INV-12345",
        invoice_date="2026-03-31",
        patient_name="Test Patient",
        hospital_name="   ",
        items=[],
        total_amount=100.0,
    )
    assert '<div class="brand-title">Hospital</div>' in html
    assert "Thank you for choosing our hospital!" in html


def test_invoice_template_none_hospital_name_renders_fallback():
    template = env.get_template("invoice_template.html")
    html = template.render(
        invoice_number="INV-12345",
        invoice_date="2026-03-31",
        patient_name="Test Patient",
        hospital_name=None,
        items=[],
        total_amount=100.0,
    )
    assert '<div class="brand-title">Hospital</div>' in html
    assert "Thank you for choosing our hospital!" in html


def test_invoice_template_escapes_xss_script():
    template = env.get_template("invoice_template.html")
    html = template.render(
        invoice_number="INV-12345",
        invoice_date="2026-03-31",
        patient_name="<script>alert('pwn')</script>",
        hospital_name="Safe Hospital",
        items=[],
        total_amount=100.0,
    )
    assert "<script>alert('pwn')</script>" not in html
    assert "&lt;script&gt;alert(&#39;pwn&#39;)&lt;/script&gt;" in html
