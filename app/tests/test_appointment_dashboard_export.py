import sys
import os
import asyncio
import uuid
from datetime import date, datetime, time, timedelta
import pytest
from httpx import AsyncClient, ASGITransport
import openpyxl
from io import BytesIO
from sqlalchemy import select
from unittest.mock import patch, AsyncMock

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from app.main import app
from app.models.appointment_model import Appointment
from app.models.hospital_model import Hospital
from app.models.patient_model import Patient
from app.models.doctor_model import Doctor
from app.models.department_model import Department
from app.models.user_model import User
from app.models.role_model import Role
from app.core.database import AsyncSessionLocal, engine
from app.core.dependencies import get_current_active_user, get_current_user
from app.core.constants import AppointmentStatus, AdmissionStatus
from app.core.exceptions import ForbiddenException
from app.services.appointment_service import AppointmentService
from app.utils.helpers import get_today_ist, utc_now


@pytest.fixture(autouse=True)
async def cleanup_engine():
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    await engine.dispose()
    yield
    await engine.dispose()


def _make_fake_user(user_id: int, hospital_id: int, role_name: str = "hospital_admin"):
    class FakeRole:
        name = role_name

    class FakeUser:
        def __init__(self):
            self.id = user_id
            self.role_id = 1
            self.hospital_id = hospital_id
            self.active_hospital_id = None
            self.is_active = True
            self.is_verified = True
            self.email = f"user_{user_id}_{hospital_id}@test.com"
            self.role = FakeRole()

    return FakeUser()


def _create_doctor(hospital_id: int, uid: str, suffix: str = "", first_name: str | None = None, last_name: str = "Smith", department_id: int | None = None) -> Doctor:
    return Doctor(
        first_name=first_name or f"Doc_{uid}_{suffix}"[:100],
        last_name=last_name,
        doctor_code=f"DOC_{uid}_{suffix}"[:50],
        license_number=f"LIC_{uid}_{suffix}"[:100],
        specialization="Cardiology",
        hospital_id=hospital_id,
        department_id=department_id,
    )


def _create_patient(hospital_id: int, uid: str, suffix: str = "", first_name: str | None = None, last_name: str = "Doe", patient_code: str | None = None) -> Patient:
    return Patient(
        first_name=first_name or f"Pat_{uid}_{suffix}"[:100],
        last_name=last_name,
        patient_code=patient_code or f"PAT_{uid}_{suffix}"[:50],
        gender="Female",
        hospital_id=hospital_id,
        phone="9876543210",
    )


@pytest.mark.asyncio
async def test_list_appointments_returns_all_12_dashboard_counts():
    """Verify that existing GET /appointments returns all 12 dashboard count fields."""
    uid = uuid.uuid4().hex[:8]
    today = get_today_ist()

    async with AsyncSessionLocal() as db:
        hosp = Hospital(
            name=f"Hospital Metrics {uid}",
            email=f"metrics_{uid}@hospital.com",
            phone="9988776655",
            address="100 Health Way",
        )
        db.add(hosp)
        await db.flush()

        dept = Department(
            department_name=f"Cardiology_{uid}",
            department_code=f"CARD_{uid}"[:20],
            hospital_id=hosp.id,
        )
        db.add(dept)
        await db.flush()

        doc = _create_doctor(hosp.id, uid, "1", first_name=f"John_{uid}", department_id=dept.department_id)
        db.add(doc)
        await db.flush()

        pat = _create_patient(hosp.id, uid, "1", first_name=f"Alice_{uid}")
        db.add(pat)
        await db.flush()

        # Create 8 appointments covering all metrics:
        # 1. Pending (Scheduled)
        a1 = Appointment(
            appointment_number=f"APT_P_{uid}",
            patient_id=pat.id,
            doctor_id=doc.id,
            department_id=dept.department_id,
            hospital_id=hosp.id,
            appointment_date=today,
            appointment_time=time(9, 0),
            appointment_status="Pending",
        )
        # 2. Confirmed (Scheduled)
        a2 = Appointment(
            appointment_number=f"APT_C_{uid}",
            patient_id=pat.id,
            doctor_id=doc.id,
            department_id=dept.department_id,
            hospital_id=hosp.id,
            appointment_date=today,
            appointment_time=time(10, 0),
            appointment_status="Confirmed",
        )
        # 3. Waiting (Checked-In + Waiting)
        a3 = Appointment(
            appointment_number=f"APT_W_{uid}",
            patient_id=pat.id,
            doctor_id=doc.id,
            department_id=dept.department_id,
            hospital_id=hosp.id,
            appointment_date=today,
            appointment_time=time(11, 0),
            appointment_status="Checked-In",
            check_in_time=datetime.now(),
            queue_token="T-01",
            queue_status="WAITING",
        )
        # 4. In Progress
        a4 = Appointment(
            appointment_number=f"APT_IP_{uid}",
            patient_id=pat.id,
            doctor_id=doc.id,
            department_id=dept.department_id,
            hospital_id=hosp.id,
            appointment_date=today,
            appointment_time=time(12, 0),
            appointment_status="In-Progress",
            check_in_time=datetime.now(),
            queue_token="T-02",
            queue_status="IN-PROGRESS",
        )
        # 5. Admitted (Completed + Admitted)
        a5 = Appointment(
            appointment_number=f"APT_ADM_{uid}",
            patient_id=pat.id,
            doctor_id=doc.id,
            department_id=dept.department_id,
            hospital_id=hosp.id,
            appointment_date=today,
            appointment_time=time(13, 0),
            appointment_status="Completed",
            admission_status="Admitted",
            admission_recommended=True,
            queue_status="COMPLETED",
        )
        # 6. Checked-Out
        a6 = Appointment(
            appointment_number=f"APT_CO_{uid}",
            patient_id=pat.id,
            doctor_id=doc.id,
            department_id=dept.department_id,
            hospital_id=hosp.id,
            appointment_date=today,
            appointment_time=time(14, 0),
            appointment_status="Checked-Out",
            check_in_time=datetime.now(),
            check_out_time=datetime.now(),
            queue_status="COMPLETED",
        )
        # 7. Cancelled
        a7 = Appointment(
            appointment_number=f"APT_CAN_{uid}",
            patient_id=pat.id,
            doctor_id=doc.id,
            department_id=dept.department_id,
            hospital_id=hosp.id,
            appointment_date=today,
            appointment_time=time(15, 0),
            appointment_status="Cancelled",
        )
        # 8. No Show
        a8 = Appointment(
            appointment_number=f"APT_NS_{uid}",
            patient_id=pat.id,
            doctor_id=doc.id,
            department_id=dept.department_id,
            hospital_id=hosp.id,
            appointment_date=today,
            appointment_time=time(16, 0),
            appointment_status="No Show",
        )
        db.add_all([a1, a2, a3, a4, a5, a6, a7, a8])
        await db.commit()

        user = _make_fake_user(user_id=1, hospital_id=hosp.id)
        service = AppointmentService(db)
        res = await service.list_appointments(current_user=user, page=1, size=20)

        # Assert all 12 dashboard metrics in existing endpoint response
        assert res["total_appointments"] == 8
        assert res["today_appointments"] == 8
        assert res["total_scheduled"] == 2  # Scheduled = Pending + Confirmed
        assert res["pending"] == 1
        assert res["confirmed"] == 1
        assert res["waiting"] == 1
        assert res["in_progress"] == 1
        assert res["checked_in"] == 1
        assert res["admitted"] == 1
        assert res["completed"] == 1
        assert res["checked_out"] == 1
        assert res["cancelled"] == 2  # Combined Cancelled + No Show
        assert "no_show" not in res
        assert "total_today_appointments" not in res
        assert len(res["items"]) == 8


@pytest.mark.asyncio
async def test_list_appointments_date_boundaries_and_ist():
    """Verify date boundaries and total_appointments in existing list endpoint."""
    uid = uuid.uuid4().hex[:8]
    today = get_today_ist()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)

    async with AsyncSessionLocal() as db:
        hosp = Hospital(name=f"HospDates_{uid}", email=f"dates_{uid}@test.com")
        db.add(hosp)
        await db.flush()

        pat = _create_patient(hosp.id, uid, "date")
        doc = _create_doctor(hosp.id, uid, "date")
        db.add_all([pat, doc])
        await db.flush()

        # 1 yesterday
        db.add(Appointment(
            appointment_number=f"APT_YEST_{uid}",
            patient_id=pat.id,
            doctor_id=doc.id,
            hospital_id=hosp.id,
            appointment_date=yesterday,
            appointment_time=time(10, 0),
            appointment_status="Confirmed",
        ))
        # 2 today
        for i in range(2):
            db.add(Appointment(
                appointment_number=f"APT_TODAY_{uid}_{i}",
                patient_id=pat.id,
                doctor_id=doc.id,
                hospital_id=hosp.id,
                appointment_date=today,
                appointment_time=time(11 + i, 0),
                appointment_status="Confirmed",
            ))
        # 1 tomorrow
        db.add(Appointment(
            appointment_number=f"APT_TOM_{uid}",
            patient_id=pat.id,
            doctor_id=doc.id,
            hospital_id=hosp.id,
            appointment_date=tomorrow,
            appointment_time=time(10, 0),
            appointment_status="Confirmed",
        ))
        await db.commit()

        user = _make_fake_user(user_id=1, hospital_id=hosp.id)
        service = AppointmentService(db)

        # Unfiltered: total = 4, today = 2
        res_unfiltered = await service.list_appointments(current_user=user, page=1, size=20)
        assert res_unfiltered["total_appointments"] == 4
        assert res_unfiltered["today_appointments"] == 2
        assert res_unfiltered["total"] == 4

        # Filtered to today: total remains all-time 4, today is 2, items returned is 2
        res_today = await service.list_appointments(date_filter="today", current_user=user, page=1, size=20)
        assert res_today["total_appointments"] == 4
        assert res_today["today_appointments"] == 2
        assert res_today["total"] == 2
        assert len(res_today["items"]) == 2


@pytest.mark.asyncio
async def test_list_appointments_tenant_isolation():
    """Verify that Hospital A and Hospital B cannot see each other's appointments or counts."""
    uid = uuid.uuid4().hex[:8]
    today = get_today_ist()

    async with AsyncSessionLocal() as db:
        hosp_a = Hospital(name=f"HospA_{uid}", email=f"a_{uid}@test.com")
        hosp_b = Hospital(name=f"HospB_{uid}", email=f"b_{uid}@test.com")
        db.add_all([hosp_a, hosp_b])
        await db.flush()

        pat_a = _create_patient(hosp_a.id, uid, "a")
        pat_b = _create_patient(hosp_b.id, uid, "b")
        doc_a = _create_doctor(hosp_a.id, uid, "a")
        doc_b = _create_doctor(hosp_b.id, uid, "b")
        db.add_all([pat_a, pat_b, doc_a, doc_b])
        await db.flush()

        # 3 appointments in Hospital A
        for i in range(3):
            db.add(Appointment(
                appointment_number=f"APT_A_{uid}_{i}",
                patient_id=pat_a.id,
                doctor_id=doc_a.id,
                hospital_id=hosp_a.id,
                appointment_date=today,
                appointment_time=time(10, 0),
                appointment_status="Confirmed",
            ))

        # 5 appointments in Hospital B
        for i in range(5):
            db.add(Appointment(
                appointment_number=f"APT_B_{uid}_{i}",
                patient_id=pat_b.id,
                doctor_id=doc_b.id,
                hospital_id=hosp_b.id,
                appointment_date=today,
                appointment_time=time(11, 0),
                appointment_status="Confirmed",
            ))
        await db.commit()

        user_a = _make_fake_user(user_id=1, hospital_id=hosp_a.id)
        user_b = _make_fake_user(user_id=2, hospital_id=hosp_b.id)

        service = AppointmentService(db)
        res_a = await service.list_appointments(current_user=user_a, page=1, size=20)
        res_b = await service.list_appointments(current_user=user_b, page=1, size=20)

        assert res_a["total_appointments"] == 3
        assert res_a["total"] == 3
        assert res_b["total_appointments"] == 5
        assert res_b["total"] == 5


@pytest.mark.asyncio
async def test_list_appointments_search():
    """Verify search across patient name/code, doctor name, and appointment number."""
    uid = uuid.uuid4().hex[:8]
    today = get_today_ist()

    async with AsyncSessionLocal() as db:
        hosp = Hospital(name=f"HospSearch_{uid}", email=f"search_{uid}@test.com")
        db.add(hosp)
        await db.flush()

        dept1 = Department(department_name=f"Ortho_{uid}", department_code=f"ORT_{uid}"[:20], hospital_id=hosp.id)
        dept2 = Department(department_name=f"Neuro_{uid}", department_code=f"NEU_{uid}"[:20], hospital_id=hosp.id)
        db.add_all([dept1, dept2])
        await db.flush()

        doc1 = _create_doctor(hosp.id, uid, "doc1", first_name=f"Gregory_{uid}", last_name="House", department_id=dept1.department_id)
        doc2 = _create_doctor(hosp.id, uid, "doc2", first_name=f"Stephen_{uid}", last_name="Strange", department_id=dept2.department_id)
        db.add_all([doc1, doc2])
        await db.flush()

        pat1 = _create_patient(hosp.id, uid, "pat1", first_name="Robert", last_name=f"Chase_{uid}", patient_code=f"PAT_CHASE_{uid}")
        pat2 = _create_patient(hosp.id, uid, "pat2", first_name="Allison", last_name=f"Cameron_{uid}", patient_code=f"PAT_CAM_{uid}")
        db.add_all([pat1, pat2])
        await db.flush()

        apt1 = Appointment(
            appointment_number=f"APT_HOUSE_{uid}",
            patient_id=pat1.id,
            doctor_id=doc1.id,
            department_id=dept1.department_id,
            hospital_id=hosp.id,
            appointment_date=today,
            appointment_time=time(9, 30),
            appointment_status="Confirmed",
        )
        apt2 = Appointment(
            appointment_number=f"APT_STRANGE_{uid}",
            patient_id=pat2.id,
            doctor_id=doc2.id,
            department_id=dept2.department_id,
            hospital_id=hosp.id,
            appointment_date=today,
            appointment_time=time(10, 30),
            appointment_status="Confirmed",
        )
        db.add_all([apt1, apt2])
        await db.commit()

        user = _make_fake_user(user_id=1, hospital_id=hosp.id)
        service = AppointmentService(db)

        # 1. Search by doctor first name 'Gregory'
        res_doc = await service.list_appointments(search=f"Gregory_{uid}", current_user=user)
        assert res_doc["total"] == 1
        assert res_doc["items"][0].appointment_number == f"APT_HOUSE_{uid}"

        # 2. Search by patient last name 'Chase'
        res_pat = await service.list_appointments(search=f"Chase_{uid}", current_user=user)
        assert res_pat["total"] == 1
        assert res_pat["items"][0].appointment_number == f"APT_HOUSE_{uid}"

        # 3. Search by patient code
        res_code = await service.list_appointments(search=f"PAT_CAM_{uid}", current_user=user)
        assert res_code["total"] == 1
        assert res_code["items"][0].appointment_number == f"APT_STRANGE_{uid}"

        # 4. Search by appointment number
        res_num = await service.list_appointments(search=f"APT_STRANGE_{uid}", current_user=user)
        assert res_num["total"] == 1
        assert res_num["items"][0].appointment_number == f"APT_STRANGE_{uid}"


@pytest.mark.asyncio
async def test_excel_export_content_and_structure():
    """Verify Excel export produces valid openpyxl workbook with styling and branding."""
    uid = uuid.uuid4().hex[:8]
    today = get_today_ist()

    async with AsyncSessionLocal() as db:
        hosp = Hospital(name=f"HospExcel_{uid}", email=f"excel_{uid}@test.com", address="500 Medical Center")
        db.add(hosp)
        await db.flush()

        pat = _create_patient(hosp.id, uid, "xl", first_name="ExcelPat", last_name="Test")
        doc = _create_doctor(hosp.id, uid, "xl", first_name="ExcelDoc", last_name="Smith")
        db.add_all([pat, doc])
        await db.flush()

        apt = Appointment(
            appointment_number=f"APT_EXCEL_{uid}",
            patient_id=pat.id,
            doctor_id=doc.id,
            hospital_id=hosp.id,
            appointment_date=today,
            appointment_time=time(11, 15),
            appointment_status="Confirmed",
            booking_source="staff",
        )
        db.add(apt)
        await db.commit()

        user = _make_fake_user(user_id=1, hospital_id=hosp.id)
        service = AppointmentService(db)
        data_bytes, media_type = await service.export_appointments("excel", current_user=user)

        assert media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        assert len(data_bytes) > 0

        # Load workbook
        wb = openpyxl.load_workbook(BytesIO(data_bytes))
        ws = wb.active
        assert ws.title == "Appointments Export"

        # Check hospital name in row 1
        assert hosp.name in str(ws.cell(row=1, column=1).value)

        # Check headers in row 5
        headers = [ws.cell(row=5, column=col).value for col in range(1, 19)]
        assert "Appointment Number" in headers
        assert "Doctor" in headers
        assert "Status" in headers

        # Check data row in row 6
        assert ws.cell(row=6, column=2).value == f"APT_EXCEL_{uid}"


@pytest.mark.asyncio
async def test_pdf_export_rendering_and_unicode():
    """Verify PDF export produces valid PDF bytes with Unicode characters."""
    uid = uuid.uuid4().hex[:8]
    today = get_today_ist()

    async with AsyncSessionLocal() as db:
        hosp = Hospital(name=f"HospPDF_{uid}", email=f"pdf_{uid}@test.com")
        db.add(hosp)
        await db.flush()

        # Test Unicode name
        pat = _create_patient(hosp.id, uid, "pdf", first_name="अमित", last_name="शर्मा")
        doc = _create_doctor(hosp.id, uid, "pdf", first_name="डॉक्टर", last_name="वर्मा")
        db.add_all([pat, doc])
        await db.flush()

        apt = Appointment(
            appointment_number=f"APT_PDF_{uid}",
            patient_id=pat.id,
            doctor_id=doc.id,
            hospital_id=hosp.id,
            appointment_date=today,
            appointment_time=time(14, 30),
            appointment_status="Completed",
        )
        db.add(apt)
        await db.commit()

        user = _make_fake_user(user_id=1, hospital_id=hosp.id)
        service = AppointmentService(db)
        pdf_bytes, media_type = await service.export_appointments("pdf", current_user=user)

        assert media_type == "application/pdf"
        assert len(pdf_bytes) > 0
        assert pdf_bytes.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_export_patient_role_forbidden():
    """Verify that Patient role is forbidden from exporting appointments."""
    user = _make_fake_user(user_id=1, hospital_id=10, role_name="patient")

    async with AsyncSessionLocal() as db:
        service = AppointmentService(db)
        with pytest.raises(ForbiddenException):
            await service.export_appointments("excel", current_user=user)


@pytest.mark.asyncio
async def test_export_tenant_isolation():
    """Verify that export only contains appointments for the authorized hospital."""
    uid = uuid.uuid4().hex[:8]
    today = get_today_ist()

    async with AsyncSessionLocal() as db:
        hosp_a = Hospital(name=f"HospA_Exp_{uid}", email=f"a_exp_{uid}@test.com")
        hosp_b = Hospital(name=f"HospB_Exp_{uid}", email=f"b_exp_{uid}@test.com")
        db.add_all([hosp_a, hosp_b])
        await db.flush()

        pat_a = _create_patient(hosp_a.id, uid, "ea")
        pat_b = _create_patient(hosp_b.id, uid, "eb")
        doc_a = _create_doctor(hosp_a.id, uid, "ea")
        doc_b = _create_doctor(hosp_b.id, uid, "eb")
        db.add_all([pat_a, pat_b, doc_a, doc_b])
        await db.flush()

        db.add(Appointment(
            appointment_number=f"APT_A_{uid}",
            patient_id=pat_a.id,
            doctor_id=doc_a.id,
            hospital_id=hosp_a.id,
            appointment_date=today,
            appointment_time=time(10, 0),
            appointment_status="Confirmed",
        ))
        db.add(Appointment(
            appointment_number=f"APT_B_{uid}",
            patient_id=pat_b.id,
            doctor_id=doc_b.id,
            hospital_id=hosp_b.id,
            appointment_date=today,
            appointment_time=time(11, 0),
            appointment_status="Confirmed",
        ))
        await db.commit()

        user_a = _make_fake_user(user_id=1, hospital_id=hosp_a.id)
        service = AppointmentService(db)
        data_bytes, _ = await service.export_appointments("excel", current_user=user_a)

        wb = openpyxl.load_workbook(BytesIO(data_bytes))
        ws = wb.active
        values = [str(cell.value) for row in ws.iter_rows() for cell in row if cell.value]

        assert f"APT_A_{uid}" in values
        assert f"APT_B_{uid}" not in values


@pytest.mark.asyncio
async def test_api_endpoints_export_and_removal_verification():
    """
    Verify:
    1. GET /api/v1/appointments returns 200 with all 12 dashboard counts.
    2. GET /api/v1/appointments/export?format=excel returns 200 with attachment header.
    3. GET /api/v1/appointments/export?format=pdf returns 200 with application/pdf.
    4. GET /api/v1/appointments/dashboard-summary returns 404 (Removed as redundant).
    """
    uid = uuid.uuid4().hex[:8]
    today = get_today_ist()

    async with AsyncSessionLocal() as db:
        hosp = Hospital(name=f"HospAPI_{uid}", email=f"api_{uid}@test.com")
        db.add(hosp)
        await db.flush()

        pat = _create_patient(hosp.id, uid, "api")
        doc = _create_doctor(hosp.id, uid, "api")
        db.add_all([pat, doc])
        await db.flush()

        apt = Appointment(
            appointment_number=f"APT_API_{uid}",
            patient_id=pat.id,
            doctor_id=doc.id,
            hospital_id=hosp.id,
            appointment_date=today,
            appointment_time=time(10, 0),
            appointment_status="Confirmed",
        )
        db.add(apt)
        await db.commit()
        hosp_id = hosp.id

    fake_user = _make_fake_user(user_id=1, hospital_id=hosp_id, role_name="hospital_admin")
    app.dependency_overrides[get_current_active_user] = lambda: fake_user
    app.dependency_overrides[get_current_user] = lambda: fake_user

    transport = ASGITransport(app=app)
    headers = {"Authorization": "Bearer fake-token"}

    try:
        async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as ac:
            with patch("app.repositories.rbac_repository.RBACRepository.get_user_permissions", new=AsyncMock(return_value=["appointments:read"])):
                # 1. Existing GET /api/v1/appointments returns all counts
                resp_list = await ac.get("/api/v1/appointments")
                assert resp_list.status_code == 200, resp_list.text
                data = resp_list.json()["data"]
                assert data["total_appointments"] >= 1
                assert data["confirmed"] >= 1
                assert "total_scheduled" in data
                assert "waiting" in data
                assert "in_progress" in data
                assert "checked_in" in data
                assert "admitted" in data
                assert "completed" in data
                assert "checked_out" in data
                assert "cancelled" in data
                assert "no_show" not in data

                # 2. Test GET /export?format=excel
                resp_excel = await ac.get("/api/v1/appointments/export?format=excel")
                assert resp_excel.status_code == 200
                assert resp_excel.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                assert "attachment; filename=" in resp_excel.headers["content-disposition"]
                assert resp_excel.headers["content-disposition"].endswith(".xlsx")

                # 3. Test GET /export?format=pdf
                resp_pdf = await ac.get("/api/v1/appointments/export?format=pdf")
                assert resp_pdf.status_code == 200
                assert resp_pdf.headers["content-type"] == "application/pdf"
                assert "attachment; filename=" in resp_pdf.headers["content-disposition"]
                assert resp_pdf.headers["content-disposition"].endswith(".pdf")
                assert resp_pdf.content.startswith(b"%PDF")

                # 4. Verify removed endpoint returns 404 Not Found (or 422 if treated as ID, but route is gone)
                resp_removed = await ac.get("/api/v1/appointments/dashboard-summary")
                assert resp_removed.status_code in (404, 422), f"Expected 404/422 but got {resp_removed.status_code}"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_current_user, None)



# ==============================================================================
# PHASE 2 FOCUSED TESTS: DATE FILTERING, TENANT ISOLATION & NO SHOW SEPARATION
# ==============================================================================

@pytest.mark.asyncio
async def test_dashboard_date_filtering_scopes_status_counts_correctly():
    """
    Verify that:
    1. total_appointments is all-time historical tenant count.
    2. Status counts (completed, cancelled, pending, etc.) are scoped to the active date range.
    3. date_filter=today scopes status counts to today only.
    4. date_filter=last_7_days scopes status counts to the 7-day window.
    5. date_filter=custom scopes status counts to [start_date, end_date].
    """
    uid = uuid.uuid4().hex[:8]
    today = get_today_ist()
    three_days_ago = today - timedelta(days=3)
    ten_days_ago = today - timedelta(days=10)

    async with AsyncSessionLocal() as db:
        hosp = Hospital(
            name=f"Hosp DateFilter {uid}",
            email=f"datefilter_{uid}@hosp.com",
            phone="9123456780",
            address="123 Care Street",
        )
        db.add(hosp)
        await db.flush()

        doc = _create_doctor(hosp.id, uid, "DF1")
        pat = _create_patient(hosp.id, uid, "DF1")
        db.add_all([doc, pat])
        await db.flush()

        # Appt 1: Completed on TODAY
        a_today = Appointment(
            appointment_number=f"APT_TODAY_{uid}",
            patient_id=pat.id,
            doctor_id=doc.id,
            hospital_id=hosp.id,
            appointment_date=today,
            appointment_time=time(10, 0),
            appointment_status="Completed",
        )
        # Appt 2: Completed 3 DAYS AGO (within last_7_days)
        a_3d = Appointment(
            appointment_number=f"APT_3D_{uid}",
            patient_id=pat.id,
            doctor_id=doc.id,
            hospital_id=hosp.id,
            appointment_date=three_days_ago,
            appointment_time=time(11, 0),
            appointment_status="Completed",
        )
        # Appt 3: Completed 10 DAYS AGO (outside last_7_days, within all-time)
        a_10d = Appointment(
            appointment_number=f"APT_10D_{uid}",
            patient_id=pat.id,
            doctor_id=doc.id,
            hospital_id=hosp.id,
            appointment_date=ten_days_ago,
            appointment_time=time(12, 0),
            appointment_status="Completed",
        )
        db.add_all([a_today, a_3d, a_10d])
        await db.commit()

        user = _make_fake_user(user_id=1, hospital_id=hosp.id)
        service = AppointmentService(db)

        # 1. No filter -> all-time: total=3, completed=3
        res_all = await service.list_appointments(current_user=user)
        assert res_all["total_appointments"] == 3
        assert res_all["completed"] == 3

        # 2. date_filter="today" -> total remains 3 (historical), completed is 1 (only today)
        res_today = await service.list_appointments(current_user=user, date_filter="today")
        assert res_today["total_appointments"] == 3
        assert res_today["today_appointments"] == 1
        assert res_today["completed"] == 1

        # 3. date_filter="last_7_days" -> total remains 3, completed is 2 (today + 3 days ago)
        res_7d = await service.list_appointments(current_user=user, date_filter="last_7_days")
        assert res_7d["total_appointments"] == 3
        assert res_7d["completed"] == 2

        # 4. date_filter="custom" [ten_days_ago, three_days_ago] -> completed is 2 (3d and 10d)
        res_custom = await service.list_appointments(
            current_user=user, date_filter="custom", start_date=ten_days_ago, end_date=three_days_ago
        )
        assert res_custom["total_appointments"] == 3
        assert res_custom["completed"] == 2

        # 5. Direct appointment_date filter
        res_date = await service.list_appointments(current_user=user, appointment_date=three_days_ago)
        assert res_date["total_appointments"] == 3
        assert res_date["completed"] == 1


@pytest.mark.asyncio
async def test_cancelled_count_aggregates_cancelled_and_no_show():
    """
    Verify that:
    1. Cancelled count aggregates both Cancelled and No Show appointments.
    2. No separate no_show key exists in dashboard metrics.
    3. status=Cancelled filter returns ONLY Cancelled records.
    4. status=No Show filter returns ONLY No Show records.
    """
    uid = uuid.uuid4().hex[:8]
    today = get_today_ist()

    async with AsyncSessionLocal() as db:
        hosp = Hospital(
            name=f"Hosp NoShow {uid}",
            email=f"noshow_{uid}@hosp.com",
            phone="9123456781",
            address="456 Care Lane",
        )
        db.add(hosp)
        await db.flush()

        doc = _create_doctor(hosp.id, uid, "NS1")
        pat = _create_patient(hosp.id, uid, "NS1")
        db.add_all([doc, pat])
        await db.flush()

        # 2 Cancelled appointments
        can1 = Appointment(
            appointment_number=f"APT_C1_{uid}",
            patient_id=pat.id,
            doctor_id=doc.id,
            hospital_id=hosp.id,
            appointment_date=today,
            appointment_time=time(10, 0),
            appointment_status="Cancelled",
        )
        can2 = Appointment(
            appointment_number=f"APT_C2_{uid}",
            patient_id=pat.id,
            doctor_id=doc.id,
            hospital_id=hosp.id,
            appointment_date=today,
            appointment_time=time(11, 0),
            appointment_status="Cancelled",
        )
        # 1 No Show appointment
        ns1 = Appointment(
            appointment_number=f"APT_NS1_{uid}",
            patient_id=pat.id,
            doctor_id=doc.id,
            hospital_id=hosp.id,
            appointment_date=today,
            appointment_time=time(12, 0),
            appointment_status="No Show",
        )
        db.add_all([can1, can2, ns1])
        await db.commit()

        user = _make_fake_user(user_id=1, hospital_id=hosp.id)
        service = AppointmentService(db)

        # Listing without filter
        res = await service.list_appointments(current_user=user)
        assert res["total_appointments"] == 3
        assert res["cancelled"] == 3  # 2 Cancelled + 1 No Show combined
        assert "no_show" not in res
        assert "total_today_appointments" not in res

        # Listing with status="Cancelled"
        res_can = await service.list_appointments(current_user=user, status="Cancelled")
        assert res_can["total"] == 2
        for item in res_can["items"]:
            assert item.appointment_status == "Cancelled"

        # Listing with status="No Show"
        res_ns = await service.list_appointments(current_user=user, status="No Show")
        assert res_ns["total"] == 1
        for item in res_ns["items"]:
            assert item.appointment_status == "No Show"


@pytest.mark.asyncio
async def test_super_admin_x_hospital_id_enforcement_and_validation():
    """
    Verify Super Admin security rules:
    Rule 1: Super Admin with valid active X-Hospital-Id accesses that hospital.
    Rule 2: Inactive hospital is rejected with HTTP 400 BadRequestException.
    Rule 3: Nonexistent hospital ID is rejected with HTTP 400 BadRequestException.
    Rule 4: Super Admin without X-Hospital-Id is rejected with HTTP 400.
    Rule 5: Normal hospital user cannot switch tenants via X-Hospital-Id.
    Rule 6: Export and listing use identical validation.
    """
    uid = uuid.uuid4().hex[:8]
    today = get_today_ist()

    async with AsyncSessionLocal() as db:
        h1 = Hospital(name=f"Hosp One {uid}", email=f"h1_{uid}@h.com", phone="1", address="A", is_active=True)
        h2 = Hospital(name=f"Hosp Two {uid}", email=f"h2_{uid}@h.com", phone="2", address="B", is_active=True)
        h_inactive = Hospital(name=f"Hosp Inactive {uid}", email=f"inact_{uid}@h.com", phone="3", address="C", is_active=False)
        db.add_all([h1, h2, h_inactive])
        await db.flush()
        h1_id = h1.id
        h2_id = h2.id
        h_inact_id = h_inactive.id

        doc1 = _create_doctor(h1_id, uid, "SA1")
        pat1 = _create_patient(h1_id, uid, "SA1")
        db.add_all([doc1, pat1])
        await db.flush()

        a1 = Appointment(
            appointment_number=f"APT_H1_{uid}",
            patient_id=pat1.id,
            doctor_id=doc1.id,
            hospital_id=h1_id,
            appointment_date=today,
            appointment_time=time(9, 0),
            appointment_status="Confirmed",
        )
        db.add(a1)
        await db.commit()

        service = AppointmentService(db)

        # Super Admin user (hospital_id = None)
        super_admin = _make_fake_user(user_id=99, hospital_id=None, role_name="Super Admin")
        from app.core.exceptions import BadRequestException, ForbiddenException

        # 1. Super Admin without X-Hospital-Id -> BadRequestException (listing & export)
        with pytest.raises(BadRequestException) as exc_info:
            await service.list_appointments(current_user=super_admin, x_hospital_id=None)
        assert "X-Hospital-Id header is required" in str(exc_info.value)

        with pytest.raises(BadRequestException) as exc_exp_no:
            await service.export_appointments(format_type="excel", current_user=super_admin, x_hospital_id=None)
        assert "X-Hospital-Id header is required" in str(exc_exp_no.value)

        # 2. Super Admin with nonexistent X-Hospital-Id -> BadRequestException (listing & export)
        with pytest.raises(BadRequestException) as exc_info2:
            await service.list_appointments(current_user=super_admin, x_hospital_id=999999)
        assert "does not exist" in str(exc_info2.value)

        with pytest.raises(BadRequestException) as exc_exp_inv:
            await service.export_appointments(format_type="excel", current_user=super_admin, x_hospital_id=999999)
        assert "does not exist" in str(exc_exp_inv.value)

        # 3. Super Admin with inactive hospital -> BadRequestException (listing & export)
        with pytest.raises(BadRequestException) as exc_inact:
            await service.list_appointments(current_user=super_admin, x_hospital_id=h_inact_id)
        assert "is inactive" in str(exc_inact.value)

        with pytest.raises(BadRequestException) as exc_exp_inact:
            await service.export_appointments(format_type="excel", current_user=super_admin, x_hospital_id=h_inact_id)
        assert "is inactive" in str(exc_exp_inact.value)

        # 4. Super Admin with valid active X-Hospital-Id -> Success, sees only H1
        res_sa = await service.list_appointments(current_user=super_admin, x_hospital_id=h1_id)
        assert res_sa["total"] == 1
        assert res_sa["items"][0].appointment_number == f"APT_H1_{uid}"

        content, media_type = await service.export_appointments(
            format_type="excel", current_user=super_admin, x_hospital_id=h1_id
        )
        assert len(content) > 0
        assert "spreadsheetml" in media_type

        # 5. Normal Hospital Admin of H1 with matching header -> Success
        normal_admin = _make_fake_user(user_id=10, hospital_id=h1_id, role_name="hospital_admin")
        res_norm = await service.list_appointments(current_user=normal_admin, x_hospital_id=h1_id)
        assert res_norm["total"] == 1

        # 6. Normal Hospital Admin of H1 without header -> Success
        res_norm_no = await service.list_appointments(current_user=normal_admin, x_hospital_id=None)
        assert res_norm_no["total"] == 1

        # 7. Normal Hospital Admin of H1 trying to access H2 -> ForbiddenException
        with pytest.raises(ForbiddenException):
            await service.list_appointments(current_user=normal_admin, x_hospital_id=h2_id)

        with pytest.raises(ForbiddenException):
            await service.export_appointments(format_type="excel", current_user=normal_admin, x_hospital_id=h2_id)


@pytest.mark.asyncio
async def test_pagination_independence_for_summary_counts():
    """Verify that page and size do not reduce or alter dashboard summary counts."""
    uid = uuid.uuid4().hex[:8]
    today = get_today_ist()

    async with AsyncSessionLocal() as db:
        hosp = Hospital(
            name=f"Hosp Pag {uid}",
            email=f"pag_{uid}@hosp.com",
            phone="9123456782",
            address="789 Care Blvd",
        )
        db.add(hosp)
        await db.flush()

        doc = _create_doctor(hosp.id, uid, "PG1")
        pat = _create_patient(hosp.id, uid, "PG1")
        db.add_all([doc, pat])
        await db.flush()

        appts = [
            Appointment(
                appointment_number=f"APT_PG_{i}_{uid}",
                patient_id=pat.id,
                doctor_id=doc.id,
                hospital_id=hosp.id,
                appointment_date=today,
                appointment_time=time(9 + i, 0),
                appointment_status="Confirmed",
            )
            for i in range(5)
        ]
        db.add_all(appts)
        await db.commit()

        user = _make_fake_user(user_id=1, hospital_id=hosp.id)
        service = AppointmentService(db)

        # Query page 1, size 2 -> items length is 2, but total_appointments and confirmed remain 5
        res = await service.list_appointments(current_user=user, page=1, size=2)
        assert len(res["items"]) == 2
        assert res["total"] == 5
        assert res["total_appointments"] == 5
        assert res["confirmed"] == 5


@pytest.mark.asyncio
async def test_api_route_super_admin_x_hospital_id_http_behavior():
    """
    Test FastAPI route integration with X-Hospital-Id header:
    1. Super Admin with valid active X-Hospital-Id gets 200 for listing and export.
    2. Super Admin without X-Hospital-Id gets 400 for listing and export.
    3. Super Admin with nonexistent X-Hospital-Id gets 400 for listing and export.
    4. Super Admin with inactive hospital gets 400 for listing and export.
    5. Normal Hospital Admin with matching X-Hospital-Id gets 200.
    6. Normal Hospital Admin with mismatched X-Hospital-Id gets 403.
    """
    uid = uuid.uuid4().hex[:8]
    today = get_today_ist()

    async with AsyncSessionLocal() as db:
        h1 = Hospital(name=f"API Hosp 1 {uid}", email=f"api1_{uid}@h.com", phone="11", address="Addr 1", is_active=True)
        h2 = Hospital(name=f"API Hosp 2 {uid}", email=f"api2_{uid}@h.com", phone="22", address="Addr 2", is_active=True)
        h_inactive = Hospital(name=f"API Hosp Inact {uid}", email=f"api_inact_{uid}@h.com", phone="33", address="Addr 3", is_active=False)
        db.add_all([h1, h2, h_inactive])
        await db.flush()
        h1_id = h1.id
        h2_id = h2.id
        h_inact_id = h_inactive.id

        doc1 = _create_doctor(h1_id, uid, "API1")
        pat1 = _create_patient(h1_id, uid, "API1")
        db.add_all([doc1, pat1])
        await db.flush()

        apt = Appointment(
            appointment_number=f"APT_API_{uid}",
            patient_id=pat1.id,
            doctor_id=doc1.id,
            hospital_id=h1_id,
            appointment_date=today,
            appointment_time=time(10, 0),
            appointment_status="Confirmed",
        )
        db.add(apt)
        await db.commit()

    # Test Super Admin user
    super_admin = _make_fake_user(user_id=101, hospital_id=None, role_name="Super Admin")
    app.dependency_overrides[get_current_active_user] = lambda: super_admin
    app.dependency_overrides[get_current_user] = lambda: super_admin

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("app.repositories.rbac_repository.RBACRepository.get_user_permissions", new=AsyncMock(return_value=["appointments:read"])):
                # 1. Super Admin without X-Hospital-Id -> 400
                r_no_h = await ac.get("/api/v1/appointments")
                assert r_no_h.status_code == 400, r_no_h.text
                assert "X-Hospital-Id header is required" in r_no_h.text

                # 2. Super Admin with invalid X-Hospital-Id -> 400
                r_inv_h = await ac.get("/api/v1/appointments", headers={"X-Hospital-Id": "999999"})
                assert r_inv_h.status_code == 400, r_inv_h.text
                assert "does not exist" in r_inv_h.text

                # 3. Super Admin with inactive X-Hospital-Id -> 400
                r_inact_h = await ac.get("/api/v1/appointments", headers={"X-Hospital-Id": str(h_inact_id)})
                assert r_inact_h.status_code == 400, r_inact_h.text
                assert "is inactive" in r_inact_h.text

                # 4. Super Admin with valid active X-Hospital-Id -> 200
                r_valid = await ac.get("/api/v1/appointments", headers={"X-Hospital-Id": str(h1_id)})
                assert r_valid.status_code == 200, r_valid.text
                data = r_valid.json()["data"]
                assert data["total"] == 1
                assert data["items"][0]["appointment_number"] == f"APT_API_{uid}"
                assert "cancelled" in data
                assert "no_show" not in data

                # 5. Super Admin export without X-Hospital-Id -> 400
                r_exp_no = await ac.get("/api/v1/appointments/export?format=excel")
                assert r_exp_no.status_code == 400

                # 6. Super Admin export with inactive X-Hospital-Id -> 400
                r_exp_inact = await ac.get("/api/v1/appointments/export?format=excel", headers={"X-Hospital-Id": str(h_inact_id)})
                assert r_exp_inact.status_code == 400
                assert "is inactive" in r_exp_inact.text

                # 7. Super Admin export with valid X-Hospital-Id -> 200
                r_exp_valid = await ac.get("/api/v1/appointments/export?format=excel", headers={"X-Hospital-Id": str(h1_id)})
                assert r_exp_valid.status_code == 200

                # 8. Normal Admin passing mismatched X-Hospital-Id -> 403
                normal_admin = _make_fake_user(user_id=102, hospital_id=h1_id, role_name="hospital_admin")
                app.dependency_overrides[get_current_active_user] = lambda: normal_admin
                app.dependency_overrides[get_current_user] = lambda: normal_admin

                r_mismatch = await ac.get("/api/v1/appointments", headers={"X-Hospital-Id": str(h2_id)})
                assert r_mismatch.status_code == 403, r_mismatch.text

                r_exp_mismatch = await ac.get("/api/v1/appointments/export?format=excel", headers={"X-Hospital-Id": str(h2_id)})
                assert r_exp_mismatch.status_code == 403, r_exp_mismatch.text

                # 9. Normal Admin passing matching X-Hospital-Id -> 200
                r_match = await ac.get("/api/v1/appointments", headers={"X-Hospital-Id": str(h1_id)})
                assert r_match.status_code == 200, r_match.text

                # 10. Normal Admin without X-Hospital-Id -> 200
                r_default = await ac.get("/api/v1/appointments")
                assert r_default.status_code == 200, r_default.text
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_current_user, None)
