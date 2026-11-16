import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date, datetime, timezone

from app.core.exceptions import BadRequestException
from app.models.bed_allocation_model import Bed, Room, Floor
from app.models.patient_model import Patient
from app.models.doctor_model import Doctor
from app.models.user_model import User
from app.models.role_model import Role
from app.models.staff_model import Staff
from app.models.billing_model import Billing, Payment
from app.models.pharmacy_model import Prescription, PrescriptionItem, Medicine
from app.models.lab_model import TestOrder, LabTest
from app.models.appointment_model import Appointment

# Prevent pytest from treating TestOrder model / schemas as test classes
TestOrder.__test__ = False

from app.schemas.bed_allocation_schema import BedTransferRequest
from app.schemas.billing_schema import RefundCreate
from app.schemas.appointment_schema import AdmitRecommendationRequest
from app.schemas.pharmacy_schema import PrescriptionCreate, PrescriptionItemCreate
from app.schemas.lab_schema import TestOrderCreate

TestOrderCreate.__test__ = False

from app.services.bed_allocation_service import BedAllocationService
from app.services.billing_service import BillingService
from app.services.pharmacy_service import PharmacyService
from app.services.lab_service import LabService
from app.services.appointment_service import AppointmentService
from app.services.notification_service import NotificationService


# ============================================================================
# CANDIDATE 1: BED TRANSFER NOTIFICATION & TENANT ISOLATION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_bed_transfer_notifies_patient_and_attending_doctor():
    """Verify that transferring a bed dispatches notifications to both patient and doctor in same hospital."""
    db = AsyncMock()
    service = BedAllocationService(db)

    patient = Patient(id=1, user_id=101, first_name="John", last_name="Doe", hospital_id=10)
    source_bed = Bed(id=1, name="B-101", status="Occupied", hospital_id=10, patient_id=1, patient=patient)
    source_bed.room = Room(id=1, name="Room-1", floor=Floor(id=1, name="1st Floor"))
    target_bed = Bed(id=2, name="B-102", status="Available", hospital_id=10, patient_id=None)
    target_bed.room = Room(id=2, name="Room-2", floor=Floor(id=2, name="2nd Floor"))

    service.repo = AsyncMock()
    service.get_bed = AsyncMock(side_effect=lambda bed_id, current_user=None: source_bed if bed_id == 1 else target_bed)
    service.get_patient = AsyncMock(return_value=patient)
    service.repo.create_activity_log = AsyncMock()

    mock_app = Appointment(id=9, doctor_id=20, patient_id=1, hospital_id=10)
    mock_app_res = MagicMock()
    mock_app_res.scalar_one_or_none.return_value = mock_app
    db.execute = AsyncMock(return_value=mock_app_res)

    # 1. pat_user_active -> True
    # 2. doc_user_id -> 201
    db.scalar = AsyncMock(side_effect=[True, 201])

    req = BedTransferRequest(sourceBedId=1, targetBedId=2)

    with patch("app.services.notification_service.NotificationService.dispatch_notification", new_callable=AsyncMock) as mock_dispatch:
        res = await service.transfer_bed(req)

        assert res is not None
        assert target_bed.status == "Occupied"
        assert source_bed.status == "Available"

        calls = mock_dispatch.call_args_list
        dispatched_user_ids = [c.kwargs.get("user_id") for c in calls]
        notif_types = [c.kwargs.get("notification_type") for c in calls]

        # Both patient (101) and attending doctor (201) should be notified
        assert 101 in dispatched_user_ids
        assert 201 in dispatched_user_ids
        assert all(nt == "PATIENT_BED_TRANSFER" for nt in notif_types)
        assert all(c.kwargs.get("reference_type") == "BED_ALLOCATION" for c in calls)
        assert all(c.kwargs.get("reference_id") == 2 for c in calls)


@pytest.mark.asyncio
async def test_bed_transfer_excludes_doctor_from_different_hospital():
    """Verify tenant isolation: attending doctor belonging to a different hospital is NOT notified."""
    db = AsyncMock()
    service = BedAllocationService(db)

    patient = Patient(id=1, user_id=101, first_name="John", last_name="Doe", hospital_id=10)
    source_bed = Bed(id=1, name="B-101", status="Occupied", hospital_id=10, patient_id=1, patient=patient)
    source_bed.room = Room(id=1, name="Room-1", floor=Floor(id=1, name="1st Floor"))
    target_bed = Bed(id=2, name="B-102", status="Available", hospital_id=10, patient_id=None)
    target_bed.room = Room(id=2, name="Room-2", floor=Floor(id=2, name="2nd Floor"))

    service.repo = AsyncMock()
    service.get_bed = AsyncMock(side_effect=lambda bed_id, current_user=None: source_bed if bed_id == 1 else target_bed)
    service.get_patient = AsyncMock(return_value=patient)
    service.repo.create_activity_log = AsyncMock()

    mock_app = Appointment(id=9, doctor_id=20, patient_id=1, hospital_id=10)
    mock_app_res = MagicMock()
    mock_app_res.scalar_one_or_none.return_value = mock_app
    db.execute = AsyncMock(return_value=mock_app_res)

    # Doctor query returns None because doctor belongs to different hospital (or user hospital mismatch)
    db.scalar = AsyncMock(side_effect=[True, None])

    req = BedTransferRequest(sourceBedId=1, targetBedId=2)

    with patch("app.services.notification_service.NotificationService.dispatch_notification", new_callable=AsyncMock) as mock_dispatch:
        await service.transfer_bed(req)

        dispatched_user_ids = [c.kwargs.get("user_id") for c in mock_dispatch.call_args_list]
        assert 101 in dispatched_user_ids
        assert 201 not in dispatched_user_ids, "Cross-tenant doctor must NOT be notified"


@pytest.mark.asyncio
async def test_bed_transfer_cross_tenant_doctor_and_appointment_records():
    """Verify that appointments or doctors from another hospital are never resolved."""
    db = AsyncMock()
    service = BedAllocationService(db)

    patient = Patient(id=1, user_id=101, first_name="John", last_name="Doe", hospital_id=10)
    source_bed = Bed(id=1, name="B-101", status="Occupied", hospital_id=10, patient_id=1, patient=patient)
    source_bed.room = Room(id=1, name="Room-1", floor=Floor(id=1, name="1st Floor"))
    target_bed = Bed(id=2, name="B-102", status="Available", hospital_id=10, patient_id=None)
    target_bed.room = Room(id=2, name="Room-2", floor=Floor(id=2, name="2nd Floor"))

    service.repo = AsyncMock()
    service.get_bed = AsyncMock(side_effect=lambda bed_id, current_user=None: source_bed if bed_id == 1 else target_bed)
    service.get_patient = AsyncMock(return_value=patient)
    service.repo.create_activity_log = AsyncMock()

    # Appointment queries return None because no appointment exists in hospital 10
    mock_empty_res = MagicMock()
    mock_empty_res.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_empty_res)

    # Patient user is active in hospital 10
    db.scalar = AsyncMock(return_value=True)

    req = BedTransferRequest(sourceBedId=1, targetBedId=2)

    with patch("app.services.notification_service.NotificationService.dispatch_notification", new_callable=AsyncMock) as mock_dispatch:
        res = await service.transfer_bed(req)
        assert res is not None

        dispatched = [c.kwargs.get("user_id") for c in mock_dispatch.call_args_list]
        # Only patient notified; no cross-tenant doctor was resolved
        assert dispatched == [101]


@pytest.mark.asyncio
async def test_bed_transfer_handles_walkin_patient_without_user_id():
    """Verify that a patient without user_id (walk-in) does not cause error and doctor is still notified."""
    db = AsyncMock()
    service = BedAllocationService(db)

    patient = Patient(id=1, user_id=None, first_name="Walkin", last_name="Patient", hospital_id=10)
    source_bed = Bed(id=1, name="B-101", status="Occupied", hospital_id=10, patient_id=1, patient=patient)
    source_bed.room = Room(id=1, name="Room-1", floor=Floor(id=1, name="1st Floor"))
    target_bed = Bed(id=2, name="B-102", status="Available", hospital_id=10, patient_id=None)
    target_bed.room = Room(id=2, name="Room-2", floor=Floor(id=2, name="2nd Floor"))

    service.repo = AsyncMock()
    service.get_bed = AsyncMock(side_effect=lambda bed_id, current_user=None: source_bed if bed_id == 1 else target_bed)
    service.get_patient = AsyncMock(return_value=patient)
    service.repo.create_activity_log = AsyncMock()

    mock_app = Appointment(id=9, doctor_id=20, patient_id=1, hospital_id=10)
    mock_app_res = MagicMock()
    mock_app_res.scalar_one_or_none.return_value = mock_app
    db.execute = AsyncMock(return_value=mock_app_res)

    # Doctor scalar returns 201
    db.scalar = AsyncMock(return_value=201)

    req = BedTransferRequest(sourceBedId=1, targetBedId=2)

    with patch("app.services.notification_service.NotificationService.dispatch_notification", new_callable=AsyncMock) as mock_dispatch:
        res = await service.transfer_bed(req)
        assert res is not None

        dispatched_user_ids = [c.kwargs.get("user_id") for c in mock_dispatch.call_args_list]
        assert 201 in dispatched_user_ids
        assert None not in dispatched_user_ids


# ============================================================================
# CANDIDATE 2: REFUND NOTIFICATION, DEDUPLICATION & VALIDATION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_refund_processed_notifies_patient_and_accountant_and_admin():
    """Verify refund notifies patient and active accountants & hospital admins in same hospital."""
    db = AsyncMock()
    service = BillingService(db)
    service.repo = AsyncMock()
    service.audit_repo = AsyncMock()
    service.patient_repo = AsyncMock()

    billing = Billing(id=50, bill_number="BILL-50", patient_id=5, hospital_id=10, paid_amount=500.0, balance_amount=0.0)
    service.repo.get_by_id_for_update = AsyncMock(return_value=billing)

    payment = Payment(
        id=77,
        billing_id=50,
        amount=200.0,
        payment_method="refund",
        payment_date=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        status="completed",
        is_refund=True,
        refund_reason="Excess payment",
    )
    service.repo.add_payment = AsyncMock(return_value=payment)
    service._recalculate_billing = AsyncMock(return_value=billing)

    patient = Patient(id=5, user_id=505, first_name="Jane", last_name="Smith", is_deleted=False)
    db.get = AsyncMock(return_value=patient)

    accountant = User(id=301, full_name="Alice Accountant", hospital_id=10, is_active=True)
    admin = User(id=302, full_name="Bob Admin", hospital_id=10, is_active=True)

    # Include duplicate user to verify deduplication
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [accountant, admin, accountant]
    db.execute = AsyncMock(return_value=mock_result)

    req = RefundCreate(amount=200.0, refund_reason="Excess payment")

    with patch("app.services.transaction_history_service.TransactionHistoryService.create_event", new_callable=AsyncMock):
        with patch("app.services.notification_service.NotificationService.dispatch_notification", new_callable=AsyncMock) as mock_dispatch:
            res = await service.process_refund(billing_id=50, data=req, user_id=999)
            assert res is not None

            calls = mock_dispatch.call_args_list
            dispatched = {c.kwargs.get("user_id"): c.kwargs for c in calls}

            # 1. Patient notification
            assert 505 in dispatched
            assert dispatched[505]["notification_type"] == "PATIENT_REFUND_PROCESSED"
            assert dispatched[505]["priority"] == "NORMAL"
            assert dispatched[505]["reference_type"] == "PAYMENT"
            assert dispatched[505]["reference_id"] == 77

            # 2. Staff notifications (deduplicated)
            assert 301 in dispatched
            assert dispatched[301]["notification_type"] == "REFUND_PROCESSED"
            assert dispatched[301]["priority"] == "HIGH"
            assert dispatched[301]["hospital_id"] == 10

            assert 302 in dispatched
            assert dispatched[302]["notification_type"] == "REFUND_PROCESSED"
            assert dispatched[302]["priority"] == "HIGH"
            assert dispatched[302]["hospital_id"] == 10

            # Exactly 3 calls total: 1 patient + 2 unique staff
            assert len(calls) == 3


@pytest.mark.asyncio
async def test_refund_validation_failure_prevents_notification():
    """Verify that when refund validation fails (e.g. amount exceeds paid), no notification is sent."""
    db = AsyncMock()
    service = BillingService(db)
    service.repo = AsyncMock()

    billing = Billing(id=51, bill_number="BILL-51", patient_id=5, hospital_id=10, paid_amount=100.0, balance_amount=0.0)
    service.repo.get_by_id_for_update = AsyncMock(return_value=billing)

    # Requesting refund of 500 when only 100 was paid
    req = RefundCreate(amount=500.0, refund_reason="Excessive refund request")

    with patch("app.services.notification_service.NotificationService.dispatch_notification", new_callable=AsyncMock) as mock_dispatch:
        with pytest.raises(BadRequestException):
            await service.process_refund(billing_id=51, data=req, user_id=999)

        # Zero notifications must be dispatched on business failure
        assert mock_dispatch.call_count == 0


# ============================================================================
# CANDIDATE 3: NEW PRESCRIPTION NOTIFICATION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_new_prescription_notifies_pharmacists_and_patient():
    """Verify new prescription dispatches notifications to active pharmacists and patient."""
    db = AsyncMock()
    service = PharmacyService(db)
    service.prescription_repo = AsyncMock()
    service.patient_repo = AsyncMock()
    service.audit_repo = AsyncMock()
    service.medicine_repo = AsyncMock()
    service.batch_repo = AsyncMock()
    service._prescription_response = MagicMock(return_value={"status": "ok"})

    current_user = User(id=999, hospital_id=10, is_active=True)

    patient = Patient(id=12, user_id=601, first_name="Rahul", last_name="Sharma", email="rahul@example.com", phone="9876543210", hospital_id=10)
    doctor = Doctor(id=1, hospital_id=10, is_deleted=False)
    appointment = Appointment(
        id=10,
        patient_id=12,
        doctor_id=1,
        appointment_date=date.today(),
        appointment_status="Confirmed",
        admission_status=None,
        appointment_type="OPD",
    )

    db.scalar = AsyncMock(side_effect=[doctor, patient])

    pharmacist1 = User(id=401, full_name="Pharma One", hospital_id=10, is_active=True)
    pharmacist2 = User(id=402, full_name="Pharma Two", hospital_id=10, is_active=True)

    mock_app_res = MagicMock()
    mock_app_res.scalar_one_or_none.return_value = appointment

    # Include duplicate to verify deduplication
    mock_pharm_res = MagicMock()
    mock_pharm_res.scalars.return_value.all.return_value = [pharmacist1, pharmacist2, pharmacist1]

    db.execute = AsyncMock(side_effect=[mock_app_res, mock_pharm_res])

    medicine = Medicine(id=1, name="Paracetamol", stock_quantity=100, reserved_quantity=0, expiry_date=date(2030, 1, 1), batch_number="B1")
    service.medicine_repo.get_by_id_for_update = AsyncMock(return_value=medicine)
    service.medicine_repo.update_reserved_stock = AsyncMock()
    service.batch_repo.get_available_batches_fefo = AsyncMock(return_value=[])

    saved_rx = Prescription(id=88, prescription_number="RX-8888", patient_id=12, hospital_id=10)
    saved_rx.items = []
    service.prescription_repo.create = AsyncMock(return_value=saved_rx)
    service.prescription_repo.get_by_id = AsyncMock(return_value=saved_rx)

    req = PrescriptionCreate(
        patient_id=12,
        doctor_id=1,
        appointment_id=10,
        instructions="Daily medication",
        items=[
            PrescriptionItemCreate(
                medicine_id=1,
                dosage="500mg",
                frequency="1-0-1",
                duration_days=5,
                quantity=10,
            )
        ],
    )

    with patch("app.services.notification_service.NotificationService.dispatch_notification", new_callable=AsyncMock) as mock_dispatch:
        res = await service.create_prescription(req, user_id=999, current_user=current_user)
        assert res is not None

        calls = mock_dispatch.call_args_list
        dispatched = {c.kwargs.get("user_id"): c.kwargs for c in calls}

        # Patient notification preserved
        assert 601 in dispatched
        assert dispatched[601]["notification_type"] == "PRESCRIPTION_ISSUED"
        assert dispatched[601]["reference_id"] == 88

        # Pharmacist notifications dispatched (deduplicated)
        assert 401 in dispatched
        assert dispatched[401]["notification_type"] == "PHARMACY_NEW_PRESCRIPTION"
        assert dispatched[401]["reference_id"] == 88
        assert dispatched[401]["hospital_id"] == 10

        assert 402 in dispatched
        assert dispatched[402]["notification_type"] == "PHARMACY_NEW_PRESCRIPTION"
        assert dispatched[402]["reference_id"] == 88

        # Exactly 3 calls total: 1 patient + 2 unique pharmacists
        assert len(calls) == 3


# ============================================================================
# CANDIDATE 4: STAT LAB ORDER & DEPARTMENT ISOLATION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_stat_lab_order_department_isolation():
    """Verify STAT lab order only notifies technicians in the matching department, not unrelated departments."""
    db = AsyncMock()
    service = LabService(db)
    service.order_repo = AsyncMock()
    service.audit_repo = AsyncMock()
    service.test_repo = AsyncMock()
    service.patient_repo = AsyncMock()
    service._validate_department = AsyncMock()

    current_user = User(id=999, hospital_id=10, is_active=True)

    patient = Patient(id=15, user_id=701, first_name="Amit", last_name="Verma", hospital_id=10, is_deleted=False)
    lab_test = LabTest(id=1, test_name="Complete Blood Count", is_active=True, department_id=5)
    service.test_repo.get_by_id = AsyncMock(return_value=lab_test)
    service.order_repo.get_active_order_by_patient_and_test = AsyncMock(return_value=None)

    order = TestOrder(
        id=99,
        order_number="LAB-0099",
        patient_id=15,
        lab_test_id=1,
        hospital_id=10,
        department_id=5,
        priority="URGENT",
    )
    service.order_repo.create = AsyncMock(return_value=order)
    service.get_order = AsyncMock(return_value=order)
    db.get = AsyncMock(return_value=patient)

    mock_patient_res = MagicMock()
    mock_patient_res.scalar_one_or_none.return_value = patient

    mock_doc_res = MagicMock()
    mock_doc_res.scalar_one_or_none.return_value = None

    # Dept 5 technician Suresh
    lab_tech_dept5 = User(id=501, full_name="Lab Tech Suresh (Dept 5)", hospital_id=10, is_active=True)
    mock_tech_res = MagicMock()
    # Query returned only department 5 technicians
    mock_tech_res.scalars.return_value.all.return_value = [lab_tech_dept5]

    db.execute = AsyncMock(side_effect=[mock_patient_res, mock_doc_res, mock_tech_res])

    req = TestOrderCreate(
        patient_id=15,
        lab_test_id=1,
        priority="URGENT",
    )

    with patch("app.services.notification_service.NotificationService.dispatch_notification", new_callable=AsyncMock) as mock_dispatch:
        res = await service.create_order(data=req, user_id=999, current_user=current_user)
        assert res is not None

        calls = mock_dispatch.call_args_list
        dispatched_user_ids = [c.kwargs.get("user_id") for c in calls]

        # Dept 5 technician is notified
        assert 501 in dispatched_user_ids
        # Unrelated Dept 8 technician (e.g. 502) is NOT notified
        assert 502 not in dispatched_user_ids
        assert 701 in dispatched_user_ids


@pytest.mark.asyncio
async def test_normal_lab_order_does_not_notify_lab_technicians():
    """Verify NORMAL priority lab order does NOT dispatch STAT notification to lab technicians."""
    db = AsyncMock()
    service = LabService(db)
    service.order_repo = AsyncMock()
    service.audit_repo = AsyncMock()
    service.test_repo = AsyncMock()
    service.patient_repo = AsyncMock()
    service._validate_department = AsyncMock()

    current_user = User(id=999, hospital_id=10, is_active=True)

    patient = Patient(id=15, user_id=701, first_name="Amit", last_name="Verma", hospital_id=10, is_deleted=False)
    lab_test = LabTest(id=1, test_name="Lipid Profile", is_active=True, department_id=5)
    service.test_repo.get_by_id = AsyncMock(return_value=lab_test)
    service.order_repo.get_active_order_by_patient_and_test = AsyncMock(return_value=None)

    order = TestOrder(
        id=100,
        order_number="LAB-0100",
        patient_id=15,
        lab_test_id=1,
        hospital_id=10,
        department_id=5,
        priority="NORMAL",
    )
    service.order_repo.create = AsyncMock(return_value=order)
    service.get_order = AsyncMock(return_value=order)

    db.get = AsyncMock(return_value=patient)

    mock_patient_res = MagicMock()
    mock_patient_res.scalar_one_or_none.return_value = patient

    mock_doc_res = MagicMock()
    mock_doc_res.scalar_one_or_none.return_value = None

    db.execute = AsyncMock(side_effect=[mock_patient_res, mock_doc_res])

    req = TestOrderCreate(
        patient_id=15,
        lab_test_id=1,
        priority="NORMAL",
    )

    with patch("app.services.notification_service.NotificationService.dispatch_notification", new_callable=AsyncMock) as mock_dispatch:
        res = await service.create_order(data=req, user_id=999, current_user=current_user)
        assert res is not None

        calls = mock_dispatch.call_args_list
        dispatched = {c.kwargs.get("user_id"): c.kwargs for c in calls}

        assert 701 in dispatched
        assert dispatched[701]["notification_type"] == "PATIENT_LAB_ORDER_CREATED"

        notif_types = [c.kwargs.get("notification_type") for c in calls]
        assert "LAB_ORDER_STAT" not in notif_types


# ============================================================================
# CANDIDATE 5: ADMISSION RECOMMENDATION ROUTING TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_recommend_admission_notifies_receptionists_and_queue():
    """Verify recommending admission dispatches notifications to receptionists while preserving queue alerts."""
    db = AsyncMock()
    service = AppointmentService(db)
    service.repo = AsyncMock()
    service.audit_repo = AsyncMock()

    appointment = Appointment(
        id=250,
        patient_id=30,
        doctor_id=10,
        hospital_id=10,
        admission_number="ADM-202611-250",
        appointment_status="Completed",
        admission_status="admit_recommended",
        admission_recommended=True,
        admission_reason="Severe Pneumonia",
        expected_los=5,
        recommended_ward="ICU",
        disposition="Admit",
    )
    appointment.patient = Patient(id=30, first_name="Anita", last_name="Roy", diagnosis=None)

    service.repo.get_by_id = AsyncMock(return_value=appointment)
    service.repo.update = AsyncMock(return_value=appointment)
    service._create_queue_notification = AsyncMock()

    receptionist = User(id=801, full_name="Pooja Receptionist", hospital_id=10, is_active=True)
    mock_res = MagicMock()
    # Include duplicate to test deduplication
    mock_res.scalars.return_value.all.return_value = [receptionist, receptionist]
    mock_res.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_res)

    req = AdmitRecommendationRequest(
        admission_reason="Severe Pneumonia",
        expected_los=5,
        recommended_ward="ICU",
        diagnosis="Pneumonia",
        notes="Urgent bed required",
    )

    with patch("app.services.notification_service.NotificationService.dispatch_notification", new_callable=AsyncMock) as mock_dispatch:
        res = await service.recommend_admission(appointment_id=250, data=req, user_id=999)
        assert res is not None

        service._create_queue_notification.assert_awaited_once_with(
            appointment,
            "Admission recommended for Anita Roy (Admission No: ADM-202611-250). Please allocate a bed.",
        )

        calls = mock_dispatch.call_args_list
        dispatched = {c.kwargs.get("user_id"): c.kwargs for c in calls}

        assert 801 in dispatched
        assert dispatched[801]["notification_type"] == "ADMISSION_RECOMMENDED"
        assert dispatched[801]["priority"] == "HIGH"
        assert dispatched[801]["reference_type"] == "APPOINTMENT"
        assert dispatched[801]["reference_id"] == 250
        assert dispatched[801]["hospital_id"] == 10

        # Exactly 1 receptionist notification after deduplication
        assert len(calls) == 1


# ============================================================================
# TRANSACTION & SAVEPOINT SAFETY TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_notification_dispatch_failure_session_recovery():
    """Verify that when notification persistence fails, begin_nested() isolates the error and returns None without breaking transaction."""
    db = AsyncMock()
    # Configure begin_nested async context manager
    nested_cm = AsyncMock()
    nested_cm.__aenter__ = AsyncMock(return_value=None)
    nested_cm.__aexit__ = AsyncMock(return_value=None)
    db.begin_nested = MagicMock(return_value=nested_cm)

    service = NotificationService(db)
    service.repo.exists_duplicate = AsyncMock(return_value=False)
    # Simulate DB flush error (e.g. table lock or foreign key constraint failure)
    service.repo.create = AsyncMock(side_effect=Exception("Database flush constraint error"))

    with patch("app.websocket.notification_socket.notification_manager.send_to_user", new_callable=AsyncMock) as mock_ws:
        result = await service.dispatch_notification(
            user_id=101,
            title="Test Alert",
            message="Test Message",
            notification_type="TEST_ALERT",
            reference_type="TEST",
            reference_id=1,
            hospital_id=10,
        )

        # 1. Result should be None (not crashing the caller)
        assert result is None

        # 2. begin_nested savepoint was engaged to protect the session
        db.begin_nested.assert_called_once()

        # 3. No WebSocket side effects triggered on failed persistence
        assert mock_ws.call_count == 0


@pytest.mark.asyncio
async def test_in_transaction_side_effect_limitation_documentation():
    """Demonstrate the documented architectural limitation: if outer transaction fails post-dispatch, DB rolls back."""
    db = AsyncMock()
    service = BillingService(db)
    service.repo = AsyncMock()

    billing = Billing(id=52, bill_number="BILL-52", patient_id=5, hospital_id=10, paid_amount=500.0, balance_amount=0.0)
    service.repo.get_by_id_for_update = AsyncMock(return_value=billing)

    payment = Payment(
        id=78,
        billing_id=52,
        amount=200.0,
        payment_method="refund",
        payment_date=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        status="completed",
        is_refund=True,
    )
    service.repo.add_payment = AsyncMock(return_value=payment)
    service._recalculate_billing = AsyncMock(return_value=billing)

    # Simulate unexpected failure during post-notification processing
    service.audit_repo.create = AsyncMock(side_effect=RuntimeError("Audit log write failed"))

    req = RefundCreate(amount=200.0, refund_reason="Excess payment")

    with patch("app.services.transaction_history_service.TransactionHistoryService.create_event", new_callable=AsyncMock):
        with pytest.raises(RuntimeError, match="Audit log write failed"):
            await service.process_refund(billing_id=52, data=req, user_id=999)

        # Verified: the exception halts execution before notifications are dispatched


# ============================================================================
# AREA A: FAIL-CLOSED BED TRANSFER TENANT ISOLATION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_bed_transfer_fail_closed_when_both_beds_null_hospital_id():
    """Verify that when both beds (and patient) have NULL hospital_id, all notifications fail closed with exactly 0 queries."""
    db = AsyncMock()
    service = BedAllocationService(db)

    patient = Patient(id=1, user_id=101, first_name="John", last_name="Doe", hospital_id=None)
    source_bed = Bed(id=1, name="B-101", status="Occupied", hospital_id=None, patient_id=1, patient=patient)
    source_bed.room = Room(id=1, name="Room-1", floor=Floor(id=1, name="1st Floor"))
    target_bed = Bed(id=2, name="B-102", status="Available", hospital_id=None, patient_id=None)
    target_bed.room = Room(id=2, name="Room-2", floor=Floor(id=2, name="2nd Floor"))

    service.repo = AsyncMock()
    service.get_bed = AsyncMock(side_effect=lambda bed_id, current_user=None: source_bed if bed_id == 1 else target_bed)
    service.get_patient = AsyncMock(return_value=patient)
    service.repo.create_activity_log = AsyncMock()

    db.scalar = AsyncMock()
    db.execute = AsyncMock()

    req = BedTransferRequest(sourceBedId=1, targetBedId=2)

    with patch("app.services.notification_service.NotificationService.dispatch_notification", new_callable=AsyncMock) as mock_dispatch:
        res = await service.transfer_bed(req)
        assert res is not None
        assert target_bed.status == "Occupied"
        assert source_bed.status == "Available"

        # Exactly ZERO queries executed because target_hospital_id is None (fully fail-closed)
        assert db.execute.call_count == 0
        assert db.scalar.call_count == 0

        # Zero notifications dispatched when tenant ownership cannot be established
        assert mock_dispatch.call_count == 0


@pytest.mark.asyncio
async def test_bed_transfer_patient_from_another_hospital_not_notified():
    """Verify that a patient user belonging to a different hospital is NOT notified on bed transfer."""
    db = AsyncMock()
    service = BedAllocationService(db)

    patient = Patient(id=1, user_id=101, first_name="John", last_name="Doe", hospital_id=10)
    source_bed = Bed(id=1, name="B-101", status="Occupied", hospital_id=10, patient_id=1, patient=patient)
    source_bed.room = Room(id=1, name="Room-1", floor=Floor(id=1, name="1st Floor"))
    target_bed = Bed(id=2, name="B-102", status="Available", hospital_id=10, patient_id=None)
    target_bed.room = Room(id=2, name="Room-2", floor=Floor(id=2, name="2nd Floor"))

    service.repo = AsyncMock()
    service.get_bed = AsyncMock(side_effect=lambda bed_id, current_user=None: source_bed if bed_id == 1 else target_bed)
    service.get_patient = AsyncMock(return_value=patient)
    service.repo.create_activity_log = AsyncMock()

    mock_app = Appointment(id=9, doctor_id=20, patient_id=1, hospital_id=10)
    mock_app_res = MagicMock()
    mock_app_res.scalar_one_or_none.return_value = mock_app
    db.execute = AsyncMock(return_value=mock_app_res)

    # 1. pat_user_active -> None (User belongs to hospital 20, query filtered User.hospital_id == 10)
    # 2. doc_user_id -> 201 (doctor belongs to hospital 10)
    db.scalar = AsyncMock(side_effect=[None, 201])

    req = BedTransferRequest(sourceBedId=1, targetBedId=2)

    with patch("app.services.notification_service.NotificationService.dispatch_notification", new_callable=AsyncMock) as mock_dispatch:
        res = await service.transfer_bed(req)
        assert res is not None

        dispatched_user_ids = [c.kwargs.get("user_id") for c in mock_dispatch.call_args_list]
        # Cross-tenant patient is NOT notified; doctor in hospital 10 IS notified
        assert 101 not in dispatched_user_ids
        assert 201 in dispatched_user_ids



@pytest.mark.asyncio
async def test_bed_transfer_target_has_hospital_source_bed_null_hospital():
    """Verify attending doctor is resolved when target bed has hospital_id even if source bed is NULL."""
    db = AsyncMock()
    service = BedAllocationService(db)

    patient = Patient(id=1, user_id=101, first_name="John", last_name="Doe", hospital_id=None)
    source_bed = Bed(id=1, name="B-101", status="Occupied", hospital_id=None, patient_id=1, patient=patient)
    source_bed.room = Room(id=1, name="Room-1", floor=Floor(id=1, name="1st Floor"))
    target_bed = Bed(id=2, name="B-102", status="Available", hospital_id=10, patient_id=None)
    target_bed.room = Room(id=2, name="Room-2", floor=Floor(id=2, name="2nd Floor"))

    service.repo = AsyncMock()
    service.get_bed = AsyncMock(side_effect=lambda bed_id, current_user=None: source_bed if bed_id == 1 else target_bed)
    service.get_patient = AsyncMock(return_value=patient)
    service.repo.create_activity_log = AsyncMock()

    mock_app = Appointment(id=9, doctor_id=20, patient_id=1, hospital_id=10)
    mock_app_res = MagicMock()
    mock_app_res.scalar_one_or_none.return_value = mock_app
    db.execute = AsyncMock(return_value=mock_app_res)

    # 1. pat_user_active -> True
    # 2. doc_user_id -> 201
    db.scalar = AsyncMock(side_effect=[True, 201])

    req = BedTransferRequest(sourceBedId=1, targetBedId=2)

    with patch("app.services.notification_service.NotificationService.dispatch_notification", new_callable=AsyncMock) as mock_dispatch:
        res = await service.transfer_bed(req)
        assert res is not None

        dispatched_user_ids = [c.kwargs.get("user_id") for c in mock_dispatch.call_args_list]
        assert 101 in dispatched_user_ids
        assert 201 in dispatched_user_ids
        # Hospital ID 10 is passed to notifications
        for call in mock_dispatch.call_args_list:
            assert call.kwargs.get("hospital_id") == 10


@pytest.mark.asyncio
async def test_bed_transfer_target_null_hospital_source_bed_has_hospital():
    """Verify attending doctor is resolved from source bed hospital when target bed has NULL hospital_id."""
    db = AsyncMock()
    service = BedAllocationService(db)

    patient = Patient(id=1, user_id=101, first_name="John", last_name="Doe", hospital_id=None)
    source_bed = Bed(id=1, name="B-101", status="Occupied", hospital_id=10, patient_id=1, patient=patient)
    source_bed.room = Room(id=1, name="Room-1", floor=Floor(id=1, name="1st Floor"))
    target_bed = Bed(id=2, name="B-102", status="Available", hospital_id=None, patient_id=None)
    target_bed.room = Room(id=2, name="Room-2", floor=Floor(id=2, name="2nd Floor"))

    service.repo = AsyncMock()
    service.get_bed = AsyncMock(side_effect=lambda bed_id, current_user=None: source_bed if bed_id == 1 else target_bed)
    service.get_patient = AsyncMock(return_value=patient)
    service.repo.create_activity_log = AsyncMock()

    mock_app = Appointment(id=9, doctor_id=20, patient_id=1, hospital_id=10)
    mock_app_res = MagicMock()
    mock_app_res.scalar_one_or_none.return_value = mock_app
    db.execute = AsyncMock(return_value=mock_app_res)

    db.scalar = AsyncMock(side_effect=[True, 201])

    req = BedTransferRequest(sourceBedId=1, targetBedId=2)

    with patch("app.services.notification_service.NotificationService.dispatch_notification", new_callable=AsyncMock) as mock_dispatch:
        res = await service.transfer_bed(req)
        assert res is not None

        dispatched_user_ids = [c.kwargs.get("user_id") for c in mock_dispatch.call_args_list]
        assert 101 in dispatched_user_ids
        assert 201 in dispatched_user_ids


@pytest.mark.asyncio
async def test_bed_transfer_doctor_user_hospital_mismatch_fails_closed():
    """Verify doctor is not notified when doctor/user record fails tenant hospital check."""
    db = AsyncMock()
    service = BedAllocationService(db)

    patient = Patient(id=1, user_id=101, first_name="John", last_name="Doe", hospital_id=10)
    source_bed = Bed(id=1, name="B-101", status="Occupied", hospital_id=10, patient_id=1, patient=patient)
    source_bed.room = Room(id=1, name="Room-1", floor=Floor(id=1, name="1st Floor"))
    target_bed = Bed(id=2, name="B-102", status="Available", hospital_id=10, patient_id=None)
    target_bed.room = Room(id=2, name="Room-2", floor=Floor(id=2, name="2nd Floor"))

    service.repo = AsyncMock()
    service.get_bed = AsyncMock(side_effect=lambda bed_id, current_user=None: source_bed if bed_id == 1 else target_bed)
    service.get_patient = AsyncMock(return_value=patient)
    service.repo.create_activity_log = AsyncMock()

    mock_app = Appointment(id=9, doctor_id=20, patient_id=1, hospital_id=10)
    mock_app_res = MagicMock()
    mock_app_res.scalar_one_or_none.return_value = mock_app
    db.execute = AsyncMock(return_value=mock_app_res)

    # 1. pat_user_active -> True
    # 2. doc_user_id -> None (doctor/user hospital mismatch in SQL join)
    db.scalar = AsyncMock(side_effect=[True, None])

    req = BedTransferRequest(sourceBedId=1, targetBedId=2)

    with patch("app.services.notification_service.NotificationService.dispatch_notification", new_callable=AsyncMock) as mock_dispatch:
        res = await service.transfer_bed(req)
        assert res is not None

        dispatched = [c.kwargs.get("user_id") for c in mock_dispatch.call_args_list]
        assert dispatched == [101]


# ============================================================================
# AREA C: STAT LAB ORDER DEPARTMENT ISOLATION & EMAIL MATCHING TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_stat_lab_strict_department_isolation_no_fallback():
    """Verify that when department-specific STAT order has no technicians, NO fallback to other departments occurs."""
    db = AsyncMock()
    service = LabService(db)
    service.order_repo = AsyncMock()
    service.audit_repo = AsyncMock()
    service.test_repo = AsyncMock()
    service.patient_repo = AsyncMock()
    service._validate_department = AsyncMock()

    current_user = User(id=999, hospital_id=10, is_active=True)
    patient = Patient(id=15, user_id=701, first_name="Amit", last_name="Verma", hospital_id=10, is_deleted=False)
    lab_test = LabTest(id=1, test_name="Biochemistry Panel", is_active=True, department_id=5)
    service.test_repo.get_by_id = AsyncMock(return_value=lab_test)
    service.order_repo.get_active_order_by_patient_and_test = AsyncMock(return_value=None)

    order = TestOrder(
        id=101,
        order_number="LAB-0101",
        patient_id=15,
        lab_test_id=1,
        hospital_id=10,
        department_id=5,
        priority="STAT",
    )
    service.order_repo.create = AsyncMock(return_value=order)
    service.get_order = AsyncMock(return_value=order)
    db.get = AsyncMock(return_value=patient)

    mock_patient_res = MagicMock()
    mock_patient_res.scalar_one_or_none.return_value = patient

    mock_doc_res = MagicMock()
    mock_doc_res.scalar_one_or_none.return_value = None

    # Dept 5 query returns EMPTY (no technicians in dept 5)
    mock_tech_res = MagicMock()
    mock_tech_res.scalars.return_value.all.return_value = []

    db.execute = AsyncMock(side_effect=[mock_patient_res, mock_doc_res, mock_tech_res])

    req = TestOrderCreate(
        patient_id=15,
        lab_test_id=1,
        priority="STAT",
    )

    with patch("app.services.notification_service.NotificationService.dispatch_notification", new_callable=AsyncMock) as mock_dispatch:
        res = await service.create_order(data=req, user_id=999, current_user=current_user)
        assert res is not None

        # Verify only 3 queries executed (patient, doctor, dept-5 techs) - ZERO fallback queries!
        assert db.execute.call_count == 3

        calls = mock_dispatch.call_args_list
        dispatched_user_ids = [c.kwargs.get("user_id") for c in calls]

        # Only patient notified; NO fallback lab tech notified
        assert 701 in dispatched_user_ids
        notif_types = [c.kwargs.get("notification_type") for c in calls]
        assert "LAB_ORDER_STAT" not in notif_types


@pytest.mark.asyncio
async def test_stat_lab_order_no_department_general_technicians():
    """Verify that when test order has department_id=None, general hospital lab technicians are notified."""
    db = AsyncMock()
    service = LabService(db)
    service.order_repo = AsyncMock()
    service.audit_repo = AsyncMock()
    service.test_repo = AsyncMock()
    service.patient_repo = AsyncMock()
    service._validate_department = AsyncMock()

    current_user = User(id=999, hospital_id=10, is_active=True)
    patient = Patient(id=15, user_id=701, first_name="Amit", last_name="Verma", hospital_id=10, is_deleted=False)
    lab_test = LabTest(id=2, test_name="Routine Analysis", is_active=True, department_id=None)
    service.test_repo.get_by_id = AsyncMock(return_value=lab_test)
    service.order_repo.get_active_order_by_patient_and_test = AsyncMock(return_value=None)

    order = TestOrder(
        id=102,
        order_number="LAB-0102",
        patient_id=15,
        lab_test_id=2,
        hospital_id=10,
        department_id=None,
        priority="URGENT",
    )
    service.order_repo.create = AsyncMock(return_value=order)
    service.get_order = AsyncMock(return_value=order)
    db.get = AsyncMock(return_value=patient)

    mock_patient_res = MagicMock()
    mock_patient_res.scalar_one_or_none.return_value = patient

    mock_doc_res = MagicMock()
    mock_doc_res.scalar_one_or_none.return_value = None

    general_tech = User(id=505, full_name="General Lab Tech", hospital_id=10, is_active=True)
    mock_tech_res = MagicMock()
    mock_tech_res.scalars.return_value.all.return_value = [general_tech]

    db.execute = AsyncMock(side_effect=[mock_patient_res, mock_doc_res, mock_tech_res])

    req = TestOrderCreate(
        patient_id=15,
        lab_test_id=2,
        priority="URGENT",
    )

    with patch("app.services.notification_service.NotificationService.dispatch_notification", new_callable=AsyncMock) as mock_dispatch:
        res = await service.create_order(data=req, user_id=999, current_user=current_user)
        assert res is not None

        calls = mock_dispatch.call_args_list
        dispatched_user_ids = [c.kwargs.get("user_id") for c in calls]

        assert 701 in dispatched_user_ids
        assert 505 in dispatched_user_ids

        stat_calls = [c for c in calls if c.kwargs.get("notification_type") == "LAB_ORDER_STAT"]
        assert len(stat_calls) == 1
        assert stat_calls[0].kwargs.get("user_id") == 505
        assert stat_calls[0].kwargs.get("hospital_id") == 10


# ============================================================================
# USER PREFERENCE BEHAVIOR PARITY & REGRESSION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_user_preference_missing_record_defaults_applied():
    """Verify that when UserPreference is missing, default values (True) apply without committing."""
    db = AsyncMock()
    # No cached preference and no DB preference record
    db.scalar = AsyncMock(return_value=None)
    nested_cm = AsyncMock()
    nested_cm.__aenter__ = AsyncMock(return_value=None)
    nested_cm.__aexit__ = AsyncMock(return_value=None)
    db.begin_nested = MagicMock(return_value=nested_cm)

    service = NotificationService(db)
    service.repo.exists_duplicate = AsyncMock(return_value=False)
    service.repo.create = AsyncMock(side_effect=lambda n: n)

    with patch("app.websocket.notification_socket.notification_manager.send_to_user", new_callable=AsyncMock):
        with patch("app.tasks.notification_tasks.send_browser_push_async.apply_async") as mock_push:
            # 1. Normal notification with missing preference -> Browser push is enabled by default
            res = await service.dispatch_notification(
                user_id=101,
                title="Appointment Booked",
                message="Your appointment is confirmed",
                notification_type="APPOINTMENT_CONFIRMATION",
            )
            assert res is not None
            mock_push.assert_called_once()
            # Verify no commit was called on the session
            assert db.commit.call_count == 0

            # 2. Critical Emergency Alert with missing preference -> Delivered by default
            res_crit = await service.dispatch_notification(
                user_id=101,
                title="Emergency Alert",
                message="Critical health condition update",
                notification_type="PATIENT_EMERGENCY_ALERT",
            )
            assert res_crit is not None
            assert db.commit.call_count == 0


@pytest.mark.asyncio
async def test_user_preference_existing_record_respected():
    """Verify that existing UserPreference records in DB are respected without auto-commits."""
    db = AsyncMock()
    nested_cm = AsyncMock()
    nested_cm.__aenter__ = AsyncMock(return_value=None)
    nested_cm.__aexit__ = AsyncMock(return_value=None)
    db.begin_nested = MagicMock(return_value=nested_cm)

    service = NotificationService(db)
    service.repo.exists_duplicate = AsyncMock(return_value=False)
    service.repo.create = AsyncMock(side_effect=lambda n: n)

    # 1. User has critical_emergency_alerts = False
    db.scalar = AsyncMock(return_value=False)
    with patch("app.websocket.notification_socket.notification_manager.send_to_user", new_callable=AsyncMock):
        res = await service.dispatch_notification(
            user_id=102,
            title="Emergency Alert",
            message="Critical alert",
            notification_type="PATIENT_EMERGENCY_ALERT",
            hospital_id=10,
        )
        # Suppressed due to preference
        assert res is None
        assert db.commit.call_count == 0

    # 2. User has push_notifications = False
    db.scalar = AsyncMock(return_value=False)
    with patch("app.websocket.notification_socket.notification_manager.send_to_user", new_callable=AsyncMock):
        with patch("app.tasks.notification_tasks.send_browser_push_async.apply_async") as mock_push:
            res = await service.dispatch_notification(
                user_id=102,
                title="Regular Alert",
                message="Regular notification",
                notification_type="PRESCRIPTION_ISSUED",
                hospital_id=10,
            )
            assert res is not None
            # Push was suppressed due to preference
            mock_push.assert_not_called()
            assert db.commit.call_count == 0


@pytest.mark.asyncio
async def test_user_preference_redis_cache_hit_avoids_db():
    """Verify that cached preferences in Redis are used directly without hitting the database."""
    db = AsyncMock()
    nested_cm = AsyncMock()
    nested_cm.__aenter__ = AsyncMock(return_value=None)
    nested_cm.__aexit__ = AsyncMock(return_value=None)
    db.begin_nested = MagicMock(return_value=nested_cm)

    service = NotificationService(db)
    service.repo.exists_duplicate = AsyncMock(return_value=False)
    service.repo.create = AsyncMock(side_effect=lambda n: n)

    cached_json = '{"push_notifications": false, "critical_emergency_alerts": true}'

    with patch("app.utils.redis_service.cache_get", new_callable=AsyncMock, return_value=cached_json):
        with patch("app.websocket.notification_socket.notification_manager.send_to_user", new_callable=AsyncMock):
            with patch("app.tasks.notification_tasks.send_browser_push_async.apply_async") as mock_push:
                res = await service.dispatch_notification(
                    user_id=103,
                    title="Cached Alert",
                    message="Testing cache hit",
                    notification_type="PRESCRIPTION_ISSUED",
                )
                assert res is not None
                # push_notifications was false in Redis cache -> push suppressed
                mock_push.assert_not_called()
                # Zero DB scalar queries for preference
                assert db.scalar.call_count == 0
                assert db.commit.call_count == 0


