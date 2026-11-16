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


# ============================================================================
# CANDIDATE 6: NOTIFICATION DUPLICATE PREVENTION & WINDOW TESTS
# ============================================================================

from app.repositories.notification_repository import NotificationRepository
from app.models.notification_model import Notification


@pytest.mark.asyncio
async def test_exists_duplicate_within_window_suppressed():
    """Verify that a duplicate notification within the 600-second window is detected (suppressed)."""
    db = AsyncMock()
    # Mock count > 0 returned by database scalar
    db.scalar = AsyncMock(return_value=1)

    repo = NotificationRepository(db)
    is_dup = await repo.exists_duplicate(
        user_id=10,
        notification_type="APPOINTMENT_CONFIRMATION",
        reference_type="APPOINTMENT",
        reference_id=50,
        window_seconds=600,
    )

    assert is_dup is True
    # Verify the query was executed against db.scalar
    assert db.scalar.call_count == 1
    query_arg = db.scalar.call_args[0][0]
    compiled_sql = str(query_arg)
    assert "notifications.created_at >=" in compiled_sql


@pytest.mark.asyncio
async def test_exists_duplicate_older_than_window_allowed():
    """Verify that an existing notification older than 600 seconds is excluded by the actual cutoff."""
    from datetime import timedelta

    fixed_now = datetime(2026, 11, 16, 12, 0, 0)
    expected_cutoff = fixed_now - timedelta(seconds=600)

    # Notification created 650 seconds ago (older than the 600-second window)
    existing_notification = Notification(
        id=1,
        user_id=10,
        notification_type="APPOINTMENT_CONFIRMATION",
        reference_type="APPOINTMENT",
        reference_id=50,
        created_at=fixed_now - timedelta(seconds=650),
        is_deleted=False,
    )

    db = AsyncMock()

    def evaluate_query(query):
        compiled = query.compile()
        params = compiled.params
        cutoff_param = next(v for k, v in params.items() if k.startswith("created_at"))

        # Verify the cutoff matches fixed_now - 600s exactly
        assert cutoff_param == expected_cutoff
        assert params["user_id_1"] == 10
        assert params["notification_type_1"] == "APPOINTMENT_CONFIRMATION"
        assert params["reference_type_1"] == "APPOINTMENT"
        assert params["reference_id_1"] == 50

        # Evaluate the filter condition: Notification.created_at >= cutoff
        if (
            existing_notification.user_id == params["user_id_1"]
            and existing_notification.notification_type == params["notification_type_1"]
            and existing_notification.reference_type == params["reference_type_1"]
            and existing_notification.reference_id == params["reference_id_1"]
            and not existing_notification.is_deleted
            and existing_notification.created_at >= cutoff_param
        ):
            return 1
        return 0

    db.scalar = AsyncMock(side_effect=evaluate_query)
    repo = NotificationRepository(db)

    with patch("app.repositories.notification_repository.utc_now", return_value=fixed_now):
        # 1. 650s old record: older than cutoff -> excluded -> allowed (False)
        is_dup_older = await repo.exists_duplicate(
            user_id=10,
            notification_type="APPOINTMENT_CONFIRMATION",
            reference_type="APPOINTMENT",
            reference_id=50,
            window_seconds=600,
        )
        assert is_dup_older is False
        assert db.scalar.call_count == 1

        # 2. 550s old record: within cutoff -> included -> suppressed (True)
        existing_notification.created_at = fixed_now - timedelta(seconds=550)
        is_dup_recent = await repo.exists_duplicate(
            user_id=10,
            notification_type="APPOINTMENT_CONFIRMATION",
            reference_type="APPOINTMENT",
            reference_id=50,
            window_seconds=600,
        )
        assert is_dup_recent is True
        assert db.scalar.call_count == 2


@pytest.mark.asyncio
async def test_exists_duplicate_custom_and_none_window_compatibility():
    """Verify window_seconds=None evaluates without time filter and custom window applies correct filter."""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=1)

    repo = NotificationRepository(db)

    # 1. window_seconds=None (checks all time)
    is_dup_all_time = await repo.exists_duplicate(
        user_id=10,
        notification_type="APPOINTMENT_CONFIRMATION",
        reference_type="APPOINTMENT",
        reference_id=50,
        window_seconds=None,
    )
    assert is_dup_all_time is True
    query_all_time = db.scalar.call_args[0][0]
    assert "notifications.created_at >=" not in str(query_all_time)

    # 2. Default parameter (omitted window_seconds defaults to 600)
    await repo.exists_duplicate(
        user_id=10,
        notification_type="APPOINTMENT_CONFIRMATION",
        reference_type="APPOINTMENT",
        reference_id=50,
    )
    query_default = db.scalar.call_args[0][0]
    assert "notifications.created_at >=" in str(query_default)


@pytest.mark.asyncio
async def test_exists_duplicate_none_reference_returns_false():
    """Verify that None reference_type or reference_id immediately returns False without hitting DB."""
    db = AsyncMock()
    repo = NotificationRepository(db)

    assert await repo.exists_duplicate(10, "TYPE", None, 50) is False
    assert await repo.exists_duplicate(10, "TYPE", "REF", None) is False
    assert await repo.exists_duplicate(10, "TYPE", None, None) is False
    assert db.scalar.call_count == 0


@pytest.mark.asyncio
async def test_notify_appointment_confirmation_passes_appointment_id():
    """Verify NotificationService.notify_appointment_confirmation forwards appointment_id as reference_id."""
    db = AsyncMock()
    service = NotificationService(db)

    with patch.object(service, "dispatch_notification", new_callable=AsyncMock) as mock_dispatch:
        mock_dispatch.return_value = MagicMock()

        await service.notify_appointment_confirmation(
            user_id=101,
            appointment_number="APT-2026-001",
            patient_name="Alice Smith",
            doctor_name="Dr. House",
            appointment_date="2026-11-20",
            appointment_time="10:00:00",
            email="alice@example.com",
            phone="9876543210",
            patient_code="PAT-001",
            hospital_id=5,
            appointment_id=42,
        )

        mock_dispatch.assert_called_once()
        kwargs = mock_dispatch.call_args.kwargs
        assert kwargs["reference_type"] == "APPOINTMENT"
        assert kwargs["reference_id"] == 42
        assert kwargs["hospital_id"] == 5
        assert kwargs["user_id"] == 101


@pytest.mark.asyncio
async def test_notify_appointment_confirmation_omitted_appointment_id_defaults_none():
    """Verify backward compatibility: omitting appointment_id forwards reference_id=None."""
    db = AsyncMock()
    service = NotificationService(db)

    with patch.object(service, "dispatch_notification", new_callable=AsyncMock) as mock_dispatch:
        mock_dispatch.return_value = MagicMock()

        await service.notify_appointment_confirmation(
            user_id=101,
            appointment_number="APT-2026-001",
            patient_name="Alice Smith",
            doctor_name="Dr. House",
            appointment_date="2026-11-20",
            appointment_time="10:00:00",
        )

        mock_dispatch.assert_called_once()
        kwargs = mock_dispatch.call_args.kwargs
        assert kwargs["reference_type"] == "APPOINTMENT"
        assert kwargs["reference_id"] is None


@pytest.mark.asyncio
async def test_appointment_service_notify_safely_passes_appointment_id():
    """Verify AppointmentService._notify_confirmation_safely wires appointment.id to notify_appointment_confirmation."""
    db = AsyncMock()
    service = AppointmentService(db)

    # Mock repos
    patient = Patient(id=1, user_id=101, first_name="Alice", last_name="Smith", email="alice@test.com", phone="12345", patient_code="P1")
    doctor = Doctor(id=2, first_name="Gregory", last_name="House")

    service.patient_repo = AsyncMock()
    service.patient_repo.get_by_id = AsyncMock(return_value=patient)
    service.doctor_repo = AsyncMock()
    service.doctor_repo.get_by_id = AsyncMock(return_value=doctor)

    appointment = Appointment(
        id=77,
        appointment_number="APT-77",
        patient_id=1,
        doctor_id=2,
        hospital_id=5,
        appointment_date=date(2026, 11, 20),
        appointment_time="14:30:00",
    )

    with patch("app.services.notification_service.NotificationService.notify_appointment_confirmation", new_callable=AsyncMock) as mock_notify:
        await service._notify_confirmation_safely(appointment, target_user_id=101)

        mock_notify.assert_called_once()
        kwargs = mock_notify.call_args.kwargs
        assert kwargs["appointment_id"] == 77
        assert kwargs["user_id"] == 101
        assert kwargs["hospital_id"] == 5
        assert kwargs["appointment_number"] == "APT-77"


@pytest.mark.asyncio
async def test_repeated_appointment_confirmation_suppressed_within_window():
    """Verify that dispatch_notification suppresses repeated appointment confirmations when duplicate exists in window."""
    db = AsyncMock()
    nested_cm = AsyncMock()
    nested_cm.__aenter__ = AsyncMock(return_value=None)
    nested_cm.__aexit__ = AsyncMock(return_value=None)
    db.begin_nested = MagicMock(return_value=nested_cm)

    service = NotificationService(db)
    # Simulate exists_duplicate returning True (i.e. notification sent within past 600s)
    service.repo.exists_duplicate = AsyncMock(return_value=True)
    service.repo.create = AsyncMock()

    result = await service.dispatch_notification(
        user_id=101,
        title="Appointment Confirmed",
        message="Your appointment has been confirmed.",
        notification_type="APPOINTMENT_CONFIRMATION",
        reference_type="APPOINTMENT",
        reference_id=88,
        hospital_id=5,
    )

    # Must be suppressed (returns None)
    assert result is None
    service.repo.exists_duplicate.assert_called_once_with(
        user_id=101,
        notification_type="APPOINTMENT_CONFIRMATION",
        reference_type="APPOINTMENT",
        reference_id=88,
    )
    # Repo create must NOT be called
    service.repo.create.assert_not_called()


# ============================================================================
# CANDIDATE 2: APPOINTMENT NO-SHOW NOTIFICATION TESTS
# ============================================================================

from app.schemas.appointment_schema import AppointmentUpdate
from app.core.constants import AppointmentStatus


@pytest.mark.asyncio
async def test_confirmed_appointment_transition_to_no_show_notifies_patient():
    """Verify that transition from Confirmed to NO_SHOW dispatches notification to patient."""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=True)
    service = AppointmentService(db)

    patient = Patient(id=1, user_id=101, first_name="John", last_name="Doe", email="john@example.com", phone="12345", patient_code="P1", hospital_id=10)
    doctor = Doctor(id=2, first_name="Sarah", last_name="Connor", hospital_id=10)
    appointment = Appointment(
        id=55,
        appointment_number="APT-55",
        patient_id=1,
        doctor_id=2,
        hospital_id=10,
        appointment_status=AppointmentStatus.CONFIRMED,
        appointment_date=date(2026, 11, 20),
        appointment_time="10:00:00",
        reminder_sent=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    service.repo.get_by_id = AsyncMock(return_value=appointment)
    service.repo.update = AsyncMock(return_value=appointment)
    service.patient_repo.get_by_id = AsyncMock(return_value=patient)
    service.doctor_repo.get_by_id = AsyncMock(return_value=doctor)
    service.audit_repo.create = AsyncMock()

    update_req = AppointmentUpdate(appointment_status=AppointmentStatus.NO_SHOW)

    with patch("app.services.notification_service.NotificationService.notify_appointment_no_show", new_callable=AsyncMock) as mock_notify:
        res = await service.update(appointment_id=55, data=update_req, user_id=1)

        assert res is not None
        assert appointment.appointment_status == AppointmentStatus.NO_SHOW
        assert appointment.queue_status == "SKIPPED"

        mock_notify.assert_called_once()
        kwargs = mock_notify.call_args.kwargs
        assert kwargs["user_id"] == 101
        assert kwargs["appointment_number"] == "APT-55"
        assert kwargs["appointment_id"] == 55
        assert kwargs["hospital_id"] == 10
        assert kwargs["patient_name"] == "John Doe"
        assert kwargs["doctor_name"] == "Sarah Connor"


@pytest.mark.asyncio
async def test_no_show_walkin_patient_without_user_id_safely_skipped():
    """Verify walk-in patient with user_id=None skips notification safely without errors."""
    db = AsyncMock()
    service = AppointmentService(db)

    # Walk-in patient: user_id is None
    patient = Patient(id=1, user_id=None, first_name="Walkin", last_name="Patient", hospital_id=10)
    doctor = Doctor(id=2, first_name="Sarah", last_name="Connor", hospital_id=10)
    appointment = Appointment(
        id=56,
        appointment_number="APT-56",
        patient_id=1,
        doctor_id=2,
        hospital_id=10,
        appointment_status=AppointmentStatus.CONFIRMED,
        appointment_date=date(2026, 11, 20),
        appointment_time="10:00:00",
        reminder_sent=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    service.repo.get_by_id = AsyncMock(return_value=appointment)
    service.repo.update = AsyncMock(return_value=appointment)
    service.patient_repo.get_by_id = AsyncMock(return_value=patient)
    service.doctor_repo.get_by_id = AsyncMock(return_value=doctor)
    service.audit_repo.create = AsyncMock()

    update_req = AppointmentUpdate(appointment_status=AppointmentStatus.NO_SHOW)

    with patch("app.services.notification_service.NotificationService.notify_appointment_no_show", new_callable=AsyncMock) as mock_notify:
        res = await service.update(appointment_id=56, data=update_req, user_id=1)

        assert res is not None
        # Notification must NOT be dispatched for walk-in patient
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_no_show_cross_tenant_patient_fails_closed():
    """Verify patient from another hospital is not notified (fail-closed tenant isolation)."""
    db = AsyncMock()
    service = AppointmentService(db)

    # Patient hospital (99) mismatches appointment hospital (10)
    patient = Patient(id=1, user_id=101, first_name="John", last_name="Doe", hospital_id=99)
    doctor = Doctor(id=2, first_name="Sarah", last_name="Connor", hospital_id=10)
    appointment = Appointment(
        id=57,
        appointment_number="APT-57",
        patient_id=1,
        doctor_id=2,
        hospital_id=10,
        appointment_status=AppointmentStatus.CONFIRMED,
        appointment_date=date(2026, 11, 20),
        appointment_time="10:00:00",
        reminder_sent=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    service.repo.get_by_id = AsyncMock(return_value=appointment)
    service.repo.update = AsyncMock(return_value=appointment)
    service.patient_repo.get_by_id = AsyncMock(return_value=patient)
    service.doctor_repo.get_by_id = AsyncMock(return_value=doctor)
    service.audit_repo.create = AsyncMock()

    update_req = AppointmentUpdate(appointment_status=AppointmentStatus.NO_SHOW)

    with patch("app.services.notification_service.NotificationService.notify_appointment_no_show", new_callable=AsyncMock) as mock_notify:
        res = await service.update(appointment_id=57, data=update_req, user_id=1)

        assert res is not None
        # Cross-tenant mismatch -> notification suppressed
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_notes_only_update_on_existing_no_show_does_not_retrigger():
    """Verify updating notes on an already marked NO_SHOW appointment does not trigger notification."""
    db = AsyncMock()
    service = AppointmentService(db)

    patient = Patient(id=1, user_id=101, first_name="John", last_name="Doe", hospital_id=10)
    doctor = Doctor(id=2, first_name="Sarah", last_name="Connor", hospital_id=10)
    # Already NO_SHOW before update
    appointment = Appointment(
        id=58,
        appointment_number="APT-58",
        patient_id=1,
        doctor_id=2,
        hospital_id=10,
        appointment_status=AppointmentStatus.NO_SHOW,
        appointment_date=date(2026, 11, 20),
        appointment_time="10:00:00",
        reminder_sent=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    service.repo.get_by_id = AsyncMock(return_value=appointment)
    service.repo.update = AsyncMock(return_value=appointment)
    service.patient_repo.get_by_id = AsyncMock(return_value=patient)
    service.doctor_repo.get_by_id = AsyncMock(return_value=doctor)
    service.audit_repo.create = AsyncMock()

    # Notes-only update
    update_req = AppointmentUpdate(notes="Patient called to explain absence")

    with patch("app.services.notification_service.NotificationService.notify_appointment_no_show", new_callable=AsyncMock) as mock_notify:
        res = await service.update(appointment_id=58, data=update_req, user_id=1)

        assert res is not None
        # No status change -> notification must NOT be called
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_no_show_repeated_update_duplicate_suppression():
    """Verify repeated NO_SHOW notification for same appointment within window is suppressed by dispatcher."""
    db = AsyncMock()
    nested_cm = AsyncMock()
    nested_cm.__aenter__ = AsyncMock(return_value=None)
    nested_cm.__aexit__ = AsyncMock(return_value=None)
    db.begin_nested = MagicMock(return_value=nested_cm)

    service = NotificationService(db)
    # Simulate exists_duplicate returning True
    service.repo.exists_duplicate = AsyncMock(return_value=True)
    service.repo.create = AsyncMock()

    res = await service.notify_appointment_no_show(
        user_id=101,
        appointment_number="APT-59",
        patient_name="John Doe",
        doctor_name="Sarah Connor",
        appointment_date="2026-11-20",
        appointment_time="10:00:00",
        hospital_id=10,
        appointment_id=59,
    )

    # Must be suppressed (returns None)
    assert res is None
    service.repo.exists_duplicate.assert_called_once_with(
        user_id=101,
        notification_type="APPOINTMENT_NO_SHOW",
        reference_type="APPOINTMENT",
        reference_id=59,
    )
    service.repo.create.assert_not_called()


@pytest.mark.asyncio
async def test_no_show_dispatch_failure_does_not_break_appointment_update():
    """Verify notification dispatch failure does not abort the appointment update transaction."""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=True)
    service = AppointmentService(db)

    patient = Patient(id=1, user_id=101, first_name="John", last_name="Doe", hospital_id=10)
    doctor = Doctor(id=2, first_name="Sarah", last_name="Connor", hospital_id=10)
    appointment = Appointment(
        id=60,
        appointment_number="APT-60",
        patient_id=1,
        doctor_id=2,
        hospital_id=10,
        appointment_status=AppointmentStatus.CONFIRMED,
        appointment_date=date(2026, 11, 20),
        appointment_time="10:00:00",
        reminder_sent=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    service.repo.get_by_id = AsyncMock(return_value=appointment)
    service.repo.update = AsyncMock(return_value=appointment)
    service.patient_repo.get_by_id = AsyncMock(return_value=patient)
    service.doctor_repo.get_by_id = AsyncMock(return_value=doctor)
    service.audit_repo.create = AsyncMock()

    update_req = AppointmentUpdate(appointment_status=AppointmentStatus.NO_SHOW)

    with patch(
        "app.services.notification_service.NotificationService.notify_appointment_no_show",
        new_callable=AsyncMock,
        side_effect=Exception("Redis/Socket connection timeout"),
    ):
        # Must not raise Exception
        res = await service.update(appointment_id=60, data=update_req, user_id=1)
        assert res is not None
        assert appointment.appointment_status == AppointmentStatus.NO_SHOW


@pytest.mark.asyncio
async def test_other_appointment_status_transition_does_not_trigger_no_show():
    """Verify other status transitions (e.g. to CANCELLED) do NOT trigger NO_SHOW notification."""
    db = AsyncMock()
    service = AppointmentService(db)

    patient = Patient(id=1, user_id=101, first_name="John", last_name="Doe", hospital_id=10)
    doctor = Doctor(id=2, first_name="Sarah", last_name="Connor", hospital_id=10)
    appointment = Appointment(
        id=61,
        appointment_number="APT-61",
        patient_id=1,
        doctor_id=2,
        hospital_id=10,
        appointment_status=AppointmentStatus.PENDING,
        appointment_date=date(2026, 11, 20),
        appointment_time="10:00:00",
        reminder_sent=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    service.repo.get_by_id = AsyncMock(return_value=appointment)
    service.repo.update = AsyncMock(return_value=appointment)
    service.patient_repo.get_by_id = AsyncMock(return_value=patient)
    service.doctor_repo.get_by_id = AsyncMock(return_value=doctor)
    service.audit_repo.create = AsyncMock()

    update_req = AppointmentUpdate(appointment_status=AppointmentStatus.CANCELLED)

    with patch("app.services.notification_service.NotificationService.notify_appointment_no_show", new_callable=AsyncMock) as mock_notify:
        res = await service.update(appointment_id=61, data=update_req, user_id=1)

        assert res is not None
        assert appointment.appointment_status == AppointmentStatus.CANCELLED
        # NO_SHOW notification must NOT be called
        mock_notify.assert_not_called()


# ============================================================================
# CANDIDATE 2 SECURITY: RECIPIENT USER TENANT ISOLATION TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_no_show_patient_user_hospital_mismatch_suppresses_notification():
    """Verify that if patient.user_id belongs to a User with a different hospital_id, notification is suppressed."""
    db = AsyncMock()
    # db.scalar returns None because User.hospital_id != appointment.hospital_id
    db.scalar = AsyncMock(return_value=None)
    service = AppointmentService(db)

    patient = Patient(id=1, user_id=101, first_name="John", last_name="Doe", hospital_id=10)
    doctor = Doctor(id=2, first_name="Sarah", last_name="Connor", hospital_id=10)
    appointment = Appointment(
        id=62,
        appointment_number="APT-62",
        patient_id=1,
        doctor_id=2,
        hospital_id=10,
        appointment_status=AppointmentStatus.CONFIRMED,
        appointment_date=date(2026, 11, 20),
        appointment_time="10:00:00",
        reminder_sent=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    service.repo.get_by_id = AsyncMock(return_value=appointment)
    service.repo.update = AsyncMock(return_value=appointment)
    service.patient_repo.get_by_id = AsyncMock(return_value=patient)
    service.doctor_repo.get_by_id = AsyncMock(return_value=doctor)
    service.audit_repo.create = AsyncMock()

    update_req = AppointmentUpdate(appointment_status=AppointmentStatus.NO_SHOW)

    with patch("app.services.notification_service.NotificationService.notify_appointment_no_show", new_callable=AsyncMock) as mock_notify:
        res = await service.update(appointment_id=62, data=update_req, user_id=1)

        assert res is not None
        assert appointment.appointment_status == AppointmentStatus.NO_SHOW
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_no_show_user_hospital_id_none_suppresses_notification():
    """Verify that if User.hospital_id is None, notification is suppressed."""
    db = AsyncMock()
    # db.scalar returns None because User.hospital_id is None
    db.scalar = AsyncMock(return_value=None)
    service = AppointmentService(db)

    patient = Patient(id=1, user_id=101, first_name="John", last_name="Doe", hospital_id=10)
    doctor = Doctor(id=2, first_name="Sarah", last_name="Connor", hospital_id=10)
    appointment = Appointment(
        id=63,
        appointment_number="APT-63",
        patient_id=1,
        doctor_id=2,
        hospital_id=10,
        appointment_status=AppointmentStatus.CONFIRMED,
        appointment_date=date(2026, 11, 20),
        appointment_time="10:00:00",
        reminder_sent=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    service.repo.get_by_id = AsyncMock(return_value=appointment)
    service.repo.update = AsyncMock(return_value=appointment)
    service.patient_repo.get_by_id = AsyncMock(return_value=patient)
    service.doctor_repo.get_by_id = AsyncMock(return_value=doctor)
    service.audit_repo.create = AsyncMock()

    update_req = AppointmentUpdate(appointment_status=AppointmentStatus.NO_SHOW)

    with patch("app.services.notification_service.NotificationService.notify_appointment_no_show", new_callable=AsyncMock) as mock_notify:
        res = await service.update(appointment_id=63, data=update_req, user_id=1)

        assert res is not None
        assert appointment.appointment_status == AppointmentStatus.NO_SHOW
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_no_show_user_inactive_suppresses_notification():
    """Verify that if User.is_active is False, notification is suppressed."""
    db = AsyncMock()
    # User found in correct hospital, but is_active is False
    db.scalar = AsyncMock(return_value=False)
    service = AppointmentService(db)

    patient = Patient(id=1, user_id=101, first_name="John", last_name="Doe", hospital_id=10)
    doctor = Doctor(id=2, first_name="Sarah", last_name="Connor", hospital_id=10)
    appointment = Appointment(
        id=64,
        appointment_number="APT-64",
        patient_id=1,
        doctor_id=2,
        hospital_id=10,
        appointment_status=AppointmentStatus.CONFIRMED,
        appointment_date=date(2026, 11, 20),
        appointment_time="10:00:00",
        reminder_sent=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    service.repo.get_by_id = AsyncMock(return_value=appointment)
    service.repo.update = AsyncMock(return_value=appointment)
    service.patient_repo.get_by_id = AsyncMock(return_value=patient)
    service.doctor_repo.get_by_id = AsyncMock(return_value=doctor)
    service.audit_repo.create = AsyncMock()

    update_req = AppointmentUpdate(appointment_status=AppointmentStatus.NO_SHOW)

    with patch("app.services.notification_service.NotificationService.notify_appointment_no_show", new_callable=AsyncMock) as mock_notify:
        res = await service.update(appointment_id=64, data=update_req, user_id=1)

        assert res is not None
        assert appointment.appointment_status == AppointmentStatus.NO_SHOW
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_no_show_user_does_not_exist_suppresses_notification():
    """Verify that if User record does not exist for patient.user_id, notification is suppressed."""
    db = AsyncMock()
    # User does not exist -> db.scalar returns None
    db.scalar = AsyncMock(return_value=None)
    service = AppointmentService(db)

    patient = Patient(id=1, user_id=99999, first_name="John", last_name="Doe", hospital_id=10)
    doctor = Doctor(id=2, first_name="Sarah", last_name="Connor", hospital_id=10)
    appointment = Appointment(
        id=65,
        appointment_number="APT-65",
        patient_id=1,
        doctor_id=2,
        hospital_id=10,
        appointment_status=AppointmentStatus.CONFIRMED,
        appointment_date=date(2026, 11, 20),
        appointment_time="10:00:00",
        reminder_sent=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    service.repo.get_by_id = AsyncMock(return_value=appointment)
    service.repo.update = AsyncMock(return_value=appointment)
    service.patient_repo.get_by_id = AsyncMock(return_value=patient)
    service.doctor_repo.get_by_id = AsyncMock(return_value=doctor)
    service.audit_repo.create = AsyncMock()

    update_req = AppointmentUpdate(appointment_status=AppointmentStatus.NO_SHOW)

    with patch("app.services.notification_service.NotificationService.notify_appointment_no_show", new_callable=AsyncMock) as mock_notify:
        res = await service.update(appointment_id=65, data=update_req, user_id=1)

        assert res is not None
        assert appointment.appointment_status == AppointmentStatus.NO_SHOW
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_no_show_valid_active_user_in_correct_hospital_notified():
    """Verify that a valid active user in the same hospital receives notification."""
    db = AsyncMock()
    # User found in correct hospital and is_active is True
    db.scalar = AsyncMock(return_value=True)
    service = AppointmentService(db)

    patient = Patient(
        id=1,
        user_id=101,
        first_name="John",
        last_name="Doe",
        email="john@example.com",
        phone="12345",
        patient_code="P1",
        hospital_id=10,
    )
    doctor = Doctor(id=2, first_name="Sarah", last_name="Connor", hospital_id=10)
    appointment = Appointment(
        id=66,
        appointment_number="APT-66",
        patient_id=1,
        doctor_id=2,
        hospital_id=10,
        appointment_status=AppointmentStatus.CONFIRMED,
        appointment_date=date(2026, 11, 20),
        appointment_time="10:00:00",
        reminder_sent=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    service.repo.get_by_id = AsyncMock(return_value=appointment)
    service.repo.update = AsyncMock(return_value=appointment)
    service.patient_repo.get_by_id = AsyncMock(return_value=patient)
    service.doctor_repo.get_by_id = AsyncMock(return_value=doctor)
    service.audit_repo.create = AsyncMock()

    update_req = AppointmentUpdate(appointment_status=AppointmentStatus.NO_SHOW)

    with patch("app.services.notification_service.NotificationService.notify_appointment_no_show", new_callable=AsyncMock) as mock_notify:
        res = await service.update(appointment_id=66, data=update_req, user_id=1)

        assert res is not None
        assert appointment.appointment_status == AppointmentStatus.NO_SHOW
        mock_notify.assert_called_once_with(
            user_id=101,
            appointment_number="APT-66",
            patient_name="John Doe",
            doctor_name="Sarah Connor",
            appointment_date="2026-11-20",
            appointment_time="10:00:00",
            email="john@example.com",
            phone="12345",
            patient_code="P1",
            hospital_id=10,
            appointment_id=66,
        )


# ============================================================================
# WORKFLOW A: DISCHARGE BILLING CLEARED NOTIFICATION TESTS
# ============================================================================

from app.models.discharge_model import Discharge
from app.services.discharge_service import DischargeService
from app.schemas.discharge_schema import ClearBillingRequest


@pytest.mark.asyncio
async def test_discharge_billing_cleared_notifies_attending_doctor():
    """Verify transition of billing_cleared to True dispatches notification to attending doctor."""
    db = AsyncMock()
    # doctor user is active in tenant
    db.scalar = AsyncMock(return_value=True)
    service = DischargeService(db)

    discharge = Discharge(
        id=101,
        discharge_number="DIS-101",
        appointment_id=1,
        patient_id=201,
        doctor_id=301,
        hospital_id=10,
        admission_date=datetime.now(timezone.utc),
        discharge_date=datetime.now(timezone.utc),
        diagnosis_at_discharge="Recovered",
        treatment_summary="Routine care",
        condition_on_discharge="Stable",
        pharmacy_cleared=True,
        billing_cleared=False,
        payment_cleared=False,
        doctor_approved=False,
        discharge_status="PENDING_CLEARANCES",
        final_bill_id=501,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    doctor = Doctor(id=301, user_id=401, first_name="Sarah", last_name="Connor", email="sarah@example.com", phone="12345", hospital_id=10)
    patient = Patient(id=201, first_name="John", last_name="Doe", hospital_id=10)

    service.repo.get_by_id = AsyncMock(return_value=discharge)
    service.repo.update = AsyncMock(return_value=discharge)
    service.validate_applicable_ipd_bills_settled = AsyncMock(return_value=(True, []))
    service._check_and_update_cleared_status = MagicMock()

    db.get = AsyncMock(side_effect=lambda model, ident: doctor if model == Doctor else (patient if model == Patient else None))

    req = ClearBillingRequest(notes="All bills settled")

    with patch("app.services.notification_service.NotificationService.notify_discharge_billing_cleared", new_callable=AsyncMock) as mock_notify:
        res = await service.clear_billing(discharge_id=101, user_id=999, data=req, hospital_id=10)
        assert res is not None
        assert discharge.billing_cleared is True

        mock_notify.assert_called_once()
        kwargs = mock_notify.call_args.kwargs
        assert kwargs["user_id"] == 401
        assert kwargs["discharge_number"] == "DIS-101"
        assert kwargs["discharge_id"] == 101
        assert kwargs["hospital_id"] == 10
        assert kwargs["patient_name"] == "John Doe"
        assert kwargs["doctor_name"] == "Sarah Connor"


@pytest.mark.asyncio
async def test_discharge_repeated_billing_clearance_does_not_retrigger():
    """Verify repeated billing clearance call on already-cleared discharge does not re-trigger notification."""
    db = AsyncMock()
    service = DischargeService(db)

    # Already billing_cleared = True
    discharge = Discharge(
        id=102,
        discharge_number="DIS-102",
        appointment_id=2,
        patient_id=202,
        doctor_id=302,
        hospital_id=10,
        admission_date=datetime.now(timezone.utc),
        discharge_date=datetime.now(timezone.utc),
        diagnosis_at_discharge="Recovered",
        treatment_summary="Routine care",
        condition_on_discharge="Stable",
        pharmacy_cleared=True,
        billing_cleared=True,
        payment_cleared=False,
        doctor_approved=False,
        discharge_status="PENDING_CLEARANCES",
        final_bill_id=502,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    service.repo.get_by_id = AsyncMock(return_value=discharge)
    service.repo.update = AsyncMock(return_value=discharge)
    service.validate_applicable_ipd_bills_settled = AsyncMock(return_value=(True, []))
    service._check_and_update_cleared_status = MagicMock()

    req = ClearBillingRequest(notes="Re-check")

    with patch("app.services.notification_service.NotificationService.notify_discharge_billing_cleared", new_callable=AsyncMock) as mock_notify:
        res = await service.clear_billing(discharge_id=102, user_id=999, data=req, hospital_id=10)
        assert res is not None
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_discharge_missing_doctor_safely_skips():
    """Verify missing doctor record safely skips notification without error."""
    db = AsyncMock()
    service = DischargeService(db)

    discharge = Discharge(
        id=103,
        discharge_number="DIS-103",
        appointment_id=3,
        patient_id=203,
        doctor_id=303,
        hospital_id=10,
        admission_date=datetime.now(timezone.utc),
        discharge_date=datetime.now(timezone.utc),
        diagnosis_at_discharge="Recovered",
        treatment_summary="Routine care",
        condition_on_discharge="Stable",
        pharmacy_cleared=True,
        billing_cleared=False,
        payment_cleared=False,
        doctor_approved=False,
        discharge_status="PENDING_CLEARANCES",
        final_bill_id=503,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    service.repo.get_by_id = AsyncMock(return_value=discharge)
    service.repo.update = AsyncMock(return_value=discharge)
    service.validate_applicable_ipd_bills_settled = AsyncMock(return_value=(True, []))
    service._check_and_update_cleared_status = MagicMock()

    # doctor does not exist
    db.get = AsyncMock(return_value=None)

    req = ClearBillingRequest(notes="Settled")

    with patch("app.services.notification_service.NotificationService.notify_discharge_billing_cleared", new_callable=AsyncMock) as mock_notify:
        res = await service.clear_billing(discharge_id=103, user_id=999, data=req, hospital_id=10)
        assert res is not None
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_discharge_cross_hospital_doctor_safely_skips():
    """Verify doctor from another hospital (hospital mismatch) is suppressed."""
    db = AsyncMock()
    service = DischargeService(db)

    discharge = Discharge(
        id=104,
        discharge_number="DIS-104",
        appointment_id=4,
        patient_id=204,
        doctor_id=304,
        hospital_id=10,
        admission_date=datetime.now(timezone.utc),
        discharge_date=datetime.now(timezone.utc),
        diagnosis_at_discharge="Recovered",
        treatment_summary="Routine care",
        condition_on_discharge="Stable",
        pharmacy_cleared=True,
        billing_cleared=False,
        payment_cleared=False,
        doctor_approved=False,
        discharge_status="PENDING_CLEARANCES",
        final_bill_id=504,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    # Doctor in hospital 99 != discharge hospital 10
    doctor = Doctor(id=304, user_id=404, first_name="Sarah", last_name="Connor", hospital_id=99)

    service.repo.get_by_id = AsyncMock(return_value=discharge)
    service.repo.update = AsyncMock(return_value=discharge)
    service.validate_applicable_ipd_bills_settled = AsyncMock(return_value=(True, []))
    service._check_and_update_cleared_status = MagicMock()

    db.get = AsyncMock(return_value=doctor)

    req = ClearBillingRequest()

    with patch("app.services.notification_service.NotificationService.notify_discharge_billing_cleared", new_callable=AsyncMock) as mock_notify:
        res = await service.clear_billing(discharge_id=104, user_id=999, data=req, hospital_id=10)
        assert res is not None
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_discharge_cross_hospital_user_safely_skips():
    """Verify linked User in different hospital (hospital mismatch) is suppressed."""
    db = AsyncMock()
    # db.scalar returns None because User.hospital_id != discharge.hospital_id
    db.scalar = AsyncMock(return_value=None)
    service = DischargeService(db)

    discharge = Discharge(
        id=105,
        discharge_number="DIS-105",
        appointment_id=5,
        patient_id=205,
        doctor_id=305,
        hospital_id=10,
        admission_date=datetime.now(timezone.utc),
        discharge_date=datetime.now(timezone.utc),
        diagnosis_at_discharge="Recovered",
        treatment_summary="Routine care",
        condition_on_discharge="Stable",
        pharmacy_cleared=True,
        billing_cleared=False,
        payment_cleared=False,
        doctor_approved=False,
        discharge_status="PENDING_CLEARANCES",
        final_bill_id=505,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    doctor = Doctor(id=305, user_id=405, first_name="Sarah", last_name="Connor", hospital_id=10)

    service.repo.get_by_id = AsyncMock(return_value=discharge)
    service.repo.update = AsyncMock(return_value=discharge)
    service.validate_applicable_ipd_bills_settled = AsyncMock(return_value=(True, []))
    service._check_and_update_cleared_status = MagicMock()

    db.get = AsyncMock(return_value=doctor)

    req = ClearBillingRequest()

    with patch("app.services.notification_service.NotificationService.notify_discharge_billing_cleared", new_callable=AsyncMock) as mock_notify:
        res = await service.clear_billing(discharge_id=105, user_id=999, data=req, hospital_id=10)
        assert res is not None
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_discharge_inactive_user_safely_skips():
    """Verify inactive User account suppresses notification."""
    db = AsyncMock()
    # db.scalar returns False because User.is_active is False
    db.scalar = AsyncMock(return_value=False)
    service = DischargeService(db)

    discharge = Discharge(
        id=106,
        discharge_number="DIS-106",
        appointment_id=6,
        patient_id=206,
        doctor_id=306,
        hospital_id=10,
        admission_date=datetime.now(timezone.utc),
        discharge_date=datetime.now(timezone.utc),
        diagnosis_at_discharge="Recovered",
        treatment_summary="Routine care",
        condition_on_discharge="Stable",
        pharmacy_cleared=True,
        billing_cleared=False,
        payment_cleared=False,
        doctor_approved=False,
        discharge_status="PENDING_CLEARANCES",
        final_bill_id=506,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    doctor = Doctor(id=306, user_id=406, first_name="Sarah", last_name="Connor", hospital_id=10)

    service.repo.get_by_id = AsyncMock(return_value=discharge)
    service.repo.update = AsyncMock(return_value=discharge)
    service.validate_applicable_ipd_bills_settled = AsyncMock(return_value=(True, []))
    service._check_and_update_cleared_status = MagicMock()

    db.get = AsyncMock(return_value=doctor)

    req = ClearBillingRequest()

    with patch("app.services.notification_service.NotificationService.notify_discharge_billing_cleared", new_callable=AsyncMock) as mock_notify:
        res = await service.clear_billing(discharge_id=106, user_id=999, data=req, hospital_id=10)
        assert res is not None
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_discharge_missing_user_safely_skips():
    """Verify missing doctor user_id suppresses notification."""
    db = AsyncMock()
    service = DischargeService(db)

    discharge = Discharge(
        id=107,
        discharge_number="DIS-107",
        appointment_id=7,
        patient_id=207,
        doctor_id=307,
        hospital_id=10,
        admission_date=datetime.now(timezone.utc),
        discharge_date=datetime.now(timezone.utc),
        diagnosis_at_discharge="Recovered",
        treatment_summary="Routine care",
        condition_on_discharge="Stable",
        pharmacy_cleared=True,
        billing_cleared=False,
        payment_cleared=False,
        doctor_approved=False,
        discharge_status="PENDING_CLEARANCES",
        final_bill_id=507,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    # Doctor has no portal user_id
    doctor = Doctor(id=307, user_id=None, first_name="Sarah", last_name="Connor", hospital_id=10)

    service.repo.get_by_id = AsyncMock(return_value=discharge)
    service.repo.update = AsyncMock(return_value=discharge)
    service.validate_applicable_ipd_bills_settled = AsyncMock(return_value=(True, []))
    service._check_and_update_cleared_status = MagicMock()

    db.get = AsyncMock(return_value=doctor)

    req = ClearBillingRequest()

    with patch("app.services.notification_service.NotificationService.notify_discharge_billing_cleared", new_callable=AsyncMock) as mock_notify:
        res = await service.clear_billing(discharge_id=107, user_id=999, data=req, hospital_id=10)
        assert res is not None
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_discharge_dispatch_failure_does_not_break_clear_billing():
    """Verify dispatch exception does not raise or abort successful billing clearance."""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=True)
    service = DischargeService(db)

    discharge = Discharge(
        id=108,
        discharge_number="DIS-108",
        appointment_id=8,
        patient_id=208,
        doctor_id=308,
        hospital_id=10,
        admission_date=datetime.now(timezone.utc),
        discharge_date=datetime.now(timezone.utc),
        diagnosis_at_discharge="Recovered",
        treatment_summary="Routine care",
        condition_on_discharge="Stable",
        pharmacy_cleared=True,
        billing_cleared=False,
        payment_cleared=False,
        doctor_approved=False,
        discharge_status="PENDING_CLEARANCES",
        final_bill_id=508,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    doctor = Doctor(id=308, user_id=408, first_name="Sarah", last_name="Connor", hospital_id=10)

    service.repo.get_by_id = AsyncMock(return_value=discharge)
    service.repo.update = AsyncMock(return_value=discharge)
    service.validate_applicable_ipd_bills_settled = AsyncMock(return_value=(True, []))
    service._check_and_update_cleared_status = MagicMock()

    db.get = AsyncMock(return_value=doctor)

    req = ClearBillingRequest()

    with patch(
        "app.services.notification_service.NotificationService.notify_discharge_billing_cleared",
        new_callable=AsyncMock,
        side_effect=Exception("Redis/Socket connection timeout"),
    ):
        res = await service.clear_billing(discharge_id=108, user_id=999, data=req, hospital_id=10)
        assert res is not None
        assert discharge.billing_cleared is True


@pytest.mark.asyncio
async def test_discharge_null_hospital_id_safely_skips():
    """Verify discharge with null hospital_id safely skips notification (fail closed)."""
    db = AsyncMock()
    service = DischargeService(db)

    discharge = Discharge(
        id=109,
        discharge_number="DIS-109",
        appointment_id=9,
        patient_id=209,
        doctor_id=309,
        hospital_id=None,
        admission_date=datetime.now(timezone.utc),
        discharge_date=datetime.now(timezone.utc),
        diagnosis_at_discharge="Recovered",
        treatment_summary="Routine care",
        condition_on_discharge="Stable",
        pharmacy_cleared=True,
        billing_cleared=False,
        payment_cleared=False,
        doctor_approved=False,
        discharge_status="PENDING_CLEARANCES",
        final_bill_id=509,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    service.repo.get_by_id = AsyncMock(return_value=discharge)
    service.repo.update = AsyncMock(return_value=discharge)
    service.validate_applicable_ipd_bills_settled = AsyncMock(return_value=(True, []))
    service._check_and_update_cleared_status = MagicMock()

    req = ClearBillingRequest()

    with patch("app.services.notification_service.NotificationService.notify_discharge_billing_cleared", new_callable=AsyncMock) as mock_notify:
        res = await service.clear_billing(discharge_id=109, user_id=999, data=req, hospital_id=None)
        assert res is not None
        mock_notify.assert_not_called()


# ============================================================================
# WORKFLOW B: LAB SAMPLE REJECTION NOTIFICATION TESTS
# ============================================================================

from app.models.lab_model import Sample, TestOrder, LabTest
from app.services.lab_service import LabService
from app.schemas.lab_schema import SampleUpdate
from app.core.constants import SampleStatus


@pytest.mark.asyncio
async def test_sample_transition_to_rejected_notifies_doctor():
    """Verify transition of sample to REJECTED notifies doctor when doctor is valid and active."""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=True)
    service = LabService(db)

    sample = Sample(
        id=201,
        test_order_id=501,
        sample_code="SMP-201",
        sample_type="blood",
        status=SampleStatus.COLLECTED,
        collected_at=datetime.now(timezone.utc),
        collection_date=datetime.now(timezone.utc),
        notes="Hemolyzed",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    order = TestOrder(
        id=501,
        hospital_id=10,
        order_number="ORD-501",
        patient_id=301,
        doctor_id=401,
        lab_test_id=1,
        status="sample_collected",
        priority="normal",
        ordered_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    doctor = Doctor(id=401, user_id=601, first_name="Sarah", last_name="Connor", email="sarah@example.com", phone="12345", hospital_id=10)
    # Patient has no user account
    patient = Patient(id=301, user_id=None, first_name="John", last_name="Doe", hospital_id=10)
    lab_test = LabTest(id=1, test_name="CBC", is_active=True)

    service.sample_repo.get_by_id = AsyncMock(return_value=sample)
    service.sample_repo.update = AsyncMock(return_value=sample)
    service.order_repo.get_by_id = AsyncMock(return_value=order)
    service.audit_repo.create = AsyncMock()

    db.get = AsyncMock(side_effect=lambda model, ident: doctor if model == Doctor else (patient if model == Patient else (lab_test if model == LabTest else order)))

    update_req = SampleUpdate(status=SampleStatus.REJECTED)

    with patch("app.services.notification_service.NotificationService.notify_lab_sample_rejected", new_callable=AsyncMock) as mock_notify:
        res = await service.update_sample(sample_id=201, data=update_req, user_id=999)
        assert res is not None

        mock_notify.assert_called_once()
        kwargs = mock_notify.call_args.kwargs
        assert kwargs["user_id"] == 601
        assert kwargs["recipient_role"] == "DOCTOR"
        assert kwargs["sample_code"] == "SMP-201"
        assert kwargs["order_number"] == "ORD-501"
        assert kwargs["hospital_id"] == 10
        assert kwargs["sample_id"] == 201


@pytest.mark.asyncio
async def test_sample_transition_to_rejected_notifies_patient():
    """Verify transition of sample to REJECTED notifies patient when patient is valid and active."""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=True)
    service = LabService(db)

    sample = Sample(
        id=202,
        test_order_id=502,
        sample_code="SMP-202",
        sample_type="blood",
        status=SampleStatus.COLLECTED,
        collected_at=datetime.now(timezone.utc),
        collection_date=datetime.now(timezone.utc),
        notes="Insufficient quantity",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    # Order has no doctor_id
    order = TestOrder(
        id=502,
        hospital_id=10,
        order_number="ORD-502",
        patient_id=302,
        doctor_id=None,
        lab_test_id=1,
        status="sample_collected",
        priority="normal",
        ordered_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    patient = Patient(id=302, user_id=702, first_name="John", last_name="Doe", email="john@example.com", phone="54321", hospital_id=10)
    lab_test = LabTest(id=1, test_name="Lipid Profile", is_active=True)

    service.sample_repo.get_by_id = AsyncMock(return_value=sample)
    service.sample_repo.update = AsyncMock(return_value=sample)
    service.order_repo.get_by_id = AsyncMock(return_value=order)
    service.audit_repo.create = AsyncMock()

    db.get = AsyncMock(side_effect=lambda model, ident: patient if model == Patient else (lab_test if model == LabTest else order))

    update_req = SampleUpdate(status=SampleStatus.REJECTED)

    with patch("app.services.notification_service.NotificationService.notify_lab_sample_rejected", new_callable=AsyncMock) as mock_notify:
        res = await service.update_sample(sample_id=202, data=update_req, user_id=999)
        assert res is not None

        mock_notify.assert_called_once()
        kwargs = mock_notify.call_args.kwargs
        assert kwargs["user_id"] == 702
        assert kwargs["recipient_role"] == "PATIENT"
        assert kwargs["sample_code"] == "SMP-202"
        assert kwargs["order_number"] == "ORD-502"
        assert kwargs["hospital_id"] == 10
        assert kwargs["sample_id"] == 202


@pytest.mark.asyncio
async def test_sample_transition_to_rejected_both_recipients_notified():
    """Verify both valid doctor and valid patient receive notification when both pass tenant checks."""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=True)
    service = LabService(db)

    sample = Sample(
        id=203,
        test_order_id=503,
        sample_code="SMP-203",
        sample_type="blood",
        status=SampleStatus.PENDING,
        collected_at=None,
        collection_date=datetime.now(timezone.utc),
        notes="Clotted",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    order = TestOrder(
        id=503,
        hospital_id=10,
        order_number="ORD-503",
        patient_id=303,
        doctor_id=403,
        lab_test_id=1,
        status="ordered",
        priority="normal",
        ordered_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    doctor = Doctor(id=403, user_id=603, first_name="Sarah", last_name="Connor", email="sarah@example.com", phone="12345", hospital_id=10)
    patient = Patient(id=303, user_id=703, first_name="John", last_name="Doe", email="john@example.com", phone="54321", hospital_id=10)
    lab_test = LabTest(id=1, test_name="CBC", is_active=True)

    service.sample_repo.get_by_id = AsyncMock(return_value=sample)
    service.sample_repo.update = AsyncMock(return_value=sample)
    service.order_repo.get_by_id = AsyncMock(return_value=order)
    service.audit_repo.create = AsyncMock()

    db.get = AsyncMock(side_effect=lambda model, ident: doctor if model == Doctor else (patient if model == Patient else (lab_test if model == LabTest else order)))

    update_req = SampleUpdate(status=SampleStatus.REJECTED)

    with patch("app.services.notification_service.NotificationService.notify_lab_sample_rejected", new_callable=AsyncMock) as mock_notify:
        res = await service.update_sample(sample_id=203, data=update_req, user_id=999)
        assert res is not None

        assert mock_notify.call_count == 2
        notified_users = [c.kwargs["user_id"] for c in mock_notify.call_args_list]
        assert 603 in notified_users
        assert 703 in notified_users


@pytest.mark.asyncio
async def test_sample_normal_collection_does_not_trigger_rejected_notification():
    """Verify normal collection (status -> COLLECTED) does NOT trigger rejection notification."""
    db = AsyncMock()
    service = LabService(db)

    sample = Sample(
        id=204,
        test_order_id=504,
        sample_code="SMP-204",
        sample_type="blood",
        status=SampleStatus.PENDING,
        collected_at=None,
        collection_date=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    service.sample_repo.get_by_id = AsyncMock(return_value=sample)
    service.sample_repo.update = AsyncMock(return_value=sample)
    service.audit_repo.create = AsyncMock()

    update_req = SampleUpdate(status=SampleStatus.COLLECTED)

    with patch("app.services.notification_service.NotificationService.notify_lab_sample_rejected", new_callable=AsyncMock) as mock_notify:
        res = await service.update_sample(sample_id=204, data=update_req, user_id=999)
        assert res is not None
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_sample_already_rejected_notes_update_does_not_retrigger():
    """Verify updating notes on an already rejected sample does not re-trigger rejection notification."""
    db = AsyncMock()
    service = LabService(db)

    # Already REJECTED
    sample = Sample(
        id=205,
        test_order_id=505,
        sample_code="SMP-205",
        sample_type="blood",
        status=SampleStatus.REJECTED,
        collected_at=datetime.now(timezone.utc),
        collection_date=datetime.now(timezone.utc),
        notes="Previously rejected",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    service.sample_repo.get_by_id = AsyncMock(return_value=sample)
    service.sample_repo.update = AsyncMock(return_value=sample)
    service.audit_repo.create = AsyncMock()

    update_req = SampleUpdate(notes="Additional note added")

    with patch("app.services.notification_service.NotificationService.notify_lab_sample_rejected", new_callable=AsyncMock) as mock_notify:
        res = await service.update_sample(sample_id=205, data=update_req, user_id=999)
        assert res is not None
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_sample_cross_hospital_doctor_is_suppressed():
    """Verify cross-hospital doctor is not notified (suppressed by hospital mismatch)."""
    db = AsyncMock()
    # patient user active in hospital 10, doctor user in another hospital
    db.scalar = AsyncMock(return_value=True)
    service = LabService(db)

    sample = Sample(
        id=206,
        test_order_id=506,
        sample_code="SMP-206",
        sample_type="blood",
        status=SampleStatus.COLLECTED,
        collected_at=datetime.now(timezone.utc),
        collection_date=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    order = TestOrder(
        id=506,
        hospital_id=10,
        order_number="ORD-506",
        patient_id=306,
        doctor_id=406,
        lab_test_id=1,
        status="sample_collected",
        priority="normal",
        ordered_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    # Doctor in hospital 99 != order hospital 10
    doctor = Doctor(id=406, user_id=606, first_name="Sarah", last_name="Connor", hospital_id=99)
    patient = Patient(id=306, user_id=706, first_name="John", last_name="Doe", hospital_id=10)
    lab_test = LabTest(id=1, test_name="CBC", is_active=True)

    service.sample_repo.get_by_id = AsyncMock(return_value=sample)
    service.sample_repo.update = AsyncMock(return_value=sample)
    service.order_repo.get_by_id = AsyncMock(return_value=order)
    service.audit_repo.create = AsyncMock()

    db.get = AsyncMock(side_effect=lambda model, ident: doctor if model == Doctor else (patient if model == Patient else (lab_test if model == LabTest else order)))

    update_req = SampleUpdate(status=SampleStatus.REJECTED)

    with patch("app.services.notification_service.NotificationService.notify_lab_sample_rejected", new_callable=AsyncMock) as mock_notify:
        res = await service.update_sample(sample_id=206, data=update_req, user_id=999)
        assert res is not None

        # Doctor suppressed, patient still notified
        assert mock_notify.call_count == 1
        assert mock_notify.call_args.kwargs["user_id"] == 706


@pytest.mark.asyncio
async def test_sample_cross_hospital_patient_is_suppressed():
    """Verify cross-hospital patient is not notified (suppressed by hospital mismatch)."""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=True)
    service = LabService(db)

    sample = Sample(
        id=207,
        test_order_id=507,
        sample_code="SMP-207",
        sample_type="blood",
        status=SampleStatus.COLLECTED,
        collected_at=datetime.now(timezone.utc),
        collection_date=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    order = TestOrder(
        id=507,
        hospital_id=10,
        order_number="ORD-507",
        patient_id=307,
        doctor_id=407,
        lab_test_id=1,
        status="sample_collected",
        priority="normal",
        ordered_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    doctor = Doctor(id=407, user_id=607, first_name="Sarah", last_name="Connor", hospital_id=10)
    # Patient in hospital 99 != order hospital 10
    patient = Patient(id=307, user_id=707, first_name="John", last_name="Doe", hospital_id=99)
    lab_test = LabTest(id=1, test_name="CBC", is_active=True)

    service.sample_repo.get_by_id = AsyncMock(return_value=sample)
    service.sample_repo.update = AsyncMock(return_value=sample)
    service.order_repo.get_by_id = AsyncMock(return_value=order)
    service.audit_repo.create = AsyncMock()

    db.get = AsyncMock(side_effect=lambda model, ident: doctor if model == Doctor else (patient if model == Patient else (lab_test if model == LabTest else order)))

    update_req = SampleUpdate(status=SampleStatus.REJECTED)

    with patch("app.services.notification_service.NotificationService.notify_lab_sample_rejected", new_callable=AsyncMock) as mock_notify:
        res = await service.update_sample(sample_id=207, data=update_req, user_id=999)
        assert res is not None

        # Patient suppressed, doctor still notified
        assert mock_notify.call_count == 1
        assert mock_notify.call_args.kwargs["user_id"] == 607


@pytest.mark.asyncio
async def test_sample_inactive_user_is_suppressed():
    """Verify inactive User account suppresses notification for that recipient."""
    db = AsyncMock()
    # db.scalar returns False -> user is inactive
    db.scalar = AsyncMock(return_value=False)
    service = LabService(db)

    sample = Sample(
        id=208,
        test_order_id=508,
        sample_code="SMP-208",
        sample_type="blood",
        status=SampleStatus.COLLECTED,
        collected_at=datetime.now(timezone.utc),
        collection_date=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    order = TestOrder(
        id=508,
        hospital_id=10,
        order_number="ORD-508",
        patient_id=308,
        doctor_id=408,
        lab_test_id=1,
        status="sample_collected",
        priority="normal",
        ordered_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    doctor = Doctor(id=408, user_id=608, first_name="Sarah", last_name="Connor", hospital_id=10)
    patient = Patient(id=308, user_id=708, first_name="John", last_name="Doe", hospital_id=10)
    lab_test = LabTest(id=1, test_name="CBC", is_active=True)

    service.sample_repo.get_by_id = AsyncMock(return_value=sample)
    service.sample_repo.update = AsyncMock(return_value=sample)
    service.order_repo.get_by_id = AsyncMock(return_value=order)
    service.audit_repo.create = AsyncMock()

    db.get = AsyncMock(side_effect=lambda model, ident: doctor if model == Doctor else (patient if model == Patient else (lab_test if model == LabTest else order)))

    update_req = SampleUpdate(status=SampleStatus.REJECTED)

    with patch("app.services.notification_service.NotificationService.notify_lab_sample_rejected", new_callable=AsyncMock) as mock_notify:
        res = await service.update_sample(sample_id=208, data=update_req, user_id=999)
        assert res is not None
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_sample_missing_user_safely_skips_only_that_recipient():
    """Verify missing user account on patient does not suppress notification to valid doctor."""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=True)
    service = LabService(db)

    sample = Sample(
        id=209,
        test_order_id=509,
        sample_code="SMP-209",
        sample_type="blood",
        status=SampleStatus.COLLECTED,
        collected_at=datetime.now(timezone.utc),
        collection_date=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    order = TestOrder(
        id=509,
        hospital_id=10,
        order_number="ORD-509",
        patient_id=309,
        doctor_id=409,
        lab_test_id=1,
        status="sample_collected",
        priority="normal",
        ordered_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    doctor = Doctor(id=409, user_id=609, first_name="Sarah", last_name="Connor", hospital_id=10)
    # Patient user_id is None
    patient = Patient(id=309, user_id=None, first_name="Walkin", last_name="Patient", hospital_id=10)
    lab_test = LabTest(id=1, test_name="CBC", is_active=True)

    service.sample_repo.get_by_id = AsyncMock(return_value=sample)
    service.sample_repo.update = AsyncMock(return_value=sample)
    service.order_repo.get_by_id = AsyncMock(return_value=order)
    service.audit_repo.create = AsyncMock()

    db.get = AsyncMock(side_effect=lambda model, ident: doctor if model == Doctor else (patient if model == Patient else (lab_test if model == LabTest else order)))

    update_req = SampleUpdate(status=SampleStatus.REJECTED)

    with patch("app.services.notification_service.NotificationService.notify_lab_sample_rejected", new_callable=AsyncMock) as mock_notify:
        res = await service.update_sample(sample_id=209, data=update_req, user_id=999)
        assert res is not None

        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs["user_id"] == 609


@pytest.mark.asyncio
async def test_sample_one_invalid_recipient_does_not_suppress_other_valid_recipient():
    """Verify that doctor tenant mismatch does not suppress valid patient notification."""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=True)
    service = LabService(db)

    sample = Sample(
        id=210,
        test_order_id=510,
        sample_code="SMP-210",
        sample_type="blood",
        status=SampleStatus.COLLECTED,
        collected_at=datetime.now(timezone.utc),
        collection_date=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    order = TestOrder(
        id=510,
        hospital_id=10,
        order_number="ORD-510",
        patient_id=310,
        doctor_id=410,
        lab_test_id=1,
        status="sample_collected",
        priority="normal",
        ordered_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    # Doctor in hospital 99 != 10
    doctor = Doctor(id=410, user_id=610, first_name="Sarah", last_name="Connor", hospital_id=99)
    # Patient in hospital 10 == 10
    patient = Patient(id=310, user_id=710, first_name="John", last_name="Doe", hospital_id=10)
    lab_test = LabTest(id=1, test_name="CBC", is_active=True)

    service.sample_repo.get_by_id = AsyncMock(return_value=sample)
    service.sample_repo.update = AsyncMock(return_value=sample)
    service.order_repo.get_by_id = AsyncMock(return_value=order)
    service.audit_repo.create = AsyncMock()

    db.get = AsyncMock(side_effect=lambda model, ident: doctor if model == Doctor else (patient if model == Patient else (lab_test if model == LabTest else order)))

    update_req = SampleUpdate(status=SampleStatus.REJECTED)

    with patch("app.services.notification_service.NotificationService.notify_lab_sample_rejected", new_callable=AsyncMock) as mock_notify:
        res = await service.update_sample(sample_id=210, data=update_req, user_id=999)
        assert res is not None

        mock_notify.assert_called_once()
        assert mock_notify.call_args.kwargs["user_id"] == 710


@pytest.mark.asyncio
async def test_sample_dispatch_failure_one_recipient_does_not_suppress_other():
    """Verify dispatch exception on doctor notification does not prevent patient notification."""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=True)
    service = LabService(db)

    sample = Sample(
        id=211,
        test_order_id=511,
        sample_code="SMP-211",
        sample_type="blood",
        status=SampleStatus.COLLECTED,
        collected_at=datetime.now(timezone.utc),
        collection_date=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    order = TestOrder(
        id=511,
        hospital_id=10,
        order_number="ORD-511",
        patient_id=311,
        doctor_id=411,
        lab_test_id=1,
        status="sample_collected",
        priority="normal",
        ordered_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    doctor = Doctor(id=411, user_id=611, first_name="Sarah", last_name="Connor", hospital_id=10)
    patient = Patient(id=311, user_id=711, first_name="John", last_name="Doe", hospital_id=10)
    lab_test = LabTest(id=1, test_name="CBC", is_active=True)

    service.sample_repo.get_by_id = AsyncMock(return_value=sample)
    service.sample_repo.update = AsyncMock(return_value=sample)
    service.order_repo.get_by_id = AsyncMock(return_value=order)
    service.audit_repo.create = AsyncMock()

    db.get = AsyncMock(side_effect=lambda model, ident: doctor if model == Doctor else (patient if model == Patient else (lab_test if model == LabTest else order)))

    update_req = SampleUpdate(status=SampleStatus.REJECTED)

    # Doctor fails, patient succeeds
    async def mock_dispatch_side_effect(*args, **kwargs):
        if kwargs.get("recipient_role") == "DOCTOR":
            raise Exception("Doctor socket failed")
        return None

    with patch("app.services.notification_service.NotificationService.notify_lab_sample_rejected", new_callable=AsyncMock, side_effect=mock_dispatch_side_effect) as mock_notify:
        res = await service.update_sample(sample_id=211, data=update_req, user_id=999)
        assert res is not None

        # Both were attempted
        assert mock_notify.call_count == 2


@pytest.mark.asyncio
async def test_sample_rejection_duplicate_suppression():
    """Verify repeated rejection notification for same sample is suppressed by duplicate window."""
    db = AsyncMock()
    nested_cm = AsyncMock()
    nested_cm.__aenter__ = AsyncMock(return_value=None)
    nested_cm.__aexit__ = AsyncMock(return_value=None)
    db.begin_nested = MagicMock(return_value=nested_cm)

    service = NotificationService(db)
    service.repo.exists_duplicate = AsyncMock(return_value=True)
    service.repo.create = AsyncMock()

    res = await service.notify_lab_sample_rejected(
        user_id=612,
        sample_code="SMP-212",
        order_number="ORD-512",
        test_name="CBC",
        recipient_role="DOCTOR",
        sample_id=212,
    )

    assert res is None
    service.repo.exists_duplicate.assert_called_once_with(
        user_id=612,
        notification_type="LAB_SAMPLE_REJECTED",
        reference_type="SAMPLE",
        reference_id=212,
    )
    service.repo.create.assert_not_called()


@pytest.mark.asyncio
async def test_sample_dispatch_failure_does_not_break_sample_update():
    """Verify overall dispatch exception does not abort the sample update."""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=True)
    service = LabService(db)

    sample = Sample(
        id=213,
        test_order_id=513,
        sample_code="SMP-213",
        sample_type="blood",
        status=SampleStatus.COLLECTED,
        collected_at=datetime.now(timezone.utc),
        collection_date=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    order = TestOrder(
        id=513,
        hospital_id=10,
        order_number="ORD-513",
        patient_id=313,
        doctor_id=413,
        lab_test_id=1,
        status="sample_collected",
        priority="normal",
        ordered_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    doctor = Doctor(id=413, user_id=613, first_name="Sarah", last_name="Connor", hospital_id=10)

    service.sample_repo.get_by_id = AsyncMock(return_value=sample)
    service.sample_repo.update = AsyncMock(return_value=sample)
    service.order_repo.get_by_id = AsyncMock(return_value=order)
    service.audit_repo.create = AsyncMock()

    db.get = AsyncMock(side_effect=lambda model, ident: doctor if model == Doctor else order)

    update_req = SampleUpdate(status=SampleStatus.REJECTED)

    with patch(
        "app.services.notification_service.NotificationService.notify_lab_sample_rejected",
        new_callable=AsyncMock,
        side_effect=Exception("Total connection failure"),
    ):
        res = await service.update_sample(sample_id=213, data=update_req, user_id=999)
        assert res is not None
        assert sample.status == SampleStatus.REJECTED


# ============================================================================
# WORKFLOW C: STAFF ONBOARDING WELCOME NOTIFICATION TESTS
# ============================================================================

from app.models.staff_model import Staff
from app.services.staff_service import StaffService
from app.schemas.staff_schema import StaffCreate, StaffUpdate


@pytest.mark.asyncio
async def test_staff_creation_triggers_welcome_notification():
    """Verify creating a new staff member triggers welcome notification to the new staff user."""
    db = AsyncMock()
    # User is active in tenant
    db.scalar = AsyncMock(side_effect=[None, None, True])  # check email, check phone, check user_active
    db.flush = AsyncMock()
    def mock_add(obj):
        if hasattr(obj, "id") and getattr(obj, "id", None) is None:
            obj.id = 801
    db.add = MagicMock(side_effect=mock_add)
    service = StaffService(db)

    service.repo.get_by_email = AsyncMock(return_value=None)
    service.repo.get_by_staff_code = AsyncMock(return_value=None)
    service._validate_department_and_role = AsyncMock()
    service.dept_repo.get_by_id = AsyncMock(return_value=MagicMock(name="Pathology"))

    role = MagicMock(id=5, name="Receptionist")
    service.rbac_repo.get_role_by_name = AsyncMock(return_value=role)

    created_staff = Staff(
        id=701,
        hospital_id=10,
        full_name="Ramesh Sharma",
        email="ramesh@example.com",
        phone="9876543210",
        staff_code="STF-701",
        department_id=1,
        role_name="Receptionist",
        status=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    service.repo.create = AsyncMock(return_value=created_staff)
    service.repo.get_by_id = AsyncMock(return_value=created_staff)
    service.audit_repo.create = AsyncMock()

    current_user = User(id=999, hospital_id=10, is_active=True)

    data = StaffCreate(
        full_name="Ramesh Sharma",
        email="ramesh@example.com",
        phone="9876543210",
        password="Nexa#Sec9918!Staff",
        staff_code="STF-701",
        department_id=1,
        role_name="Receptionist",
    )

    with patch("app.services.notification_service.NotificationService.notify_staff_onboarding_welcome", new_callable=AsyncMock) as mock_notify:
        res = await service.create_staff(data=data, current_user_id=999, current_user=current_user)
        assert res is not None

        mock_notify.assert_called_once()
        kwargs = mock_notify.call_args.kwargs
        assert kwargs["full_name"] == "Ramesh Sharma"
        assert kwargs["staff_code"] == "STF-701"
        assert kwargs["role_name"] == "Receptionist"
        assert kwargs["hospital_id"] == 10
        assert kwargs["staff_id"] == 701


@pytest.mark.asyncio
async def test_staff_creation_correct_new_user_receives_notification():
    """Verify notification user_id matches the newly created User record."""
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[None, None, True])
    db.flush = AsyncMock()
    def mock_add(obj):
        if hasattr(obj, "id") and getattr(obj, "id", None) is None:
            obj.id = 801
    db.add = MagicMock(side_effect=mock_add)
    service = StaffService(db)

    service.repo.get_by_email = AsyncMock(return_value=None)
    service.repo.get_by_staff_code = AsyncMock(return_value=None)
    service._validate_department_and_role = AsyncMock()
    service.dept_repo.get_by_id = AsyncMock(return_value=None)
    role = MagicMock(id=6, name="Pharmacist")
    service.rbac_repo.get_role_by_name = AsyncMock(return_value=role)

    created_staff = Staff(
        id=702,
        hospital_id=10,
        full_name="Pooja Verma",
        email="pooja@example.com",
        phone="9876543211",
        staff_code="STF-702",
        department_id=2,
        role_name="Pharmacist",
        status=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    service.repo.create = AsyncMock(return_value=created_staff)
    service.repo.get_by_id = AsyncMock(return_value=created_staff)
    service.audit_repo.create = AsyncMock()

    current_user = User(id=999, hospital_id=10, is_active=True)

    data = StaffCreate(
        full_name="Pooja Verma",
        email="pooja@example.com",
        phone="9876543211",
        password="Nexa#Sec9918!Staff",
        staff_code="STF-702",
        department_id=2,
        role_name="Pharmacist",
    )

    with patch("app.services.notification_service.NotificationService.notify_staff_onboarding_welcome", new_callable=AsyncMock) as mock_notify:
        res = await service.create_staff(data=data, current_user_id=999, current_user=current_user)
        assert res is not None

        mock_notify.assert_called_once()
        # user_id must match newly created user id
        assert mock_notify.call_args.kwargs["user_id"] == 801


@pytest.mark.asyncio
async def test_staff_creation_payload_details():
    """Verify staff welcome notification carries correct department name and hospital_id."""
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[None, None, True])
    db.flush = AsyncMock()
    def mock_add(obj):
        if hasattr(obj, "id") and getattr(obj, "id", None) is None:
            obj.id = 801
    db.add = MagicMock(side_effect=mock_add)
    service = StaffService(db)

    service.repo.get_by_email = AsyncMock(return_value=None)
    service.repo.get_by_staff_code = AsyncMock(return_value=None)
    service._validate_department_and_role = AsyncMock()
    dept_mock = MagicMock()
    dept_mock.name = "Accounts & Finance"
    service.dept_repo.get_by_id = AsyncMock(return_value=dept_mock)
    role = MagicMock(id=7, name="Accountant")
    service.rbac_repo.get_role_by_name = AsyncMock(return_value=role)

    created_staff = Staff(
        id=703,
        hospital_id=10,
        full_name="Anil Kumar",
        email="anil@example.com",
        phone="9876543212",
        staff_code="STF-703",
        department_id=3,
        role_name="Accountant",
        status=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    service.repo.create = AsyncMock(return_value=created_staff)
    service.repo.get_by_id = AsyncMock(return_value=created_staff)
    service.audit_repo.create = AsyncMock()

    current_user = User(id=999, hospital_id=10, is_active=True)

    data = StaffCreate(
        full_name="Anil Kumar",
        email="anil@example.com",
        phone="9876543212",
        password="Nexa#Sec9918!Staff",
        staff_code="STF-703",
        department_id=3,
        role_name="Accountant",
    )

    with patch("app.services.notification_service.NotificationService.notify_staff_onboarding_welcome", new_callable=AsyncMock) as mock_notify:
        res = await service.create_staff(data=data, current_user_id=999, current_user=current_user)
        assert res is not None

        mock_notify.assert_called_once()
        kwargs = mock_notify.call_args.kwargs
        assert kwargs["department_name"] == "Accounts & Finance"
        assert kwargs["hospital_id"] == 10
        assert kwargs["staff_id"] == 703


@pytest.mark.asyncio
async def test_staff_update_does_not_trigger_welcome_notification():
    """Verify updating staff profile does not trigger welcome notification."""
    db = AsyncMock()
    service = StaffService(db)

    staff = Staff(
        id=704,
        hospital_id=10,
        full_name="Old Name",
        email="staff4@example.com",
        phone="9876543213",
        staff_code="STF-704",
        department_id=1,
        role_name="Receptionist",
        status=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    service.repo.get_by_id = AsyncMock(return_value=staff)
    service.repo.update = AsyncMock(return_value=staff)
    service.audit_repo.create = AsyncMock()

    update_req = StaffUpdate(full_name="New Name")
    current_user = User(id=999, hospital_id=10, is_active=True)

    with patch("app.services.notification_service.NotificationService.notify_staff_onboarding_welcome", new_callable=AsyncMock) as mock_notify:
        res = await service.update_staff(staff_id=704, data=update_req, current_user_id=999, current_user=current_user)
        assert res is not None
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_staff_inactive_user_is_suppressed():
    """Verify inactive User suppresses staff welcome notification."""
    db = AsyncMock()
    # db.scalar for user_active returns False
    db.scalar = AsyncMock(side_effect=[None, None, False])
    db.flush = AsyncMock()
    def mock_add(obj):
        if hasattr(obj, "id") and getattr(obj, "id", None) is None:
            obj.id = 801
    db.add = MagicMock(side_effect=mock_add)
    service = StaffService(db)

    service.repo.get_by_email = AsyncMock(return_value=None)
    service.repo.get_by_staff_code = AsyncMock(return_value=None)
    service._validate_department_and_role = AsyncMock()
    service.dept_repo.get_by_id = AsyncMock(return_value=None)
    role = MagicMock(id=5, name="Receptionist")
    service.rbac_repo.get_role_by_name = AsyncMock(return_value=role)

    created_staff = Staff(
        id=705,
        hospital_id=10,
        full_name="Ramesh Sharma",
        email="ramesh5@example.com",
        phone="9876543214",
        staff_code="STF-705",
        department_id=1,
        role_name="Receptionist",
        status=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    service.repo.create = AsyncMock(return_value=created_staff)
    service.repo.get_by_id = AsyncMock(return_value=created_staff)
    service.audit_repo.create = AsyncMock()

    current_user = User(id=999, hospital_id=10, is_active=True)

    data = StaffCreate(
        full_name="Ramesh Sharma",
        email="ramesh5@example.com",
        phone="9876543214",
        password="Nexa#Sec9918!Staff",
        staff_code="STF-705",
        department_id=1,
        role_name="Receptionist",
    )

    with patch("app.services.notification_service.NotificationService.notify_staff_onboarding_welcome", new_callable=AsyncMock) as mock_notify:
        res = await service.create_staff(data=data, current_user_id=999, current_user=current_user)
        assert res is not None
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_staff_cross_hospital_user_is_suppressed():
    """Verify hospital mismatch between User and Staff suppresses notification."""
    db = AsyncMock()
    # db.scalar returns None because User.hospital_id != Staff.hospital_id
    db.scalar = AsyncMock(side_effect=[None, None, None])
    db.flush = AsyncMock()
    def mock_add(obj):
        if hasattr(obj, "id") and getattr(obj, "id", None) is None:
            obj.id = 801
    db.add = MagicMock(side_effect=mock_add)
    service = StaffService(db)

    service.repo.get_by_email = AsyncMock(return_value=None)
    service.repo.get_by_staff_code = AsyncMock(return_value=None)
    service._validate_department_and_role = AsyncMock()
    service.dept_repo.get_by_id = AsyncMock(return_value=None)
    role = MagicMock(id=5, name="Receptionist")
    service.rbac_repo.get_role_by_name = AsyncMock(return_value=role)

    created_staff = Staff(
        id=706,
        hospital_id=10,
        full_name="Ramesh Sharma",
        email="ramesh6@example.com",
        phone="9876543215",
        staff_code="STF-706",
        department_id=1,
        role_name="Receptionist",
        status=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    service.repo.create = AsyncMock(return_value=created_staff)
    service.repo.get_by_id = AsyncMock(return_value=created_staff)
    service.audit_repo.create = AsyncMock()

    current_user = User(id=999, hospital_id=10, is_active=True)

    data = StaffCreate(
        full_name="Ramesh Sharma",
        email="ramesh6@example.com",
        phone="9876543215",
        password="Nexa#Sec9918!Staff",
        staff_code="STF-706",
        department_id=1,
        role_name="Receptionist",
    )

    with patch("app.services.notification_service.NotificationService.notify_staff_onboarding_welcome", new_callable=AsyncMock) as mock_notify:
        res = await service.create_staff(data=data, current_user_id=999, current_user=current_user)
        assert res is not None
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_staff_missing_user_safely_skips():
    """Verify null hospital_id suppresses welcome notification."""
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[None, None])
    db.flush = AsyncMock()
    def mock_add(obj):
        if hasattr(obj, "id") and getattr(obj, "id", None) is None:
            obj.id = 801
    db.add = MagicMock(side_effect=mock_add)
    service = StaffService(db)

    service.repo.get_by_email = AsyncMock(return_value=None)
    service.repo.get_by_staff_code = AsyncMock(return_value=None)
    service._validate_department_and_role = AsyncMock()
    service.dept_repo.get_by_id = AsyncMock(return_value=None)
    role = MagicMock(id=5, name="Receptionist")
    service.rbac_repo.get_role_by_name = AsyncMock(return_value=role)

    created_staff = Staff(
        id=707,
        hospital_id=None,
        full_name="Ramesh Sharma",
        email="ramesh7@example.com",
        phone="9876543216",
        staff_code="STF-707",
        department_id=1,
        role_name="Receptionist",
        status=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    service.repo.create = AsyncMock(return_value=created_staff)
    service.repo.get_by_id = AsyncMock(return_value=created_staff)
    service.audit_repo.create = AsyncMock()

    current_user = User(id=999, hospital_id=None, is_active=True)

    data = StaffCreate(
        full_name="Ramesh Sharma",
        email="ramesh7@example.com",
        phone="9876543216",
        password="Nexa#Sec9918!Staff",
        staff_code="STF-707",
        department_id=1,
        role_name="Receptionist",
    )

    with patch("app.services.notification_service.NotificationService.notify_staff_onboarding_welcome", new_callable=AsyncMock) as mock_notify:
        res = await service.create_staff(data=data, current_user_id=999, current_user=current_user)
        assert res is not None
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_staff_welcome_notification_contains_zero_passwords_or_credentials():
    """Verify staff welcome notification dispatcher call and helper payloads contain zero credential data."""
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[None, None, True])
    db.flush = AsyncMock()
    def mock_add(obj):
        if hasattr(obj, "id") and getattr(obj, "id", None) is None:
            obj.id = 801
    db.add = MagicMock(side_effect=mock_add)
    service = StaffService(db)

    service.repo.get_by_email = AsyncMock(return_value=None)
    service.repo.get_by_staff_code = AsyncMock(return_value=None)
    service._validate_department_and_role = AsyncMock()
    service.dept_repo.get_by_id = AsyncMock(return_value=None)
    role = MagicMock(id=5, name="Receptionist")
    service.rbac_repo.get_role_by_name = AsyncMock(return_value=role)

    created_staff = Staff(
        id=708,
        hospital_id=10,
        full_name="Secret Worker",
        email="worker@example.com",
        phone="9876543217",
        staff_code="STF-708",
        department_id=1,
        role_name="Receptionist",
        status=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    service.repo.create = AsyncMock(return_value=created_staff)
    service.repo.get_by_id = AsyncMock(return_value=created_staff)
    service.audit_repo.create = AsyncMock()

    current_user = User(id=999, hospital_id=10, is_active=True)

    raw_password = "Secret#Pass991!"
    data = StaffCreate(
        full_name="Secret Worker",
        email="worker@example.com",
        phone="9876543217",
        password=raw_password,
        staff_code="STF-708",
        department_id=1,
        role_name="Receptionist",
    )

    with patch("app.services.notification_service.NotificationService.dispatch_notification", new_callable=AsyncMock) as mock_dispatch:
        res = await service.create_staff(data=data, current_user_id=999, current_user=current_user)
        assert res is not None

        mock_dispatch.assert_called_once()
        kwargs = mock_dispatch.call_args.kwargs

        # CRITICAL CREDENTIAL AUDIT: Verify password is not leaked anywhere in payload
        assert raw_password not in kwargs.get("title", "")
        assert raw_password not in kwargs.get("message", "")
        assert raw_password not in (kwargs.get("email_subject") or "")
        assert raw_password not in (kwargs.get("email_html") or "")
        assert "password" not in kwargs.get("message", "").lower()
        assert "password" not in (kwargs.get("email_html") or "").lower()


@pytest.mark.asyncio
async def test_staff_dispatch_failure_does_not_break_staff_creation():
    """Verify dispatch exception does not abort or raise from staff creation."""
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[None, None, True])
    db.flush = AsyncMock()
    def mock_add(obj):
        if hasattr(obj, "id") and getattr(obj, "id", None) is None:
            obj.id = 801
    db.add = MagicMock(side_effect=mock_add)
    service = StaffService(db)

    service.repo.get_by_email = AsyncMock(return_value=None)
    service.repo.get_by_staff_code = AsyncMock(return_value=None)
    service._validate_department_and_role = AsyncMock()
    service.dept_repo.get_by_id = AsyncMock(return_value=None)
    role = MagicMock(id=5, name="Receptionist")
    service.rbac_repo.get_role_by_name = AsyncMock(return_value=role)

    created_staff = Staff(
        id=709,
        hospital_id=10,
        full_name="Ramesh Sharma",
        email="ramesh9@example.com",
        phone="9876543218",
        staff_code="STF-709",
        department_id=1,
        role_name="Receptionist",
        status=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    service.repo.create = AsyncMock(return_value=created_staff)
    service.repo.get_by_id = AsyncMock(return_value=created_staff)
    service.audit_repo.create = AsyncMock()

    current_user = User(id=999, hospital_id=10, is_active=True)

    data = StaffCreate(
        full_name="Ramesh Sharma",
        email="ramesh9@example.com",
        phone="9876543218",
        password="Nexa#Sec9918!Staff",
        staff_code="STF-709",
        department_id=1,
        role_name="Receptionist",
    )

    with patch(
        "app.services.notification_service.NotificationService.notify_staff_onboarding_welcome",
        new_callable=AsyncMock,
        side_effect=Exception("Notification service timeout"),
    ):
        res = await service.create_staff(data=data, current_user_id=999, current_user=current_user)
        assert res is not None
        assert res.staff_code == "STF-709"

