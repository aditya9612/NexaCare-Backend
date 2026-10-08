from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from pydantic import ValidationError

from app.models.pharmacy_model import Medicine, Prescription, PrescriptionItem
from app.models.doctor_model import Doctor
from app.models.patient_model import Patient
from app.models.appointment_model import Appointment
from app.schemas.pharmacy_schema import (
    PrescriptionCreate,
    PrescriptionItemCreate,
    PrescriptionItemResponse,
    VALID_MEAL_TIMINGS,
    VALID_TIME_OF_DAY,
)
from app.services.pharmacy_service import PharmacyService


def build_mock_medicine(med_id: int = 1, stock: int = 50) -> Medicine:
    med = Medicine(
        id=med_id,
        name=f"Paracetamol {med_id}",
        sku=f"MED-{med_id}",
        stock_quantity=stock,
        reserved_quantity=0,
        is_active=True,
    )
    return med


# 1. Test Valid Meal Timings
@pytest.mark.parametrize("input_val, expected_val", [
    ("Before Meal", "Before Meal"),
    ("before meal", "Before Meal"),
    ("After Meal", "After Meal"),
    ("AFTER MEAL", "After Meal"),
    ("With Meal", "With Meal"),
    ("Empty Stomach", "Empty Stomach"),
    ("empty stomach", "Empty Stomach"),
    ("Anytime", "Anytime"),
    ("anytime", "Anytime"),
])
def test_prescription_item_valid_meal_timings(input_val, expected_val):
    item = PrescriptionItemCreate(
        medicine_id=1,
        dosage="500mg",
        frequency="1-0-1",
        duration_days=5,
        quantity=10,
        meal_timing=input_val,
    )
    assert item.meal_timing == expected_val


# 2. Test Valid Time Of Day
@pytest.mark.parametrize("input_val, expected_val", [
    ("Morning", "Morning"),
    ("morning", "Morning"),
    ("Afternoon", "Afternoon"),
    ("AFTERNOON", "Afternoon"),
    ("Evening", "Evening"),
    ("Night", "Night"),
    ("night", "Night"),
    ("Bedtime", "Bedtime"),
    ("bedtime", "Bedtime"),
])
def test_prescription_item_valid_time_of_day(input_val, expected_val):
    item = PrescriptionItemCreate(
        medicine_id=1,
        dosage="500mg",
        frequency="1-0-1",
        duration_days=5,
        quantity=10,
        time_of_day=input_val,
    )
    assert item.time_of_day == expected_val


# 3. Test Invalid Meal Timing raises ValidationError (422)
@pytest.mark.parametrize("invalid_val", [
    "Midnight Snack",
    "During Lunch",
    "Random Timing",
    "Invalid",
])
def test_prescription_item_invalid_meal_timing_raises_validation_error(invalid_val):
    with pytest.raises(ValidationError) as exc_info:
        PrescriptionItemCreate(
            medicine_id=1,
            dosage="500mg",
            frequency="1-0-1",
            duration_days=5,
            quantity=10,
            meal_timing=invalid_val,
        )
    assert "Invalid meal_timing" in str(exc_info.value)


# 4. Test Invalid Time Of Day raises ValidationError (422)
@pytest.mark.parametrize("invalid_val", [
    "Dawn",
    "Midnight",
    "Noon",
    "RandomSlot",
])
def test_prescription_item_invalid_time_of_day_raises_validation_error(invalid_val):
    with pytest.raises(ValidationError) as exc_info:
        PrescriptionItemCreate(
            medicine_id=1,
            dosage="500mg",
            frequency="1-0-1",
            duration_days=5,
            quantity=10,
            time_of_day=invalid_val,
        )
    assert "Invalid time_of_day" in str(exc_info.value)


# 5. Test Prescription Creation with both fields present
@pytest.mark.asyncio
async def test_create_prescription_with_both_meal_timing_and_time_of_day():
    mock_db = AsyncMock()
    service = PharmacyService(mock_db)

    # Mock doctor, patient, appointment existence
    mock_doc = Doctor(id=1, user_id=10, first_name="John", last_name="Doe")
    mock_pat = Patient(id=1, user_id=20, first_name="Alice", last_name="Smith", patient_code="P-101")
    mock_appt = Appointment(id=1, patient_id=1, doctor_id=1, appointment_date=date.today(), appointment_status="confirmed")
    mock_med = build_mock_medicine(med_id=1, stock=50)

    service.medicine_repo.get_by_id_for_update = AsyncMock(return_value=mock_med)
    service.medicine_repo.update_reserved_stock = AsyncMock()
    service.batch_repo.get_available_batches_fefo = AsyncMock(return_value=[])

    def mock_db_scalar(stmt):
        return mock_doc

    mock_db.scalar = AsyncMock(side_effect=[mock_doc, mock_pat, None]) # doctor, patient, duplicate check
    mock_res_appt = MagicMock()
    mock_res_appt.scalar_one_or_none.return_value = mock_appt
    mock_db.execute.return_value = mock_res_appt

    created_prescription = Prescription(
        id=101,
        patient_id=1,
        doctor_id=1,
        appointment_id=1,
        prescription_number="RX-TEST-001",
        status="pending",
        created_at=datetime.utcnow(),
    )
    created_items = [
        PrescriptionItem(
            id=1,
            prescription_id=101,
            medicine_id=1,
            dosage="500mg",
            frequency="1-0-1",
            duration_days=5,
            quantity=10,
            dispensed_quantity=0,
            meal_timing="After Meal",
            time_of_day="Morning",
        )
    ]
    created_prescription.items = created_items

    service.prescription_repo.create = AsyncMock(return_value=created_prescription)
    service.prescription_repo.get_by_id = AsyncMock(return_value=created_prescription)
    service.audit_repo.create = AsyncMock()

    payload = PrescriptionCreate(
        patient_id=1,
        doctor_id=1,
        appointment_id=1,
        items=[
            PrescriptionItemCreate(
                medicine_id=1,
                dosage="500mg",
                frequency="1-0-1",
                duration_days=5,
                quantity=10,
                meal_timing="After Meal",
                time_of_day="Morning",
            )
        ]
    )

    response = await service.create_prescription(payload, user_id=1)

    assert response.id == 101
    assert len(response.items) == 1
    assert response.items[0].meal_timing == "After Meal"
    assert response.items[0].time_of_day == "Morning"


# 6. Test Backward Compatibility: Creation without optional fields defaults to None
@pytest.mark.asyncio
async def test_create_prescription_without_optional_fields_backward_compatibility():
    mock_db = AsyncMock()
    service = PharmacyService(mock_db)

    mock_doc = Doctor(id=1, user_id=10, first_name="John", last_name="Doe")
    mock_pat = Patient(id=1, user_id=20, first_name="Alice", last_name="Smith", patient_code="P-101")
    mock_appt = Appointment(id=1, patient_id=1, doctor_id=1, appointment_date=date.today(), appointment_status="confirmed")
    mock_med = build_mock_medicine(med_id=1, stock=50)

    service.medicine_repo.get_by_id_for_update = AsyncMock(return_value=mock_med)
    service.medicine_repo.update_reserved_stock = AsyncMock()
    service.batch_repo.get_available_batches_fefo = AsyncMock(return_value=[])

    mock_db.scalar = AsyncMock(side_effect=[mock_doc, mock_pat, None])
    mock_res_appt = MagicMock()
    mock_res_appt.scalar_one_or_none.return_value = mock_appt
    mock_db.execute.return_value = mock_res_appt

    created_prescription = Prescription(
        id=102,
        patient_id=1,
        doctor_id=1,
        appointment_id=1,
        prescription_number="RX-TEST-002",
        status="pending",
        created_at=datetime.utcnow(),
    )
    created_items = [
        PrescriptionItem(
            id=2,
            prescription_id=102,
            medicine_id=1,
            dosage="500mg",
            frequency="1-0-1",
            duration_days=5,
            quantity=10,
            dispensed_quantity=0,
            meal_timing=None,
            time_of_day=None,
        )
    ]
    created_prescription.items = created_items

    service.prescription_repo.create = AsyncMock(return_value=created_prescription)
    service.prescription_repo.get_by_id = AsyncMock(return_value=created_prescription)
    service.audit_repo.create = AsyncMock()

    payload = PrescriptionCreate(
        patient_id=1,
        doctor_id=1,
        appointment_id=1,
        items=[
            PrescriptionItemCreate(
                medicine_id=1,
                dosage="500mg",
                frequency="1-0-1",
                duration_days=5,
                quantity=10,
            )
        ]
    )

    response = await service.create_prescription(payload, user_id=1)

    assert response.id == 102
    assert len(response.items) == 1
    assert response.items[0].meal_timing is None
    assert response.items[0].time_of_day is None
