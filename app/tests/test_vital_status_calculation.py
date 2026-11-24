import pytest
from datetime import datetime
from app.schemas.nurse_schema import calculate_vital_status, PatientVitalResponse
from app.schemas.inventory_schema import InventoryItemResponse


# ---------------------------------------------------------------------------
# Priority 2: 14 Required Blood Pressure Regression Test Cases
# ---------------------------------------------------------------------------
BP_TEST_CASES = [
    # 1. Standard valid BP (Normal: sys 90-120, dia 60-80)
    ("120/80", "Normal", "Standard valid BP"),
    # 2. High systolic BP
    ("140/80", "Abnormal", "High systolic BP (>120)"),
    # 3. High diastolic BP
    ("115/95", "Abnormal", "High diastolic BP (>80)"),
    # 4. Low systolic BP
    ("85/70", "Abnormal", "Low systolic BP (<90)"),
    # 5. Low diastolic BP
    ("115/50", "Abnormal", "Low diastolic BP (<60)"),
    # 6. Missing systolic
    ("/80", "Abnormal", "Missing systolic component"),
    # 7. Missing diastolic
    ("120/", "Abnormal", "Missing diastolic component"),
    # 8. Multiple slash separators
    ("120/80/90", "Abnormal", "Multiple slash separators"),
    # 9. Non-numeric values
    ("abc/xyz", "Abnormal", "Non-numeric systolic and diastolic"),
    # 10. Empty string
    ("", "Abnormal", "Empty string"),
    # 11. Whitespace-only value
    ("   ", "Abnormal", "Whitespace-only value"),
    # 12. No separator
    ("12080", "Abnormal", "No slash separator"),
    # 13. Normal boundary values (sys 90, dia 60; sys 120, dia 80)
    ("90/60", "Normal", "Normal lower boundary"),
    ("120/60", "Normal", "Normal boundary sys 120, dia 60"),
    ("90/80", "Normal", "Normal boundary sys 90, dia 80"),
    # 14. Invalid malformed BP (partial alpha, double slash)
    ("12a/80", "Abnormal", "Alphanumeric in systolic"),
    ("120/8b", "Abnormal", "Alphanumeric in diastolic"),
    ("//", "Abnormal", "Double slash with no values"),
    ("120//80", "Abnormal", "Double slash with values"),
    # 15. Additional BP Numeric Format Cases
    ("090/060", "Normal", "Leading zeros (Normal)"),
    ("90.0/60", "Normal", "Float systolic with .0 (Normal)"),
    ("90/60.0", "Normal", "Float diastolic with .0 (Normal)"),
    ("+90/60", "Normal", "Explicit positive sign systolic (Normal)"),
    ("90/+60", "Normal", "Explicit positive sign diastolic (Normal)"),
    ("90.5/60", "Normal", "Fractional systolic (Normal)"),
    ("90/60.5", "Normal", "Fractional diastolic (Normal)"),
    ("-90/60", "Abnormal", "Negative systolic (<90)"),
    ("90/-60", "Abnormal", "Negative diastolic (<60)"),
    ("1e2/60", "Normal", "Scientific notation systolic 1e2=100 (Normal)"),
    ("90/6e1", "Normal", "Scientific notation diastolic 6e1=60 (Normal)"),
    ("abc/80", "Abnormal", "Non-numeric systolic"),
    ("90/abc", "Abnormal", "Non-numeric diastolic"),
    # 16. Critical NULL / Missing BP Case
    (None, "Normal", "SQL NULL / None BP"),
]


@pytest.mark.parametrize("bp,expected_status,case_name", BP_TEST_CASES)
def test_python_vital_status_bp_cases(bp, expected_status, case_name):
    """
    Verify Python calculate_vital_status classifies all required BP cases correctly.
    Baseline vitals (temp=36.6, pulse=75, spo2=98.0) are kept in normal ranges.
    """
    status = calculate_vital_status(
        temperature=36.6,
        blood_pressure=bp,
        pulse_rate=75,
        oxygen_saturation=98.0,
    )
    assert status == expected_status, f"Failed for {case_name} ({bp}): expected {expected_status}, got {status}"


def test_calculate_vital_status_temperature_boundaries():
    """Verify temperature boundary and abnormal conditions."""
    # Normal range: 36.5 - 37.5
    assert calculate_vital_status(temperature=36.5, blood_pressure="120/80", pulse_rate=75, oxygen_saturation=98.0) == "Normal"
    assert calculate_vital_status(temperature=37.5, blood_pressure="120/80", pulse_rate=75, oxygen_saturation=98.0) == "Normal"
    assert calculate_vital_status(temperature=36.4, blood_pressure="120/80", pulse_rate=75, oxygen_saturation=98.0) == "Abnormal"
    assert calculate_vital_status(temperature=37.6, blood_pressure="120/80", pulse_rate=75, oxygen_saturation=98.0) == "Abnormal"


def test_calculate_vital_status_pulse_boundaries():
    """Verify pulse rate boundary and abnormal conditions."""
    # Normal range: 60 - 100
    assert calculate_vital_status(temperature=36.6, blood_pressure="120/80", pulse_rate=60, oxygen_saturation=98.0) == "Normal"
    assert calculate_vital_status(temperature=36.6, blood_pressure="120/80", pulse_rate=100, oxygen_saturation=98.0) == "Normal"
    assert calculate_vital_status(temperature=36.6, blood_pressure="120/80", pulse_rate=59, oxygen_saturation=98.0) == "Abnormal"
    assert calculate_vital_status(temperature=36.6, blood_pressure="120/80", pulse_rate=101, oxygen_saturation=98.0) == "Abnormal"


def test_calculate_vital_status_spo2_boundaries():
    """Verify oxygen saturation boundary and abnormal conditions."""
    # Normal range: 95.0 - 100.0
    assert calculate_vital_status(temperature=36.6, blood_pressure="120/80", pulse_rate=75, oxygen_saturation=95.0) == "Normal"
    assert calculate_vital_status(temperature=36.6, blood_pressure="120/80", pulse_rate=75, oxygen_saturation=100.0) == "Normal"
    assert calculate_vital_status(temperature=36.6, blood_pressure="120/80", pulse_rate=75, oxygen_saturation=94.9) == "Abnormal"
    assert calculate_vital_status(temperature=36.6, blood_pressure="120/80", pulse_rate=75, oxygen_saturation=101.0) == "Abnormal"


def test_sql_repository_bp_consistency_sqlite():
    """
    Test SQL filtering in NursePatientVitalRepository._apply_filters against in-memory SQLite.
    Asserts 100% agreement between Python calculate_vital_status and SQL repository queries:
    - Normal query returns exactly all Normal records.
    - Abnormal query returns exactly all Abnormal records.
    - Zero overlap, complete coverage (no unclassified or misclassified records).
    """
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from app.models.nurse_model import PatientVital, Nurse
    from app.models.user_model import User
    from app.repositories.nurse_repository import NursePatientVitalRepository

    engine = create_engine("sqlite:///:memory:")
    # Allow NULL blood_pressure in SQLite test table to test SQL NULL classification
    PatientVital.__table__.columns["blood_pressure"].nullable = True
    User.__table__.create(engine)
    Nurse.__table__.create(engine)
    PatientVital.__table__.create(engine)

    with Session(engine) as session:
        for idx, (bp, expected, desc) in enumerate(BP_TEST_CASES, start=1):
            vital = PatientVital(
                id=idx,
                nurse_id=1,
                patient_id=1,
                temperature=36.6,
                blood_pressure=bp,
                pulse_rate=75,
                oxygen_saturation=98.0,
                recorded_at=datetime.utcnow(),
                notes=f"Test note {desc}",
            )
            session.add(vital)
        session.commit()

        repo = NursePatientVitalRepository(session)

        # 1. Query with status="normal"
        q_normal = repo._apply_filters(select(PatientVital), patient_id=1, status="normal")
        normal_records = session.scalars(q_normal).all()
        normal_ids = {r.id for r in normal_records}

        # 2. Query with status="abnormal"
        q_abnormal = repo._apply_filters(select(PatientVital), patient_id=1, status="abnormal")
        abnormal_records = session.scalars(q_abnormal).all()
        abnormal_ids = {r.id for r in abnormal_records}

        # Verify completeness and mutual exclusivity
        total_cases = len(BP_TEST_CASES)
        assert len(normal_ids) + len(abnormal_ids) == total_cases, (
            f"Every vital record must be either normal or abnormal. "
            f"Got {len(normal_ids)} normal + {len(abnormal_ids)} abnormal != {total_cases}"
        )
        assert len(normal_ids.intersection(abnormal_ids)) == 0, "No record should be classified as both normal and abnormal"

        # Verify 1-to-1 agreement with Python calculate_vital_status for every single case
        for idx, (bp, expected_status, desc) in enumerate(BP_TEST_CASES, start=1):
            py_status = calculate_vital_status(
                temperature=36.6,
                blood_pressure=bp,
                pulse_rate=75,
                oxygen_saturation=98.0,
            )
            assert py_status == expected_status, f"Python status mismatch for {desc} ({bp})"

            if expected_status == "Normal":
                assert idx in normal_ids, f"SQL failed to classify normal for {desc} ({bp})"
                assert idx not in abnormal_ids, f"SQL falsely classified abnormal for {desc} ({bp})"
            else:
                assert idx in abnormal_ids, f"SQL failed to classify abnormal for {desc} ({bp})"
                assert idx not in normal_ids, f"SQL falsely classified normal for {desc} ({bp})"

        # 3. Explicit NULL verification: NULL BP with abnormal temperature (e.g. fever 39.0)
        vital_null_fever = PatientVital(
            id=total_cases + 1,
            nurse_id=1,
            patient_id=1,
            temperature=39.0,
            blood_pressure=None,
            pulse_rate=75,
            oxygen_saturation=98.0,
            recorded_at=datetime.utcnow(),
            notes="NULL BP with high fever",
        )
        session.add(vital_null_fever)
        session.commit()

        q_norm_fever = repo._apply_filters(select(PatientVital), patient_id=1, status="normal")
        norm_fever_ids = {r.id for r in session.scalars(q_norm_fever).all()}
        q_abnorm_fever = repo._apply_filters(select(PatientVital), patient_id=1, status="abnormal")
        abnorm_fever_ids = {r.id for r in session.scalars(q_abnorm_fever).all()}

        assert (total_cases + 1) in abnorm_fever_ids
        assert (total_cases + 1) not in norm_fever_ids
        assert calculate_vital_status(temperature=39.0, blood_pressure=None, pulse_rate=75, oxygen_saturation=98.0) == "Abnormal"

        # 4. Test text search for "normal" and "abnormal"
        q_search_normal = repo._apply_filters(select(PatientVital), patient_id=1, search="normal")
        search_normal_records = session.scalars(q_search_normal).all()
        assert len(search_normal_records) >= len(normal_ids)

        q_search_abnormal = repo._apply_filters(select(PatientVital), patient_id=1, search="abnormal")
        search_abnormal_records = session.scalars(q_search_abnormal).all()
        assert len(search_abnormal_records) >= len(abnormal_ids)


def test_patient_vital_response_validator():
    data = {
        "id": 1,
        "nurse_id": 10,
        "patient_id": 20,
        "temperature": 36.6,
        "blood_pressure": "118/78",
        "pulse_rate": 72,
        "respiratory_rate": 16,
        "oxygen_saturation": 99.0,
        "recorded_at": datetime.now(),
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
    resp = PatientVitalResponse.model_validate(data)
    assert resp.status == "Normal"

    # Abnormal vital
    data_abnormal = dict(data, oxygen_saturation=90.0)
    resp_abnormal = PatientVitalResponse.model_validate(data_abnormal)
    assert resp_abnormal.status == "Abnormal"


def test_inventory_item_response_status_validator():
    data_active = {
        "id": 1,
        "name": "Paracetamol 500mg",
        "sku": "MED-001",
        "category": "Pharmacy",
        "quantity": 50,
        "unit": "tabs",
        "unit_cost": 2.5,
        "reorder_level": 10,
        "barcode": None,
        "expiry_date": None,
        "warehouse_id": None,
        "vendor_id": None,
        "department_id": None,
        "is_active": True,
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
    resp_active = InventoryItemResponse.model_validate(data_active)
    assert resp_active.status == "Active"

    data_inactive = dict(data_active, is_active=False)
    resp_inactive = InventoryItemResponse.model_validate(data_inactive)
    assert resp_inactive.status == "Inactive"


def test_medication_logs_response_compatibility():
    """Verify medication logs summary schema and alias synchronization."""
    from app.schemas.nurse_schema import (
        NurseMedicationLogsWithSummaryResponse,
        NurseMedicationLogDetailResponse,
    )

    # 1. Backward-compatible flat array item
    now = datetime.now()
    item_data = {
        "id": 1,
        "prescription_id": 10,
        "nurse_id": 5,
        "time_of_day_slot": "morning",
        "timestamp": now,
        "status": "Administered",
        "medicine_name": "Amoxicillin 500mg",
        "patient_id": 20,
        "patient_name": "John Doe",
        "created_at": now,
    }
    item_resp = NurseMedicationLogDetailResponse.model_validate(item_data)
    assert item_resp.medicine_name == "Amoxicillin 500mg"
    assert item_resp.status == "Administered"

    # 2. Enhanced summary response with aliases
    summary_data = {
        "items": [item_data],
        "total": 1,
        "total_prescriptions": 3,  # alias for total_prescription
        "given_today": 1,
        "pending_due": 2,
        "misses_dose": 0,          # alias for missed_dose
    }
    summary_resp = NurseMedicationLogsWithSummaryResponse.model_validate(summary_data)
    assert summary_resp.total == 1
    assert summary_resp.total_prescription == 3
    assert summary_resp.missed_dose == 0
    assert len(summary_resp.items) == 1
    assert summary_resp.items[0].medicine_name == "Amoxicillin 500mg"


@pytest.mark.asyncio
async def test_vendor_payment_duplicate_and_vendor_validation_mocked():
    """Verify expense service prevents duplicate payments and mismatched vendors using mocked DB (no live MySQL connection)."""
    from unittest.mock import AsyncMock, MagicMock
    from app.core.exceptions import BadRequestException
    from app.models.expense_model import Expense, VendorPayment
    from app.schemas.expense_schema import VendorPaymentCreate
    from app.services.expense_service import ExpenseService

    mock_db = AsyncMock()
    service = ExpenseService(mock_db)

    # Mock repos
    service.vendor_repo = MagicMock()
    service.vendor_repo.get_by_id = AsyncMock(return_value=MagicMock(id=10, is_active=True))
    service.payment_repo = MagicMock()
    service.expense_repo = MagicMock()
    service.audit_repo = MagicMock()
    service.audit_repo.create = AsyncMock()

    mock_user = MagicMock()
    mock_user.hospital_id = 1
    mock_user.role.name = "Hospital Admin"

    # 1. Vendor mismatch test
    exp_vendor1 = Expense(id=1, vendor_id=10, amount=500.0, status="Pending", is_deleted=False)
    service.expense_repo.get_by_id = AsyncMock(return_value=exp_vendor1)

    req_wrong_vendor = VendorPaymentCreate(vendor_id=99, expense_id=1, amount=100.0, payment_method="cash")
    with pytest.raises(BadRequestException, match="The selected expense does not belong to this vendor"):
        await service.create_payment(req_wrong_vendor, user_id=1, current_user=mock_user)

    # 2. Duplicate payment test
    existing_p = VendorPayment(id=101, expense_id=1, vendor_id=10, amount=200.0, payment_method="cash", is_deleted=False)
    service.payment_repo.get_payments_by_expense = AsyncMock(return_value=[existing_p])

    req_duplicate = VendorPaymentCreate(vendor_id=10, expense_id=1, amount=100.0, payment_method="cash")
    with pytest.raises(BadRequestException, match="Payment record already exists for this expense"):
        await service.create_payment(req_duplicate, user_id=1, current_user=mock_user)

    # 3. Already Paid expense test
    exp_paid = Expense(id=2, vendor_id=10, amount=500.0, status="Paid", is_deleted=False)
    service.expense_repo.get_by_id = AsyncMock(return_value=exp_paid)
    service.payment_repo.get_payments_by_expense = AsyncMock(return_value=[])

    req_paid = VendorPaymentCreate(vendor_id=10, expense_id=2, amount=100.0, payment_method="cash")
    with pytest.raises(BadRequestException, match="This expense is already marked as Paid"):
        await service.create_payment(req_paid, user_id=1, current_user=mock_user)


def test_report_branding_template_rendering():
    """Verify Jinja2 template rendering preserves custom hospital branding and excludes hardcoded fallback."""
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader("app/templates"))
    template = env.get_template("report_template.html")

    # Render with custom hospital
    html_custom = template.render(
        hospital_name="Apollo Memorial Hospital",
        hospital_address="742 Evergreen Terrace",
        hospital_phone="555-4321",
        report_number="RPT-001",
        generated_at="2026-11-24 10:00:00",
    )
    assert "Apollo Memorial Hospital" in html_custom
    assert "742 Evergreen Terrace" in html_custom

    # Render without hospital name (platform level / blank)
    html_blank = template.render(
        hospital_name=None,
        report_number="RPT-002",
        generated_at="2026-11-24 10:00:00",
    )
    # Must NOT inject hardcoded "NexaCare Healthcare" into the hospital header div
    assert '<div class="hospital-name">' not in html_blank


@pytest.mark.asyncio
async def test_appointment_export_tenant_isolation_validation():
    """Verify tenant isolation in appointment export and resolution."""
    from unittest.mock import AsyncMock, MagicMock
    from app.core.exceptions import BadRequestException, ForbiddenException
    from app.services.appointment_service import AppointmentService

    mock_db = AsyncMock()
    service = AppointmentService(mock_db)

    # 1. Patient cannot export appointments
    patient_user = MagicMock()
    patient_user.role.name = "Patient"
    patient_user.is_superuser = False
    with pytest.raises(ForbiddenException, match="Patients are not authorized to export appointment records"):
        await service.export_appointments(format_type="excel", current_user=patient_user)

    # 2. Super Admin without X-Hospital-Id must be rejected
    super_admin = MagicMock()
    super_admin.role.name = "Super Admin"
    super_admin.is_superuser = True
    super_admin.hospital_id = None
    super_admin.active_hospital_id = None

    with pytest.raises(BadRequestException, match="X-Hospital-Id header is required for Super Admin"):
        await service._resolve_and_validate_tenant_id(super_admin, x_hospital_id=None)

    # 3. Non-superadmin cannot pass a different X-Hospital-Id
    hospital_admin = MagicMock()
    hospital_admin.role.name = "Hospital Admin"
    hospital_admin.is_superuser = False
    hospital_admin.hospital_id = 1

    with pytest.raises(ForbiddenException, match="Cannot access or specify another hospital's tenant context"):
        await service._resolve_and_validate_tenant_id(hospital_admin, x_hospital_id=2)


@pytest.mark.asyncio
async def test_nurse_tenant_isolation_list_daily_tasks():
    """Verify tenant isolation in list_daily_tasks prevents cross-tenant and unassigned nurse access."""
    from unittest.mock import AsyncMock, MagicMock
    from app.core.constants import UserRole
    from app.core.exceptions import ForbiddenException, NotFoundException
    from app.models.nurse_model import Nurse
    from app.services.nurse_service import NurseService

    mock_db = AsyncMock()
    service = NurseService(mock_db)
    service.repo = MagicMock()
    service.task_repo = MagicMock()
    service.task_repo.list_by_nurse = AsyncMock(return_value=[])
    service.task_repo.count_by_nurse = AsyncMock(return_value=0)

    # 1. Hospital A user accessing Hospital A nurse: allowed
    user_hosp_a = MagicMock()
    user_hosp_a.role.name = "Hospital Admin"
    nurse_hosp_a = Nurse(id=10, hospital_id=1, nurse_code="N-001", license_number="L-001")
    service.repo.get_by_id = AsyncMock(return_value=nurse_hosp_a)

    res = await service.list_daily_tasks(
        current_user=user_hosp_a,
        nurse_id=10,
        hospital_id=1,
    )
    assert res is not None
    service.repo.get_by_id.assert_awaited_with(10, hospital_id=1)
    service.task_repo.list_by_nurse.assert_awaited()

    # 2. Hospital A user accessing Hospital B nurse: rejected (NotFoundException via repo hospital filter)
    service.repo.get_by_id = AsyncMock(return_value=None)
    service.task_repo.list_by_nurse.reset_mock()

    with pytest.raises(NotFoundException, match="Nurse not found"):
        await service.list_daily_tasks(
            current_user=user_hosp_a,
            nurse_id=20,
            hospital_id=1,
        )
    service.repo.get_by_id.assert_awaited_with(20, hospital_id=1)
    service.task_repo.list_by_nurse.assert_not_called()

    # 3. Hospital A user accessing nurse with hospital_id=None: rejected (NotFoundException via repo hospital filter)
    service.repo.get_by_id = AsyncMock(return_value=None)
    service.task_repo.list_by_nurse.reset_mock()

    with pytest.raises(NotFoundException, match="Nurse not found"):
        await service.list_daily_tasks(
            current_user=user_hosp_a,
            nurse_id=30,
            hospital_id=1,
        )
    service.repo.get_by_id.assert_awaited_with(30, hospital_id=1)
    service.task_repo.list_by_nurse.assert_not_called()

    # 4. User with hospital_id=None attempting nurse access: rejected (ForbiddenException fail-closed)
    user_no_hosp = MagicMock()
    user_no_hosp.role.name = "Hospital Admin"
    service.task_repo.list_by_nurse.reset_mock()

    with pytest.raises(ForbiddenException, match="Valid hospital tenant context is required"):
        await service.list_daily_tasks(
            current_user=user_no_hosp,
            nurse_id=10,
            hospital_id=None,
        )
    service.task_repo.list_by_nurse.assert_not_called()

    # 5. Super Admin accessing cross-hospital nurse: allowed
    super_admin = MagicMock()
    super_admin.role.name = UserRole.SUPER_ADMIN
    nurse_hosp_b = Nurse(id=20, hospital_id=2, nurse_code="N-002", license_number="L-002")
    service.repo.get_by_id = AsyncMock(return_value=nurse_hosp_b)

    res_sa = await service.list_daily_tasks(
        current_user=super_admin,
        nurse_id=20,
        hospital_id=None,
    )
    assert res_sa is not None
    service.repo.get_by_id.assert_awaited_with(20, hospital_id=None)
    service.task_repo.list_by_nurse.assert_awaited()

    # 6. Calling Nurse with hospital_id=None: rejected
    nurse_user_orphan = MagicMock()
    nurse_user_orphan.role.name = UserRole.NURSE
    nurse_user_orphan.id = 99
    calling_nurse_orphan = Nurse(id=99, user_id=99, hospital_id=None, nurse_code="N-99", license_number="L-99")
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=calling_nurse_orphan)))
    service.task_repo.list_by_nurse.reset_mock()

    with pytest.raises(ForbiddenException, match="Cross-tenant access is prohibited"):
        await service.list_daily_tasks(
            current_user=nurse_user_orphan,
            nurse_id=99,
            hospital_id=1,
        )
    service.task_repo.list_by_nurse.assert_not_called()


@pytest.mark.asyncio
async def test_nurse_tenant_isolation_list_all_tasks():
    """Verify tenant isolation in list_all_tasks prevents cross-tenant and unassigned nurse access."""
    from unittest.mock import AsyncMock, MagicMock
    from app.core.constants import UserRole
    from app.core.exceptions import ForbiddenException, NotFoundException
    from app.models.nurse_model import Nurse
    from app.services.nurse_service import NurseService

    mock_db = AsyncMock()
    service = NurseService(mock_db)
    service.repo = MagicMock()
    service.task_repo = MagicMock()
    service.task_repo.list_by_nurse = AsyncMock(return_value=[])
    service.task_repo.count_by_nurse = AsyncMock(return_value=0)

    # 1. Hospital A user accessing Hospital A nurse: allowed
    user_hosp_a = MagicMock()
    user_hosp_a.role.name = "Hospital Admin"
    nurse_hosp_a = Nurse(id=10, hospital_id=1, nurse_code="N-001", license_number="L-001")
    service.repo.get_by_id = AsyncMock(return_value=nurse_hosp_a)

    res = await service.list_all_tasks(
        current_user=user_hosp_a,
        nurse_id=10,
        hospital_id=1,
    )
    assert res is not None
    service.repo.get_by_id.assert_awaited_with(10, hospital_id=1)
    service.task_repo.list_by_nurse.assert_awaited()

    # 2. Hospital A user accessing Hospital B nurse: rejected (NotFoundException)
    service.repo.get_by_id = AsyncMock(return_value=None)
    service.task_repo.list_by_nurse.reset_mock()

    with pytest.raises(NotFoundException, match="Nurse not found"):
        await service.list_all_tasks(
            current_user=user_hosp_a,
            nurse_id=20,
            hospital_id=1,
        )
    service.repo.get_by_id.assert_awaited_with(20, hospital_id=1)
    service.task_repo.list_by_nurse.assert_not_called()

    # 3. Hospital A user accessing nurse with hospital_id=None: rejected (NotFoundException)
    service.repo.get_by_id = AsyncMock(return_value=None)
    service.task_repo.list_by_nurse.reset_mock()

    with pytest.raises(NotFoundException, match="Nurse not found"):
        await service.list_all_tasks(
            current_user=user_hosp_a,
            nurse_id=30,
            hospital_id=1,
        )
    service.repo.get_by_id.assert_awaited_with(30, hospital_id=1)
    service.task_repo.list_by_nurse.assert_not_called()

    # 4. User with hospital_id=None attempting nurse access: rejected (ForbiddenException)
    user_no_hosp = MagicMock()
    user_no_hosp.role.name = "Hospital Admin"
    service.task_repo.list_by_nurse.reset_mock()

    with pytest.raises(ForbiddenException, match="Valid hospital tenant context is required"):
        await service.list_all_tasks(
            current_user=user_no_hosp,
            nurse_id=10,
            hospital_id=None,
        )
    service.task_repo.list_by_nurse.assert_not_called()

    # 5. Super Admin accessing cross-hospital nurse: allowed
    super_admin = MagicMock()
    super_admin.role.name = UserRole.SUPER_ADMIN
    nurse_hosp_b = Nurse(id=20, hospital_id=2, nurse_code="N-002", license_number="L-002")
    service.repo.get_by_id = AsyncMock(return_value=nurse_hosp_b)

    res_sa = await service.list_all_tasks(
        current_user=super_admin,
        nurse_id=20,
        hospital_id=None,
    )
    assert res_sa is not None
    service.repo.get_by_id.assert_awaited_with(20, hospital_id=None)
    service.task_repo.list_by_nurse.assert_awaited()


@pytest.mark.asyncio
async def test_nurse_tenant_isolation_get_dashboard_overview():
    """Verify tenant isolation in get_dashboard_overview prevents cross-tenant and unassigned nurse access."""
    from unittest.mock import AsyncMock, MagicMock
    from app.core.constants import UserRole
    from app.core.exceptions import ForbiddenException, NotFoundException
    from app.models.nurse_model import Nurse
    from app.services.nurse_service import NurseService

    mock_db = AsyncMock()
    service = NurseService(mock_db)
    service.assignment_repo = MagicMock()
    service.assignment_repo.list_patients_by_nurse = AsyncMock(return_value=[])

    # 1. Hospital A user accessing Hospital B nurse: query with hospital_id=1 returns None -> NotFoundException
    user_hosp_a = MagicMock()
    user_hosp_a.role.name = "Hospital Admin"
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

    with pytest.raises(NotFoundException, match="Nurse not found"):
        await service.get_dashboard_overview(
            current_user=user_hosp_a,
            nurse_id=20,
            hospital_id=1,
        )

    # 2. Hospital A user accessing nurse with hospital_id=None: returns None -> NotFoundException
    with pytest.raises(NotFoundException, match="Nurse not found"):
        await service.get_dashboard_overview(
            current_user=user_hosp_a,
            nurse_id=30,
            hospital_id=1,
        )

    # 3. User with hospital_id=None: rejected (ForbiddenException)
    user_no_hosp = MagicMock()
    user_no_hosp.role.name = "Hospital Admin"
    user_no_hosp.hospital_id = None
    user_no_hosp.active_hospital_id = None

    with pytest.raises(ForbiddenException, match="Valid hospital tenant context is required"):
        await service.get_dashboard_overview(
            current_user=user_no_hosp,
            nurse_id=10,
            hospital_id=None,
        )

    # 4. Nurse with hospital_id=None accessing dashboard: rejected (ForbiddenException)
    nurse_user_orphan = MagicMock()
    nurse_user_orphan.role.name = UserRole.NURSE
    nurse_user_orphan.id = 99
    nurse_user_orphan.hospital_id = 1
    calling_nurse_orphan = Nurse(id=99, user_id=99, hospital_id=None, nurse_code="N-99", license_number="L-99")
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=calling_nurse_orphan)))

    with pytest.raises(ForbiddenException, match="Cross-tenant access is prohibited"):
        await service.get_dashboard_overview(
            current_user=nurse_user_orphan,
            nurse_id=99,
            hospital_id=1,
        )

    # 5. Super Admin accessing cross-hospital nurse: allowed
    super_admin = MagicMock()
    super_admin.role.name = UserRole.SUPER_ADMIN
    nurse_hosp_b = Nurse(id=20, hospital_id=2, user_id=20, nurse_code="N-002", license_number="L-002")
    
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = nurse_hosp_b
    mock_res.all.return_value = []
    mock_res.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_res)
    mock_db.scalar = AsyncMock(return_value=0)

    service.shift_repo = MagicMock()
    service.shift_repo.list_shifts_by_nurse_and_date = AsyncMock(return_value=[])
    service.shift_repo.list_by_nurse = AsyncMock(return_value=[])
    service.assignment_repo.list_patient_statuses_by_nurse = AsyncMock(return_value=[])
    service.list_medication_schedules = AsyncMock(return_value=[])

    res_sa = await service.get_dashboard_overview(
        current_user=super_admin,
        nurse_id=20,
        hospital_id=None,
    )
    assert res_sa is not None



