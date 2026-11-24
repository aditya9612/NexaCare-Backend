import pytest
import uuid
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import AsyncSessionLocal
from app.schemas.staff_schema import StaffCreate, StaffUpdate, StaffResponse
from app.services.staff_service import StaffService
from app.models.user_model import User
from app.models.nurse_model import Nurse
from app.models.staff_model import Staff
from app.models.role_model import Role


# ---------------------------------------------------------------------------
# Unit Tests: Pydantic Schema Validation & Aliases
# ---------------------------------------------------------------------------

def test_nurse_create_with_snake_case_license_number():
    """Requirement 1: Create Nurse using license_number."""
    data = StaffCreate.model_validate({
        "full_name": "Test Nurse One",
        "email": "nurse1@test.com",
        "password": "Password123!",
        "staff_code": "NUR-UNIT-001",
        "department_id": 1,
        "role_name": "Nurse",
        "license_number": "LIC-SNAKE-123",
        "shift": "Morning",
    })
    assert data.license_number == "LIC-SNAKE-123"
    assert data.shift == "Morning"
    assert data.role_name == "Nurse"


def test_nurse_create_with_camel_case_license_number():
    """Requirement 2: Create Nurse using licenseNumber (camelCase)."""
    data = StaffCreate.model_validate({
        "full_name": "Test Nurse Two",
        "email": "nurse2@test.com",
        "password": "Password123!",
        "staff_code": "NUR-UNIT-002",
        "department_id": 1,
        "role_name": "Nurse",
        "licenseNumber": "LIC-CAMEL-456",
        "nurseShift": "Night",
    })
    assert data.license_number == "LIC-CAMEL-456"
    assert data.shift == "Night"


def test_nurse_create_with_alternate_aliases():
    """Verify license_no and licenseNo aliases work."""
    data1 = StaffCreate.model_validate({
        "full_name": "Test Nurse Three",
        "email": "nurse3@test.com",
        "password": "Password123!",
        "staff_code": "NUR-UNIT-003",
        "department_id": 1,
        "role_name": "Nurse",
        "license_no": "LIC-ALT-789",
    })
    assert data1.license_number == "LIC-ALT-789"

    data2 = StaffCreate.model_validate({
        "full_name": "Test Nurse Four",
        "email": "nurse4@test.com",
        "password": "Password123!",
        "staff_code": "NUR-UNIT-004",
        "department_id": 1,
        "role_name": "Nurse",
        "licenseNo": "LIC-ALT-000",
    })
    assert data2.license_number == "LIC-ALT-000"


def test_nurse_create_without_license_number_fails():
    """Requirement 3: Create Nurse without license number – must fail validation."""
    with pytest.raises(ValidationError) as exc_info:
        StaffCreate.model_validate({
            "full_name": "Test Nurse Fail",
            "email": "nurse_fail@test.com",
            "password": "Password123!",
            "staff_code": "NUR-FAIL-001",
            "department_id": 1,
            "role_name": "Nurse",
        })
    errors = exc_info.value.errors()
    assert any("license_number is required when role_name is 'Nurse'" in e["msg"] for e in errors)


def test_nurse_create_with_whitespace_license_number_fails():
    """Requirement 4: Create Nurse with whitespace-only license number – must fail."""
    with pytest.raises(ValidationError) as exc_info:
        StaffCreate.model_validate({
            "full_name": "Test Nurse Fail",
            "email": "nurse_fail2@test.com",
            "password": "Password123!",
            "staff_code": "NUR-FAIL-002",
            "department_id": 1,
            "role_name": "Nurse",
            "license_number": "     ",
        })
    errors = exc_info.value.errors()
    assert any("license_number cannot be empty or only spaces" in e["msg"] for e in errors)


def test_non_nurse_staff_without_license_number_works():
    """Requirement 5: Create non-Nurse staff without license number – must work as before."""
    data = StaffCreate.model_validate({
        "full_name": "Test Receptionist",
        "email": "receptionist@test.com",
        "password": "Password123!",
        "staff_code": "REC-UNIT-001",
        "department_id": 1,
        "role_name": "Receptionist",
    })
    assert data.license_number is None
    assert data.shift is None
    assert data.role_name == "Receptionist"


def test_staff_update_accepts_aliases():
    """Verify StaffUpdate accepts camelCase licenseNumber and nurseShift."""
    data = StaffUpdate.model_validate({
        "licenseNumber": "LIC-UPD-123",
        "nurseShift": "Evening",
    })
    assert data.license_number == "LIC-UPD-123"
    assert data.shift == "Evening"


# ---------------------------------------------------------------------------
# Integration Tests: StaffService End-to-End Workflow with DB
# ---------------------------------------------------------------------------

@pytest.fixture
def admin_user():
    user = User(id=1, email="chetan.kumar@gmail.com", hospital_id=6)
    user.role = Role(name="hospital_admin")
    return user


@pytest.mark.asyncio
async def test_staff_service_nurse_crud_workflow(admin_user):
    """
    Requirements 6, 7, 8, 9:
    - POST response includes license_number and shift.
    - Saved in existing nurses table.
    - GET /api/v1/staff/{staff_id} includes license_number and shift.
    - GET /api/v1/staff list includes Nurse details.
    - PATCH response includes updated Nurse details.
    """
    import random
    unique_num = random.randint(10000, 99999)
    unique_suffix = uuid.uuid4().hex[:6].upper()
    nurse_email = f"nurse_{unique_num}@test.com"
    staff_code = f"NUR-{unique_suffix}"
    initial_license = f"LIC-NURSE-{unique_suffix}"
    updated_license = f"LIC-NURSE-UPD-{unique_suffix}"

    async with AsyncSessionLocal() as session:
        service = StaffService(session)

        # 1. Create Nurse using camelCase licenseNumber (Requirement 2 & 6)
        create_payload = StaffCreate.model_validate({
            "hospital_id": 6,
            "full_name": "Nurse Automata Patil",
            "email": nurse_email,
            "phone": f"98765{unique_num}",
            "password": "NursePassword@123",
            "staff_code": staff_code,
            "department_id": 1,
            "role_name": "Nurse",
            "licenseNumber": initial_license,
            "nurseShift": "Morning",
        })

        created_staff = await service.create_staff(create_payload, current_user_id=admin_user.id, current_user=admin_user)
        staff_id = created_staff.id

        # Verify POST response (Requirement 6)
        assert created_staff.role_name == "Nurse"
        assert created_staff.license_number == initial_license
        assert created_staff.shift == "Morning"

        # Verify record in nurses table
        nurse_record = (await session.execute(
            select(Nurse).where(Nurse.license_number == initial_license)
        )).scalar_one_or_none()
        assert nurse_record is not None
        assert nurse_record.license_number == initial_license
        assert nurse_record.shift == "Morning"
        assert nurse_record.hospital_id == 6

        # 2. Verify GET by ID (Requirement 7)
        fetched_staff = await service.get_staff_by_id(staff_id, current_user=admin_user)
        assert fetched_staff.id == staff_id
        assert fetched_staff.role_name == "Nurse"
        assert fetched_staff.license_number == initial_license
        assert fetched_staff.shift == "Morning"

        # 3. Verify GET list includes Nurse details (Requirement 8)
        list_res = await service.list_staff(page=1, size=50, role_name="Nurse", current_user=admin_user)
        items = list_res["items"]
        found = next((item for item in items if item.id == staff_id), None)
        assert found is not None
        assert found.license_number == initial_license
        assert found.shift == "Morning"

        # 4. Verify PATCH updates Nurse details and response (Requirement 9)
        patch_payload = StaffUpdate.model_validate({
            "licenseNumber": updated_license,
            "nurseShift": "Evening",
        })
        updated_staff = await service.update_staff(staff_id, patch_payload, current_user_id=admin_user.id, current_user=admin_user)
        assert updated_staff.id == staff_id
        assert updated_staff.license_number == updated_license
        assert updated_staff.shift == "Evening"

        # Verify updated in nurses table
        nurse_record_updated = (await session.execute(
            select(Nurse).where(Nurse.id == nurse_record.id)
        )).scalar_one_or_none()
        assert nurse_record_updated.license_number == updated_license
        assert nurse_record_updated.shift == "Evening"

        # Cleanup created records cleanly
        await session.delete(nurse_record_updated)
        staff_to_del = await session.get(Staff, staff_id)
        if staff_to_del:
            await session.delete(staff_to_del)
        user_to_del = (await session.execute(
            select(User).where(func.lower(User.email) == nurse_email.lower())
        )).scalar_one_or_none()
        if user_to_del:
            await session.delete(user_to_del)
        await session.commit()


@pytest.mark.asyncio
async def test_staff_service_non_nurse_staff_crud(admin_user):
    """
    Requirement 5:
    Create non-Nurse staff (Receptionist) without license_number.
    Verify response returns license_number = None and shift = None without error.
    """
    import random
    unique_num = random.randint(10000, 99999)
    unique_suffix = uuid.uuid4().hex[:6].upper()
    rec_email = f"rec_{unique_num}@test.com"
    staff_code = f"REC-{unique_suffix}"

    async with AsyncSessionLocal() as session:
        service = StaffService(session)

        create_payload = StaffCreate.model_validate({
            "hospital_id": 6,
            "full_name": "Receptionist Automata Joshi",
            "email": rec_email,
            "phone": f"98765{unique_num}",
            "password": "RecPassword@123",
            "staff_code": staff_code,
            "department_id": 1,
            "role_name": "Receptionist",
        })

        created_staff = await service.create_staff(create_payload, current_user_id=admin_user.id, current_user=admin_user)
        assert created_staff.role_name == "Receptionist"
        assert created_staff.license_number is None
        assert created_staff.shift is None

        # Fetch by ID
        fetched_staff = await service.get_staff_by_id(created_staff.id, current_user=admin_user)
        assert fetched_staff.role_name == "Receptionist"
        assert fetched_staff.license_number is None
        assert fetched_staff.shift is None

        # Cleanup
        staff_to_del = await session.get(Staff, created_staff.id)
        if staff_to_del:
            await session.delete(staff_to_del)
        user_to_del = (await session.execute(
            select(User).where(func.lower(User.email) == rec_email.lower())
        )).scalar_one_or_none()
        if user_to_del:
            await session.delete(user_to_del)
        await session.commit()



# ---------------------------------------------------------------------------
# HTTP Route Integration Tests (Testing via FastAPI Router)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_http_create_nurse_camel_case_and_get():
    """
    Test creating Nurse via POST /api/v1/staff using camelCase licenseNumber
    and retrieving via GET /api/v1/staff/{id}.
    """
    import httpx
    import random
    from app.main import app
    from app.core.database import get_db
    from app.core.dependencies import get_current_user

    async with AsyncSessionLocal() as session:
        admin_user = User(id=1, email="chetan.kumar@gmail.com", hospital_id=6, is_active=True, is_verified=True)
        admin_user.role = Role(name="hospital_admin")

        async def override_get_db():
            yield session

        async def override_get_current_user():
            return admin_user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user

        unique_num = random.randint(10000, 99999)
        nurse_email = f"http_nurse_{unique_num}@test.com"
        staff_code = f"NUR-HTTP-{unique_num}"
        initial_license = f"LIC-HTTP-{unique_num}"

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. POST /api/v1/staff with camelCase licenseNumber
            payload = {
                "hospital_id": 6,
                "full_name": "HTTP Nurse Patil",
                "email": nurse_email,
                "phone": f"98765{unique_num}",
                "password": "NursePassword@123",
                "staff_code": staff_code,
                "department_id": 1,
                "role_name": "Nurse",
                "licenseNumber": initial_license,
                "nurseShift": "Night",
            }
            res = await client.post("/api/v1/staff", json=payload)
            assert res.status_code == 201, f"Failed: {res.text}"
            res_json = res.json()
            assert res_json["success"] is True
            data = res_json["data"]
            assert data["role_name"] == "Nurse"
            assert data["license_number"] == initial_license
            assert data["shift"] == "Night"
            created_staff_id = data["id"]

            # 2. GET /api/v1/staff/{staff_id}
            get_res = await client.get(f"/api/v1/staff/{created_staff_id}")
            assert get_res.status_code == 200
            get_data = get_res.json()["data"]
            assert get_data["id"] == created_staff_id
            assert get_data["license_number"] == initial_license
            assert get_data["shift"] == "Night"

            # 3. GET /api/v1/staff list
            list_res = await client.get("/api/v1/staff?role_name=Nurse")
            assert list_res.status_code == 200
            items = list_res.json()["data"]["items"]
            matching = next((it for it in items if it["id"] == created_staff_id), None)
            assert matching is not None
            assert matching["license_number"] == initial_license
            assert matching["shift"] == "Night"

            # 4. PATCH /api/v1/staff/{staff_id} with updated licenseNumber
            updated_license = f"LIC-HTTP-UPD-{unique_num}"
            patch_res = await client.patch(
                f"/api/v1/staff/{created_staff_id}",
                json={"licenseNumber": updated_license, "nurseShift": "Morning"},
            )
            assert patch_res.status_code == 200
            patch_data = patch_res.json()["data"]
            assert patch_data["license_number"] == updated_license
            assert patch_data["shift"] == "Morning"

            # 5. POST /api/v1/staff without licenseNumber - must fail validation
            fail_payload = {
                "hospital_id": 6,
                "full_name": "HTTP Nurse Missing",
                "email": f"missing_{unique_num}@test.com",
                "phone": f"98766{unique_num}",
                "password": "NursePassword@123",
                "staff_code": f"NUR-FAIL-{unique_num}",
                "department_id": 1,
                "role_name": "Nurse",
            }
            fail_res = await client.post("/api/v1/staff", json=fail_payload)
            assert fail_res.status_code in (400, 422)
            assert "license_number is required when role_name is 'Nurse'" in fail_res.text

            # Cleanup
            nurse_rec = (await session.execute(
                select(Nurse).where(Nurse.license_number == updated_license)
            )).scalar_one_or_none()
            if nurse_rec:
                await session.delete(nurse_rec)
            staff_to_del = await session.get(Staff, created_staff_id)
            if staff_to_del:
                await session.delete(staff_to_del)
            user_to_del = (await session.execute(
                select(User).where(func.lower(User.email) == nurse_email.lower())
            )).scalar_one_or_none()
            if user_to_del:
                await session.delete(user_to_del)
            await session.commit()

        app.dependency_overrides.clear()
