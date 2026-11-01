import uuid
import pytest
from datetime import date, time
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock

from app.main import app
from app.models.hospital_model import Hospital
from app.models.doctor_model import Doctor
from app.models.patient_model import Patient
from app.models.appointment_model import Appointment
from app.core.database import AsyncSessionLocal, engine
from app.core.dependencies import get_current_active_user, get_current_user
from app.utils.helpers import utc_now


@pytest.fixture(autouse=True)
async def cleanup_engine():
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_doctor_filter_matching_non_matching_and_omitted():
    """Verify that doctor_id filter matches only patients of that doctor, and omitted returns all."""
    uid = uuid.uuid4().hex[:8]

    async with AsyncSessionLocal() as db:
        # 1. Setup Hospital
        hosp = Hospital(
            name=f"Hosp DoctorFilter {uid}",
            email=f"hosp_{uid}@test.com",
            phone="+919999999991",
            address="123 Care Street",
        )
        db.add(hosp)
        await db.flush()

        # 2. Setup Doctors
        doc1 = Doctor(
            hospital_id=hosp.id,
            doctor_code=f"DOC1_{uid}",
            first_name="Alice",
            last_name="Smith",
            specialization="Cardiology",
            license_number=f"LIC1_{uid}",
        )
        doc2 = Doctor(
            hospital_id=hosp.id,
            doctor_code=f"DOC2_{uid}",
            first_name="Bob",
            last_name="Jones",
            specialization="Neurology",
            license_number=f"LIC2_{uid}",
        )
        db.add_all([doc1, doc2])
        await db.flush()

        # 3. Setup Patients
        p1 = Patient(
            hospital_id=hosp.id,
            patient_code=f"PAT1_{uid}",
            first_name="Charlie",
            last_name="Brown",
            gender="Male",
            status="active",
            created_at=utc_now(),
        )
        p2 = Patient(
            hospital_id=hosp.id,
            patient_code=f"PAT2_{uid}",
            first_name="Diana",
            last_name="Prince",
            gender="Female",
            status="active",
            created_at=utc_now(),
        )
        db.add_all([p1, p2])
        await db.flush()

        # 4. Setup Appointments
        appt1 = Appointment(
            hospital_id=hosp.id,
            appointment_number=f"APP1_{uid}",
            patient_id=p1.id,
            doctor_id=doc1.id,
            appointment_date=date.today(),
            appointment_time=time(10, 0),
            appointment_status="Confirmed",
        )
        appt2 = Appointment(
            hospital_id=hosp.id,
            appointment_number=f"APP2_{uid}",
            patient_id=p2.id,
            doctor_id=doc2.id,
            appointment_date=date.today(),
            appointment_time=time(11, 0),
            appointment_status="Confirmed",
        )
        db.add_all([appt1, appt2])
        await db.commit()

        doc1_id, doc2_id, p1_id, p2_id, hosp_id = doc1.id, doc2.id, p1.id, p2.id, hosp.id

    class FakeAdmin:
        id = 9001
        role_id = 1
        hospital_id = hosp_id
        is_active = True
        is_verified = True
        email = f"admin_{uid}@test.com"

        class role:
            name = "hospital_admin"

    fake_admin = FakeAdmin()
    app.dependency_overrides[get_current_active_user] = lambda: fake_admin
    app.dependency_overrides[get_current_user] = lambda: fake_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with patch("app.core.dependencies.require_permission") as mock_perm:
            mock_perm.return_value = lambda: fake_admin
            with patch(
                "app.repositories.rbac_repository.RBACRepository.get_user_permissions",
                new=AsyncMock(return_value=["patients:read"]),
            ):
                # A. Filter by Doctor 1 -> returns only Patient 1
                resp1 = await ac.get(f"/api/v1/patients?doctor_id={doc1_id}")
                assert resp1.status_code == 200, resp1.text
                data1 = resp1.json()["data"]
                item_ids1 = [item["id"] for item in data1["items"]]
                assert p1_id in item_ids1
                assert p2_id not in item_ids1
                assert data1["total"] == 1

                # B. Filter by Doctor 2 -> returns only Patient 2
                resp2 = await ac.get(f"/api/v1/patients?doctor_id={doc2_id}")
                assert resp2.status_code == 200, resp2.text
                data2 = resp2.json()["data"]
                item_ids2 = [item["id"] for item in data2["items"]]
                assert p2_id in item_ids2
                assert p1_id not in item_ids2
                assert data2["total"] == 1

                # C. Omitted doctor_id -> returns both Patient 1 and Patient 2
                resp_all = await ac.get("/api/v1/patients")
                assert resp_all.status_code == 200, resp_all.text
                data_all = resp_all.json()["data"]
                item_ids_all = [item["id"] for item in data_all["items"]]
                assert p1_id in item_ids_all
                assert p2_id in item_ids_all
                assert data_all["total"] >= 2

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_doctor_filter_duplicate_appointments_no_row_multiplication():
    """Verify that multiple appointments with the same doctor do NOT cause row duplication or wrong counts."""
    uid = uuid.uuid4().hex[:8]

    async with AsyncSessionLocal() as db:
        hosp = Hospital(
            name=f"Hosp DupAppt {uid}",
            email=f"hosp_dup_{uid}@test.com",
            phone="+919999999992",
            address="456 Care Street",
        )
        db.add(hosp)
        await db.flush()

        doc = Doctor(
            hospital_id=hosp.id,
            doctor_code=f"DOC_DUP_{uid}",
            first_name="Emily",
            last_name="Watson",
            specialization="Pediatrics",
            license_number=f"LIC_DUP_{uid}",
        )
        db.add(doc)
        await db.flush()

        p = Patient(
            hospital_id=hosp.id,
            patient_code=f"PAT_DUP_{uid}",
            first_name="Frank",
            last_name="Miller",
            gender="Male",
            status="active",
            created_at=utc_now(),
        )
        db.add(p)
        await db.flush()

        # Create 3 separate appointments for the SAME patient with the SAME doctor
        appts = [
            Appointment(
                hospital_id=hosp.id,
                appointment_number=f"APP_DUP1_{uid}",
                patient_id=p.id,
                doctor_id=doc.id,
                appointment_date=date.today(),
                appointment_time=time(9, 0),
                appointment_status="Completed",
            ),
            Appointment(
                hospital_id=hosp.id,
                appointment_number=f"APP_DUP2_{uid}",
                patient_id=p.id,
                doctor_id=doc.id,
                appointment_date=date.today(),
                appointment_time=time(10, 0),
                appointment_status="Confirmed",
            ),
            Appointment(
                hospital_id=hosp.id,
                appointment_number=f"APP_DUP3_{uid}",
                patient_id=p.id,
                doctor_id=doc.id,
                appointment_date=date.today(),
                appointment_time=time(11, 0),
                appointment_status="Pending",
            ),
        ]
        db.add_all(appts)
        await db.commit()

        doc_id, p_id, hosp_id = doc.id, p.id, hosp.id

    class FakeAdmin:
        id = 9002
        role_id = 1
        hospital_id = hosp_id
        is_active = True
        is_verified = True
        email = f"admin_dup_{uid}@test.com"

        class role:
            name = "hospital_admin"

    fake_admin = FakeAdmin()
    app.dependency_overrides[get_current_active_user] = lambda: fake_admin
    app.dependency_overrides[get_current_user] = lambda: fake_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with patch("app.core.dependencies.require_permission") as mock_perm:
            mock_perm.return_value = lambda: fake_admin
            with patch(
                "app.repositories.rbac_repository.RBACRepository.get_user_permissions",
                new=AsyncMock(return_value=["patients:read"]),
            ):
                resp = await ac.get(f"/api/v1/patients?doctor_id={doc_id}")
                assert resp.status_code == 200, resp.text
                data = resp.json()["data"]

                # Patient must appear EXACTLY once, not 3 times
                matched_items = [item for item in data["items"] if item["id"] == p_id]
                assert len(matched_items) == 1, f"Expected 1 item, got {len(matched_items)}"
                assert data["total"] == 1, f"Expected total 1, got {data['total']}"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_doctor_filter_pagination_and_sorting():
    """Verify that doctor_id works properly with pagination and sorting."""
    uid = uuid.uuid4().hex[:8]

    async with AsyncSessionLocal() as db:
        hosp = Hospital(
            name=f"Hosp Page {uid}",
            email=f"hosp_page_{uid}@test.com",
            phone="+919999999993",
            address="789 Care Street",
        )
        db.add(hosp)
        await db.flush()

        doc = Doctor(
            hospital_id=hosp.id,
            doctor_code=f"DOC_PG_{uid}",
            first_name="George",
            last_name="Martin",
            specialization="General",
            license_number=f"LIC_PG_{uid}",
        )
        db.add(doc)
        await db.flush()

        patients = []
        for i in range(5):
            p = Patient(
                hospital_id=hosp.id,
                patient_code=f"PAT_PG_{uid}_{i}",
                first_name=f"Patient_{i}_{uid}",
                last_name="Test",
                gender="Male",
                status="active",
                created_at=utc_now(),
            )
            patients.append(p)
        db.add_all(patients)
        await db.flush()

        for i, p in enumerate(patients):
            appt = Appointment(
                hospital_id=hosp.id,
                appointment_number=f"APP_PG_{uid}_{i}",
                patient_id=p.id,
                doctor_id=doc.id,
                appointment_date=date.today(),
                appointment_time=time(10, i),
                appointment_status="Confirmed",
            )
            db.add(appt)
        await db.commit()

        doc_id, hosp_id = doc.id, hosp.id

    class FakeAdmin:
        id = 9003
        role_id = 1
        hospital_id = hosp_id
        is_active = True
        is_verified = True
        email = f"admin_pg_{uid}@test.com"

        class role:
            name = "hospital_admin"

    fake_admin = FakeAdmin()
    app.dependency_overrides[get_current_active_user] = lambda: fake_admin
    app.dependency_overrides[get_current_user] = lambda: fake_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with patch("app.core.dependencies.require_permission") as mock_perm:
            mock_perm.return_value = lambda: fake_admin
            with patch(
                "app.repositories.rbac_repository.RBACRepository.get_user_permissions",
                new=AsyncMock(return_value=["patients:read"]),
            ):
                # Page 1, size 2
                resp1 = await ac.get(f"/api/v1/patients?doctor_id={doc_id}&page=1&size=2")
                assert resp1.status_code == 200, resp1.text
                d1 = resp1.json()["data"]
                assert len(d1["items"]) == 2
                assert d1["total"] == 5
                assert d1["pages"] == 3
                assert d1["page"] == 1

                # Page 3, size 2 (should have remaining 1 item)
                resp3 = await ac.get(f"/api/v1/patients?doctor_id={doc_id}&page=3&size=2")
                assert resp3.status_code == 200, resp3.text
                d3 = resp3.json()["data"]
                assert len(d3["items"]) == 1
                assert d3["total"] == 5

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_doctor_filter_invalid_id_and_validation():
    """Verify that non-existent doctor_id returns 404 and invalid doctor_id < 1 returns 422."""
    class FakeAdmin:
        id = 9004
        role_id = 1
        hospital_id = 1
        is_active = True
        is_verified = True
        email = "admin_err@test.com"

        class role:
            name = "hospital_admin"

    fake_admin = FakeAdmin()
    app.dependency_overrides[get_current_active_user] = lambda: fake_admin
    app.dependency_overrides[get_current_user] = lambda: fake_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with patch("app.core.dependencies.require_permission") as mock_perm:
            mock_perm.return_value = lambda: fake_admin
            with patch(
                "app.repositories.rbac_repository.RBACRepository.get_user_permissions",
                new=AsyncMock(return_value=["patients:read"]),
            ):
                # 1. Non-existent doctor ID -> 404 Not Found
                resp_404 = await ac.get("/api/v1/patients?doctor_id=99999999")
                assert resp_404.status_code == 404, resp_404.text
                assert "Doctor not found" in resp_404.text

                # 2. doctor_id = 0 (violates ge=1) -> 422 Unprocessable Entity
                resp_422 = await ac.get("/api/v1/patients?doctor_id=0")
                assert resp_422.status_code == 422, resp_422.text

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_doctor_filter_hospital_tenant_isolation():
    """Verify that a user in Hospital 1 cannot query doctor_id belonging to Hospital 2."""
    uid = uuid.uuid4().hex[:8]

    async with AsyncSessionLocal() as db:
        # Hospital 1 & Doctor 1
        hosp1 = Hospital(
            name=f"Hosp Iso 1 {uid}",
            email=f"hosp_iso1_{uid}@test.com",
            phone="+919999999994",
            address="100 Hospital Way",
        )
        # Hospital 2 & Doctor 2
        hosp2 = Hospital(
            name=f"Hosp Iso 2 {uid}",
            email=f"hosp_iso2_{uid}@test.com",
            phone="+919999999995",
            address="200 Hospital Way",
        )
        db.add_all([hosp1, hosp2])
        await db.flush()

        doc_hosp2 = Doctor(
            hospital_id=hosp2.id,
            doctor_code=f"DOC_ISO2_{uid}",
            first_name="Hosp2",
            last_name="Doctor",
            specialization="Orthopedics",
            license_number=f"LIC_ISO2_{uid}",
        )
        db.add(doc_hosp2)
        await db.commit()

        doc_hosp2_id, hosp1_id = doc_hosp2.id, hosp1.id

    class FakeAdminHosp1:
        id = 9005
        role_id = 1
        hospital_id = hosp1_id  # Belongs to Hospital 1
        is_active = True
        is_verified = True
        email = f"admin_hosp1_{uid}@test.com"

        class role:
            name = "hospital_admin"

    fake_admin = FakeAdminHosp1()
    app.dependency_overrides[get_current_active_user] = lambda: fake_admin
    app.dependency_overrides[get_current_user] = lambda: fake_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with patch("app.core.dependencies.require_permission") as mock_perm:
            mock_perm.return_value = lambda: fake_admin
            with patch(
                "app.repositories.rbac_repository.RBACRepository.get_user_permissions",
                new=AsyncMock(return_value=["patients:read"]),
            ):
                # Admin from Hospital 1 tries to filter by Doctor from Hospital 2
                resp = await ac.get(f"/api/v1/patients?doctor_id={doc_hosp2_id}")
                # Must return 404 because doctor does not exist in Hospital 1
                assert resp.status_code == 404, resp.text
                assert "Doctor not found" in resp.text

    app.dependency_overrides.clear()

