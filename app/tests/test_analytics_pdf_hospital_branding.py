import json
import os
import pytest
from unittest.mock import AsyncMock, patch

from app.models.analytics_model import ReportExport, ReportExportFormat, ReportExportStatus
from app.models.hospital_model import Hospital
from app.services.analytics_service import AnalyticsService
from app.tasks.analytics_tasks import _generate_export
from app.utils.pdf_generator import (
    generate_analytics_report_html,
    generate_lab_report_html,
    resolve_logo_as_data_uri,
)


DUMMY_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00"
    b"\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00"
    b"\x00IEND\xaeB`\x82"
)


def make_hospital(
    hosp_id: int,
    name: str,
    email: str = "contact@hospital.com",
    phone: str = "+91 99999 88888",
    address: str = "123 Healthcare Ave, Pune",
    website: str = "https://hospital.com",
    logo_path: str | None = None,
) -> Hospital:
    hosp = Hospital()
    hosp.id = hosp_id
    hosp.name = name
    hosp.email = email
    hosp.phone = phone
    hosp.address = address
    hosp.website = website
    hosp.logo_path = logo_path
    return hosp


def make_report_export(
    export_id: int,
    report_type: str = "revenue",
    hospital_id: int | None = None,
    requested_by: int | None = 10,
) -> ReportExport:
    filters = {}
    if hospital_id is not None:
        filters["hospital_id"] = hospital_id
    export = ReportExport()
    export.id = export_id
    export.report_type = report_type
    export.export_format = ReportExportFormat.PDF
    export.status = ReportExportStatus.PENDING
    export.filters = json.dumps(filters)
    export.requested_by = requested_by
    export.file_path = None
    return export


@pytest.fixture
def hospital_logos(tmp_path):
    logo_a = tmp_path / "hospital_a_logo.png"
    logo_a.write_bytes(DUMMY_PNG_BYTES)
    logo_b = tmp_path / "hospital_b_logo.png"
    logo_b.write_bytes(DUMMY_PNG_BYTES)
    return str(logo_a), str(logo_b)


# ---------------------------------------------------------------------------
# Test 1: Patients Analytics PDF Export uses dedicated template (no lab content)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_patients_analytics_pdf_dedicated_template_content(hospital_logos):
    logo_a_path, _ = hospital_logos

    data = {
        "title": "Patients Analytics Report",
        "report_type": "patients",
        "hospital_name": "Chetan Multispeciality Hospital",
        "hospital_address": "Main Road, Bhusawal, Maharashtra, India",
        "hospital_phone": "+919876543232",
        "hospital_email": "contact@chetanhospital.com",
        "hospital_website": "https://chetanhospital.com",
        "hospital_logo": logo_a_path,
        "generated_at": "2026-11-07 09:30:00 UTC",
        "rows": [{
            "total_patients": 120,
            "new_patients": 25,
            "active_patients": 95,
            "gender_breakdown": [{"label": "Male", "value": 65}, {"label": "Female", "value": 55}],
            "registration_trend": [{"label": "2026-11-01", "value": 5}, {"label": "2026-11-02", "value": 8}],
        }],
    }

    rel_path = await generate_analytics_report_html("RPT-TEST-PATIENTS", data)
    assert rel_path is not None

    disk_path = os.path.join("app", rel_path.lstrip("/\\"))
    if not os.path.exists(disk_path):
        disk_path = rel_path

    # Read generated HTML / PDF text
    if disk_path.endswith(".html"):
        with open(disk_path, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        import pypdf
        reader = pypdf.PdfReader(disk_path)
        content = "\n".join(page.extract_text() for page in reader.pages)

    # 1. Hospital Branding assertions
    assert "Chetan Multispeciality Hospital" in content or "CHETAN MULTISPECIALITY" in content
    assert "Main Road, Bhusawal" in content
    assert "+919876543232" in content
    assert "contact@chetanhospital.com" in content
    assert "PATIENTS ANALYTICS REPORT" in content

    # 2. Analytics specific content assertions
    assert "TOTAL PATIENTS" in content.upper()
    assert "NEW PATIENTS" in content.upper()
    assert "ACTIVE PATIENTS" in content.upper()
    assert "GENDER BREAKDOWN" in content.upper()
    assert "REGISTRATION TREND" in content.upper()
    assert "Male" in content
    assert "Female" in content

    # 3. Strictly assert ABSENCE of clinical laboratory diagnostic content
    assert "LABORATORY INVESTIGATION RESULTS" not in content
    assert "TEST PARAMETER" not in content
    assert "OBSERVED VALUE" not in content
    assert "BIOLOGICAL REFERENCE RANGE" not in content
    assert "Medical Laboratory Technologist" not in content
    assert "Consultant Pathologist" not in content
    assert "Diagnostic Report" not in content
    assert "specimen tested" not in content


# ---------------------------------------------------------------------------
# Test 2: Revenue Analytics PDF Export with Currency Formatting
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_revenue_analytics_pdf_export(hospital_logos):
    logo_a_path, _ = hospital_logos

    data = {
        "title": "Revenue Analytics Report",
        "report_type": "revenue",
        "hospital_name": "Alpha Multispeciality Hospital",
        "hospital_address": "Alpha Square, Pune",
        "hospital_phone": "+91 98765 00101",
        "hospital_email": "info@alphahospital.com",
        "hospital_website": "https://alphahospital.com",
        "hospital_logo": logo_a_path,
        "generated_at": "2026-11-07 09:30:00 UTC",
        "rows": [{
            "total_revenue": 500000.0,
            "paid_amount": 420000.0,
            "pending_amount": 80000.0,
            "payment_method_breakdown": [{"label": "UPI", "value": 250000.0}, {"label": "Cash", "value": 170000.0}],
            "daily_revenue": [{"label": "2026-11-05", "value": 45000.0}],
        }],
    }

    rel_path = await generate_analytics_report_html("RPT-TEST-REVENUE", data)
    disk_path = os.path.join("app", rel_path.lstrip("/\\"))
    if not os.path.exists(disk_path):
        disk_path = rel_path

    if disk_path.endswith(".html"):
        with open(disk_path, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        import pypdf
        reader = pypdf.PdfReader(disk_path)
        content = "\n".join(page.extract_text() for page in reader.pages)

    assert "REVENUE ANALYTICS REPORT" in content
    assert "TOTAL REVENUE" in content.upper()
    assert "PAID AMOUNT" in content.upper()
    assert "PENDING AMOUNT" in content.upper()
    assert "PAYMENT METHOD BREAKDOWN" in content.upper()
    assert "UPI" in content
    assert "LABORATORY INVESTIGATION RESULTS" not in content


# ---------------------------------------------------------------------------
# Test 3: Appointments Analytics PDF Export
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_appointments_analytics_pdf_export():
    data = {
        "title": "Appointments Analytics Report",
        "report_type": "appointments",
        "hospital_name": "Metro Healthcare Center",
        "hospital_address": "Shivaji Nagar, Pune",
        "hospital_phone": "+91 20 25551234",
        "hospital_email": "metro@health.com",
        "hospital_website": "https://metrohealth.com",
        "hospital_logo": None,
        "generated_at": "2026-11-07 09:30:00 UTC",
        "rows": [{
            "total": 350,
            "completed": 280,
            "cancelled": 50,
            "no_show": 20,
            "status_breakdown": [{"label": "Completed", "value": 280}, {"label": "Cancelled", "value": 50}],
            "department_breakdown": [{"label": "Cardiology", "value": 120}, {"label": "Orthopedics", "value": 80}],
            "daily_trend": [{"label": "2026-11-06", "value": 42}],
        }],
    }

    rel_path = await generate_analytics_report_html("RPT-TEST-APPOINTMENTS", data)
    disk_path = os.path.join("app", rel_path.lstrip("/\\"))
    if not os.path.exists(disk_path):
        disk_path = rel_path

    if disk_path.endswith(".html"):
        with open(disk_path, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        import pypdf
        reader = pypdf.PdfReader(disk_path)
        content = "\n".join(page.extract_text() for page in reader.pages)

    normalized = " ".join(content.split())
    assert "APPOINTMENTS ANALYTICS REPORT" in normalized
    assert "COMPLETED" in content.upper()
    assert "CANCELLED" in content.upper()
    assert "DEPARTMENT BREAKDOWN" in content.upper()
    assert "Cardiology" in content
    assert "Consultant Pathologist" not in content


# ---------------------------------------------------------------------------
# Test 4: Doctors Analytics PDF Export
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_doctors_analytics_pdf_export():
    data = {
        "title": "Doctors Analytics Report",
        "report_type": "doctors",
        "hospital_name": "City Care Hospital",
        "hospital_address": "Camp, Pune",
        "hospital_phone": "+91 20 26661234",
        "hospital_email": "contact@citycare.com",
        "hospital_website": "https://citycare.com",
        "hospital_logo": None,
        "generated_at": "2026-11-07 09:30:00 UTC",
        "rows": [{
            "total_doctors": 15,
            "avg_appointments_per_doctor": 23.5,
            "top_doctors": [{"doctor_name": "Dr. Sunil Patil", "department": "Pediatrics", "appointments": 45}],
            "availability_breakdown": [{"label": "Available", "value": 12}, {"label": "On Leave", "value": 3}],
        }],
    }

    rel_path = await generate_analytics_report_html("RPT-TEST-DOCTORS", data)
    disk_path = os.path.join("app", rel_path.lstrip("/\\"))
    if not os.path.exists(disk_path):
        disk_path = rel_path

    if disk_path.endswith(".html"):
        with open(disk_path, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        import pypdf
        reader = pypdf.PdfReader(disk_path)
        content = "\n".join(page.extract_text() for page in reader.pages)

    assert "DOCTORS ANALYTICS REPORT" in content
    assert "TOTAL DOCTORS" in content.upper()
    assert "TOP DOCTORS" in content.upper()
    assert "Dr. Sunil Patil" in content
    assert "Pediatrics" in content
    assert "LABORATORY INVESTIGATION RESULTS" not in content


# ---------------------------------------------------------------------------
# Test 5: Dashboard Analytics PDF Export
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dashboard_analytics_pdf_export():
    data = {
        "title": "Dashboard Analytics Report",
        "report_type": "dashboard",
        "hospital_name": "Apex Multispeciality",
        "hospital_address": "Viman Nagar, Pune",
        "hospital_phone": "+91 20 27771234",
        "hospital_email": "info@apex.com",
        "hospital_website": "https://apex.com",
        "hospital_logo": None,
        "generated_at": "2026-11-07 09:30:00 UTC",
        "rows": [{
            "revenue": 1250000.0,
            "appointments_today": 45,
            "total_patients": 1200,
            "total_doctors": 28,
            "pending_appointments": 12,
            "ai_chat_sessions": 85,
            "voice_calls_today": 32,
            "whatsapp_messages_today": 110,
            "charts": [{"name": "Weekly Trend", "data": [{"label": "Mon", "value": 20}, {"label": "Tue", "value": 25}]}],
        }],
    }

    rel_path = await generate_analytics_report_html("RPT-TEST-DASHBOARD", data)
    disk_path = os.path.join("app", rel_path.lstrip("/\\"))
    if not os.path.exists(disk_path):
        disk_path = rel_path

    if disk_path.endswith(".html"):
        with open(disk_path, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        import pypdf
        reader = pypdf.PdfReader(disk_path)
        content = "\n".join(page.extract_text() for page in reader.pages)

    normalized = " ".join(content.split())
    assert "DASHBOARD ANALYTICS REPORT" in normalized
    assert "TOTAL PATIENTS" in content.upper()
    assert "APPOINTMENTS TODAY" in content.upper()
    assert "WEEKLY TREND" in content.upper()
    assert "Mon" in content
    assert "LABORATORY INVESTIGATION RESULTS" not in content


# ---------------------------------------------------------------------------
# Test 6: Hospital A branding never appears in Hospital B PDF
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_hospital_a_branding_never_appears_in_hospital_b(hospital_logos):
    logo_a_path, logo_b_path = hospital_logos
    mock_db = AsyncMock()
    service = AnalyticsService(mock_db)

    hosp_b = make_hospital(
        202,
        "Beta Super Care Clinic",
        email="contact@betacare.com",
        phone="+91 98765 00202",
        address="Beta Commercial Hub, Mumbai",
        website="https://betacare.com",
        logo_path=logo_b_path,
    )
    export_b = make_report_export(export_id=3, report_type="dashboard", hospital_id=202)

    service.repo.get_export = AsyncMock(return_value=export_b)
    service.repo.update_export = AsyncMock(return_value=export_b)
    service._build_export_rows = AsyncMock(return_value=[{"total_patients": 89}])

    captured_call = {}

    async def fake_generate_analytics_report_html(report_no, data):
        captured_call["report_number"] = report_no
        captured_call["data"] = data
        return f"/uploads/analytics_reports/{report_no}.pdf"

    with patch("app.repositories.hospital_repository.HospitalRepository.get_by_id", new_callable=AsyncMock) as mock_get_hosp, \
         patch("app.services.analytics_service.generate_analytics_report_html", side_effect=fake_generate_analytics_report_html):
        mock_get_hosp.return_value = hosp_b

        await service.process_export(export_id=3, hospital_id=202)

        passed_data = captured_call["data"]
        assert "Alpha Multispeciality Hospital" not in passed_data.values()
        assert "info@alphahospital.com" not in passed_data.values()
        assert "+91 98765 00101" not in passed_data.values()
        assert logo_a_path != passed_data["hospital_logo"]
        assert passed_data["hospital_name"] == "Beta Super Care Clinic"


# ---------------------------------------------------------------------------
# Test 7: Missing hospital logo handled gracefully (no crash, logo is None)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_missing_hospital_logo_handled_gracefully():
    mock_db = AsyncMock()
    service = AnalyticsService(mock_db)

    hosp_no_logo = make_hospital(
        303,
        "Gamma Rural Hospital",
        email="gamma@rural.org",
        phone="+91 20 12345678",
        address="Highway 4, Satara",
        website=None,
        logo_path=None,
    )
    export_record = make_report_export(export_id=4, report_type="doctors", hospital_id=303)

    service.repo.get_export = AsyncMock(return_value=export_record)
    service.repo.update_export = AsyncMock(return_value=export_record)
    service._build_export_rows = AsyncMock(return_value=[{"total_doctors": 12}])

    captured_call = {}

    async def fake_generate_analytics_report_html(report_no, data):
        captured_call["report_number"] = report_no
        captured_call["data"] = data
        return f"/uploads/analytics_reports/{report_no}.pdf"

    with patch("app.repositories.hospital_repository.HospitalRepository.get_by_id", new_callable=AsyncMock) as mock_get_hosp, \
         patch("app.services.analytics_service.generate_analytics_report_html", side_effect=fake_generate_analytics_report_html):
        mock_get_hosp.return_value = hosp_no_logo

        await service.process_export(export_id=4, hospital_id=303)

        passed_data = captured_call["data"]
        assert passed_data["hospital_name"] == "Gamma Rural Hospital"
        assert passed_data["hospital_logo"] is None
        assert resolve_logo_as_data_uri(passed_data["hospital_logo"]) is None


# ---------------------------------------------------------------------------
# Test 8: Missing hospital info handled gracefully (neutral fallback)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_missing_hospital_info_handled_gracefully():
    mock_db = AsyncMock()
    service = AnalyticsService(mock_db)

    export_record = make_report_export(export_id=5, report_type="patients", hospital_id=999)

    service.repo.get_export = AsyncMock(return_value=export_record)
    service.repo.update_export = AsyncMock(return_value=export_record)
    service._build_export_rows = AsyncMock(return_value=[{"total_patients": 100}])

    captured_call = {}

    async def fake_generate_analytics_report_html(report_no, data):
        captured_call["report_number"] = report_no
        captured_call["data"] = data
        return f"/uploads/analytics_reports/{report_no}.pdf"

    with patch("app.repositories.hospital_repository.HospitalRepository.get_by_id", new_callable=AsyncMock) as mock_get_hosp, \
         patch("app.services.analytics_service.generate_analytics_report_html", side_effect=fake_generate_analytics_report_html):
        mock_get_hosp.return_value = None

        await service.process_export(export_id=5, hospital_id=999)

        assert export_record.status == ReportExportStatus.COMPLETED
        passed_data = captured_call["data"]
        assert passed_data["hospital_name"] is None
        assert passed_data["hospital_logo"] is None


# ---------------------------------------------------------------------------
# Test 9: Background Analytics PDF export uses the correct hospital branding
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_background_analytics_pdf_export_uses_correct_hospital_branding(hospital_logos):
    logo_a_path, _ = hospital_logos

    hosp_a = make_hospital(
        101,
        "Alpha Multispeciality Hospital",
        email="info@alphahospital.com",
        phone="+91 98765 00101",
        address="Alpha Square, Ward 1, Pune",
        website="https://alphahospital.com",
        logo_path=logo_a_path,
    )
    export_record = make_report_export(export_id=77, report_type="revenue", hospital_id=101)

    captured_call = {}

    async def fake_generate_analytics_report_html(report_no, data):
        captured_call["report_number"] = report_no
        captured_call["data"] = data
        return f"/uploads/analytics_reports/{report_no}.pdf"

    mock_db_session = AsyncMock()

    with patch("app.core.database.AsyncSessionLocal") as mock_session_local, \
         patch("app.repositories.analytics_repository.AnalyticsRepository.get_export", new_callable=AsyncMock) as mock_get_export, \
         patch("app.repositories.analytics_repository.AnalyticsRepository.update_export", new_callable=AsyncMock), \
         patch("app.repositories.hospital_repository.HospitalRepository.get_by_id", new_callable=AsyncMock) as mock_get_hosp, \
         patch("app.services.analytics_service.AnalyticsService._build_export_rows", new_callable=AsyncMock) as mock_build_rows, \
         patch("app.services.analytics_service.generate_analytics_report_html", side_effect=fake_generate_analytics_report_html):

        mock_session_local.return_value.__aenter__.return_value = mock_db_session
        mock_get_export.return_value = export_record
        mock_get_hosp.return_value = hosp_a
        mock_build_rows.return_value = [{"daily_revenue": 10000.0}]

        # Trigger background task directly (simulating Celery worker execution)
        await _generate_export(export_id=77)

        mock_get_hosp.assert_awaited_once_with(101)
        passed_data = captured_call["data"]
        assert passed_data["hospital_name"] == "Alpha Multispeciality Hospital"
        assert passed_data["hospital_logo"] == logo_a_path
        assert passed_data["hospital_email"] == "info@alphahospital.com"


# ---------------------------------------------------------------------------
# Test 10: Existing Lab Diagnostic PDF continues working unchanged
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_existing_lab_report_pdf_continues_working():
    report_data = {
        "order_number": "ORD-20261023-001",
        "report_number": "RPT-20261023-LAB",
        "status": "approved",
        "generated_at": "2026-10-23 10:00:00",
        "patient_name": "Manisha Koirala",
        "patient_code": "PAT-20261021-001",
        "patient_gender": "Female",
        "patient_dob": "1970-09-05",
        "doctor_name": "Dr. Rajesh Swami",
        "doctor_code": "DOC-20260909-01",
        "test_name": "Blood Glucose",
        "test_category": "Biochemistry",
        "sample_type": "Blood",
        "summary": "Fasting blood sugar within normal physiological limits.",
        "columns": ["Parameter", "Result Value", "Unit", "Normal Range", "Is Critical"],
        "rows": [
            ["Fasting Blood Sugar", "95", "mg/dL", "70-110", "No"],
            ["Post Prandial", "135", "mg/dL", "< 140", "No"],
        ],
        "hospital_name": "NexaCare Multi-Speciality Hospital",
        "hospital_address": "123 Medical Enclave, Pune, Maharashtra 411001",
        "hospital_phone": "+91 98765 43210",
        "hospital_email": "contact@nexacare.com",
        "hospital_website": "www.nexacare.com",
        "hospital_logo": None,
        "title": "Diagnostic Report",
    }

    rel_path = await generate_lab_report_html("RPT-20261023-LAB", report_data)
    assert rel_path is not None
    disk_path = os.path.join("app", rel_path.lstrip("/\\"))
    if not os.path.exists(disk_path):
        disk_path = rel_path

    if disk_path.endswith(".html"):
        with open(disk_path, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        import pypdf
        reader = pypdf.PdfReader(disk_path)
        content = "\n".join(page.extract_text() for page in reader.pages)

    # Existing Lab Report MUST retain diagnostic investigation results and signatures
    assert "NexaCare Multi-Speciality Hospital" in content
    assert "Manisha Koirala" in content
    assert "Blood Glucose" in content
    assert "Medical Laboratory Technologist" in content
    assert "Consultant Pathologist" in content
