import uuid
import pytest
from datetime import date
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock

from app.main import app
from app.models.hospital_model import Hospital
from app.models.doctor_model import Doctor
from app.models.patient_model import Patient
from app.models.user_model import User
from app.models.pharmacy_model import Prescription
from app.core.database import AsyncSessionLocal, engine
from app.core.dependencies import get_current_active_user, get_current_user
from app.utils.helpers import utc_now


@pytest.fixture(autouse=True)
async def cleanup_engine():
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_pharmacy_prescriptions_doctor_filtering_and_omitted():
    """Verify that doctor_id filter returns respective prescriptions and omitting it returns all."""
    uid = uuid.uuid4().hex[:8]

    async with AsyncSessionLocal() as db:
        hosp = Hospital(
            name=f"Pharm Hosp {uid}",
            email=f"pharm_hosp_{uid}@test.com",
            phone="+919999888801",
            address="100 Pharmacy Way",
        )
        db.add(hosp)
        await db.flush()

        doc1 = Doctor(
            hospital_id=hosp.id,
            doctor_code=f"DOC_PH1_{uid}",
            first_name="Alice",
            last_name="Doctor",
            specialization="General",
            license_number=f"LIC_PH1_{uid}",
        )
        doc2 = Doctor(
            hospital_id=hosp.id,
            doctor_code=f"DOC_PH2_{uid}",
            first_name="Bob",
            last_name="Doctor",
            specialization="Pediatrics",
            license_number=f"LIC_PH2_{uid}",
        )
        p = Patient(
            hospital_id=hosp.id,
            patient_code=f"PAT_PH_{uid}",
            first_name="John",
            last_name="Doe",
            gender="Male",
            status="active",
            created_at=utc_now(),
        )
        db.add_all([doc1, doc2, p])
        await db.flush()

        # Prescription for Doc 1
        rx1 = Prescription(
            hospital_id=hosp.id,
            doctor_id=doc1.id,
            patient_id=p.id,
            prescription_number=f"RX1_{uid}",
            status="pending",
            start_date=date.today(),
            created_at=utc_now(),
        )
        # Prescription for Doc 2
        rx2 = Prescription(
            hospital_id=hosp.id,
            doctor_id=doc2.id,
            patient_id=p.id,
            prescription_number=f"RX2_{uid}",
            status="approved",
            start_date=date.today(),
            created_at=utc_now(),
        )
        db.add_all([rx1, rx2])
        await db.commit()

        doc1_id, doc2_id, hosp_id = doc1.id, doc2.id, hosp.id

    class FakeAdmin:
        id = 9101
        role_id = 1
        hospital_id = hosp_id
        is_active = True
        is_verified = True
        email = f"admin_pharm_{uid}@test.com"

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
                new=AsyncMock(return_value=["pharmacy:read"]),
            ):
                # 1. Filter by Doctor 1
                resp1 = await ac.get(f"/api/v1/pharmacy/prescriptions?doctor_id={doc1_id}")
                assert resp1.status_code == 200, resp1.text
                d1 = resp1.json()["data"]
                assert d1["total"] == 1
                assert d1["items"][0]["prescription_number"] == f"RX1_{uid}"
                assert d1["items"][0]["doctor_id"] == doc1_id
                assert d1["pending"] == 1
                assert d1["approved"] == 0

                # 2. Filter by Doctor 2
                resp2 = await ac.get(f"/api/v1/pharmacy/prescriptions?doctor_id={doc2_id}")
                assert resp2.status_code == 200, resp2.text
                d2 = resp2.json()["data"]
                assert d2["total"] == 1
                assert d2["items"][0]["prescription_number"] == f"RX2_{uid}"
                assert d2["items"][0]["doctor_id"] == doc2_id
                assert d2["pending"] == 0
                assert d2["approved"] == 1

                # 3. Omitted doctor_id preserves all prescriptions
                resp_all = await ac.get("/api/v1/pharmacy/prescriptions")
                assert resp_all.status_code == 200, resp_all.text
                d_all = resp_all.json()["data"]
                rx_nums = [item["prescription_number"] for item in d_all["items"]]
                assert f"RX1_{uid}" in rx_nums
                assert f"RX2_{uid}" in rx_nums
                assert d_all["total"] >= 2

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_pharmacy_prescriptions_invalid_id_and_validation():
    """Verify that non-existent doctor_id returns 404 and doctor_id=0 returns 422."""
    class FakeAdmin:
        id = 9102
        role_id = 1
        hospital_id = 1
        is_active = True
        is_verified = True
        email = "admin_pharm_err@test.com"

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
                new=AsyncMock(return_value=["pharmacy:read"]),
            ):
                # 1. Non-existent doctor_id -> 404 Not Found
                resp_404 = await ac.get("/api/v1/pharmacy/prescriptions?doctor_id=99999999")
                assert resp_404.status_code == 404, resp_404.text
                assert "Doctor not found" in resp_404.text

                # 2. doctor_id = 0 (violates ge=1) -> 422 Unprocessable Entity
                resp_422 = await ac.get("/api/v1/pharmacy/prescriptions?doctor_id=0")
                assert resp_422.status_code == 422, resp_422.text

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_pharmacy_prescriptions_tenant_isolation():
    """Verify that a user in Hospital 1 cannot query doctor_id belonging to Hospital 2."""
    uid = uuid.uuid4().hex[:8]

    async with AsyncSessionLocal() as db:
        hosp1 = Hospital(
            name=f"Hosp1 Pharm {uid}",
            email=f"hosp1_pharm_{uid}@test.com",
            phone="+919999888802",
            address="Hosp 1 Address",
        )
        hosp2 = Hospital(
            name=f"Hosp2 Pharm {uid}",
            email=f"hosp2_pharm_{uid}@test.com",
            phone="+919999888803",
            address="Hosp 2 Address",
        )
        db.add_all([hosp1, hosp2])
        await db.flush()

        doc_hosp2 = Doctor(
            hospital_id=hosp2.id,
            doctor_code=f"DOC_H2_{uid}",
            first_name="Hosp2Doc",
            last_name="Smith",
            specialization="Surgery",
            license_number=f"LIC_H2_{uid}",
        )
        db.add(doc_hosp2)
        await db.commit()

        doc_hosp2_id, hosp1_id = doc_hosp2.id, hosp1.id

    class FakeAdminHosp1:
        id = 9103
        role_id = 1
        hospital_id = hosp1_id
        is_active = True
        is_verified = True
        email = f"admin_iso_{uid}@test.com"

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
                new=AsyncMock(return_value=["pharmacy:read"]),
            ):
                # Admin from Hospital 1 tries to filter by Doctor from Hospital 2
                resp = await ac.get(f"/api/v1/pharmacy/prescriptions?doctor_id={doc_hosp2_id}")
                assert resp.status_code == 404, resp.text
                assert "Doctor not found" in resp.text

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_pharmacy_prescriptions_doctor_user_override_restricted():
    """Verify that doctor users are restricted to their own doctor ID and cannot override it."""
    uid = uuid.uuid4().hex[:8]

    async with AsyncSessionLocal() as db:
        hosp = Hospital(
            name=f"Hosp DocRole {uid}",
            email=f"hosp_docrole_{uid}@test.com",
            phone="+919999888804",
            address="Hosp DocRole Address",
        )
        db.add(hosp)
        await db.flush()

        user_doc1 = User(
            user_code=f"USR_D1_{uid}",
            full_name="Doctor One",
            email=f"doc1_{uid}@test.com",
            hashed_password="fakehashedpassword",
            role_id=2,
            hospital_id=hosp.id,
            is_active=True,
            is_verified=True,
            created_at=utc_now(),
        )
        db.add(user_doc1)
        await db.flush()

        doc1 = Doctor(
            hospital_id=hosp.id,
            user_id=user_doc1.id,
            doctor_code=f"DOC1_ROLE_{uid}",
            first_name="Doctor",
            last_name="One",
            specialization="Cardiology",
            license_number=f"LIC1_ROLE_{uid}",
        )
        doc2 = Doctor(
            hospital_id=hosp.id,
            doctor_code=f"DOC2_ROLE_{uid}",
            first_name="Doctor",
            last_name="Two",
            specialization="Neurology",
            license_number=f"LIC2_ROLE_{uid}",
        )
        p = Patient(
            hospital_id=hosp.id,
            patient_code=f"PAT_ROLE_{uid}",
            first_name="Patient",
            last_name="Role",
            gender="Female",
            status="active",
            created_at=utc_now(),
        )
        db.add_all([doc1, doc2, p])
        await db.flush()

        rx1 = Prescription(
            hospital_id=hosp.id,
            doctor_id=doc1.id,
            patient_id=p.id,
            prescription_number=f"RX_DOC1_{uid}",
            status="pending",
            start_date=date.today(),
            created_at=utc_now(),
        )
        rx2 = Prescription(
            hospital_id=hosp.id,
            doctor_id=doc2.id,
            patient_id=p.id,
            prescription_number=f"RX_DOC2_{uid}",
            status="completed",
            start_date=date.today(),
            created_at=utc_now(),
        )
        db.add_all([rx1, rx2])
        await db.commit()

        user_doc1_id, doc1_id, doc2_id, hosp_id = user_doc1.id, doc1.id, doc2.id, hosp.id

    class FakeDoctorUser:
        id = user_doc1_id
        role_id = 2
        hospital_id = hosp_id
        is_active = True
        is_verified = True
        email = f"doc1_{uid}@test.com"

        class role:
            name = "Doctor"

    fake_doctor = FakeDoctorUser()
    app.dependency_overrides[get_current_active_user] = lambda: fake_doctor
    app.dependency_overrides[get_current_user] = lambda: fake_doctor

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with patch("app.core.dependencies.require_permission") as mock_perm:
            mock_perm.return_value = lambda: fake_doctor
            with patch(
                "app.repositories.rbac_repository.RBACRepository.get_user_permissions",
                new=AsyncMock(return_value=["pharmacy:read"]),
            ):
                # Doctor 1 attempts to pass ?doctor_id=doc2_id to access Doctor 2's prescriptions
                resp = await ac.get(f"/api/v1/pharmacy/prescriptions?doctor_id={doc2_id}")
                assert resp.status_code == 200, resp.text
                data = resp.json()["data"]

                # Response must ONLY contain Doctor 1's prescriptions
                items = data["items"]
                assert len(items) == 1
                assert items[0]["doctor_id"] == doc1_id
                assert items[0]["prescription_number"] == f"RX_DOC1_{uid}"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_pharmacy_prescriptions_pagination_and_filtered_counts():
    """Verify that doctor_id properly paginates and filters summary counts."""
    uid = uuid.uuid4().hex[:8]

    async with AsyncSessionLocal() as db:
        hosp = Hospital(
            name=f"Hosp Counts {uid}",
            email=f"hosp_cnt_{uid}@test.com",
            phone="+919999888805",
            address="Hosp Counts Address",
        )
        db.add(hosp)
        await db.flush()

        doc = Doctor(
            hospital_id=hosp.id,
            doctor_code=f"DOC_CNT_{uid}",
            first_name="Count",
            last_name="Doctor",
            specialization="General",
            license_number=f"LIC_CNT_{uid}",
        )
        p = Patient(
            hospital_id=hosp.id,
            patient_code=f"PAT_CNT_{uid}",
            first_name="Count",
            last_name="Patient",
            gender="Male",
            status="active",
            created_at=utc_now(),
        )
        db.add_all([doc, p])
        await db.flush()

        # Create 5 prescriptions for doc: 3 pending, 2 approved
        rxs = []
        for i in range(5):
            st = "pending" if i < 3 else "approved"
            rx = Prescription(
                hospital_id=hosp.id,
                doctor_id=doc.id,
                patient_id=p.id,
                prescription_number=f"RX_CNT_{uid}_{i}",
                status=st,
                start_date=date.today(),
                created_at=utc_now(),
            )
            rxs.append(rx)
        db.add_all(rxs)
        await db.commit()

        doc_id, hosp_id = doc.id, hosp.id

    class FakeAdmin:
        id = 9105
        role_id = 1
        hospital_id = hosp_id
        is_active = True
        is_verified = True
        email = f"admin_cnt_{uid}@test.com"

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
                new=AsyncMock(return_value=["pharmacy:read"]),
            ):
                # Page 1, size 2
                resp = await ac.get(f"/api/v1/pharmacy/prescriptions?doctor_id={doc_id}&page=1&size=2")
                assert resp.status_code == 200, resp.text
                d = resp.json()["data"]

                assert len(d["items"]) == 2
                assert d["total"] == 5
                assert d["pages"] == 3
                assert d["page"] == 1
                assert d["total_prescriptions"] == 5
                assert d["pending"] == 3
                assert d["approved"] == 2

    app.dependency_overrides.clear()

