from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.core.exceptions import BadRequestException, NotFoundException
from app.models.pharmacy_model import Medicine, MedicineBatch, Prescription, PrescriptionItem
from app.schemas.pharmacy_schema import (
    PrescriptionDispenseRequest,
    PrescriptionItemCreate,
    PrescriptionStatusUpdate,
    PrescriptionUpdate,
)
from app.services.pharmacy_service import PharmacyService


def build_medicine(
    med_id: int = 1,
    name: str = "Paracetamol 500mg",
    stock: int = 150,
    reserved: int = 0,
    hospital_id: int = 1,
    unit_price: float = 10.0,
    expiry_date: date | None = None,
) -> Medicine:
    return Medicine(
        id=med_id,
        name=name,
        sku=f"MED-{med_id}",
        hospital_id=hospital_id,
        stock_quantity=stock,
        reserved_quantity=reserved,
        unit_price=unit_price,
        expiry_date=expiry_date or date(2030, 1, 1),
        is_active=True,
    )


def build_prescription_item(
    item_id: int = 1,
    prescription_id: int = 3,
    medicine_id: int = 40,
    quantity: int = 5,
    dispensed_quantity: int = 0,
    duration_days: int = 5,
    dosage: str = "500mg",
    frequency: str = "1-0-1",
    batch_number: str | None = None,
) -> PrescriptionItem:
    return PrescriptionItem(
        id=item_id,
        prescription_id=prescription_id,
        medicine_id=medicine_id,
        dosage=dosage,
        frequency=frequency,
        duration_days=duration_days,
        quantity=quantity,
        dispensed_quantity=dispensed_quantity,
        batch_number=batch_number,
    )


def build_prescription(
    prescription_id: int = 3,
    patient_id: int = 10,
    doctor_id: int = 20,
    status: str = "pending",
    items: list[PrescriptionItem] | None = None,
    hospital_id: int = 1,
) -> Prescription:
    rx = Prescription(
        id=prescription_id,
        patient_id=patient_id,
        doctor_id=doctor_id,
        prescription_number=f"RX-{prescription_id:04d}",
        status=status,
        hospital_id=hospital_id,
        created_at=datetime.utcnow(),
    )
    rx.items = items or []
    return rx


@pytest.fixture
def mock_service():
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=None)
    service = PharmacyService(mock_db)
    service.audit_repo.create = AsyncMock()
    service._create_invoice_internal = AsyncMock(return_value={"invoice_number": "PHR-001"})
    return service


# =====================================================================
# 1. Dispensing when sufficient stock is properly reserved
# =====================================================================
@pytest.mark.asyncio
async def test_dispense_prescription_properly_reserved(mock_service):
    med = build_medicine(med_id=40, stock=150, reserved=5)
    item = build_prescription_item(item_id=1, prescription_id=3, medicine_id=40, quantity=5)
    rx = build_prescription(prescription_id=3, items=[item])

    mock_service.prescription_repo.get_by_id = AsyncMock(return_value=rx)
    mock_service.medicine_repo.get_by_id_for_update = AsyncMock(return_value=med)
    mock_service.medicine_repo.update_reserved_stock = AsyncMock()
    mock_service.medicine_repo.update_stock = AsyncMock()
    mock_service.prescription_repo.update = AsyncMock()

    request_data = PrescriptionDispenseRequest(payment_mode="Cash", payment_status="paid")
    result = await mock_service.dispense_prescription(3, user_id=1, data=request_data)

    # Should release reservation directly (-5) without needing reconciliation (+5)
    mock_service.medicine_repo.update_reserved_stock.assert_called_once_with(40, -5)
    mock_service.medicine_repo.update_stock.assert_called_once_with(40, -5)
    assert item.dispensed_quantity == 5
    assert rx.status == "completed"
    assert rx.dispensed_at is not None
    assert result["invoice"] == {"invoice_number": "PHR-001"}


# =====================================================================
# 2. Dispensing when reservation is missing (Prescription ID 3 scenario)
# =====================================================================
@pytest.mark.asyncio
async def test_dispense_prescription_missing_reservation_reconciles_safely(mock_service):
    # Prescription 3: required 5, physical stock 150, reserved stock 0
    med = build_medicine(med_id=40, stock=150, reserved=0)
    item = build_prescription_item(item_id=1, prescription_id=3, medicine_id=40, quantity=5)
    rx = build_prescription(prescription_id=3, items=[item])

    mock_service.prescription_repo.get_by_id = AsyncMock(return_value=rx)
    mock_service.medicine_repo.get_by_id_for_update = AsyncMock(return_value=med)
    mock_service.medicine_repo.update_reserved_stock = AsyncMock()
    mock_service.medicine_repo.update_stock = AsyncMock()
    mock_service.prescription_repo.update = AsyncMock()

    request_data = PrescriptionDispenseRequest(payment_mode="Cash", payment_status="paid")
    result = await mock_service.dispense_prescription(3, user_id=1, data=request_data)

    # Step 1: Reconciles missing reservation: update_reserved_stock(40, 5)
    # Step 2: Releases reservation: update_reserved_stock(40, -5)
    actual_calls = [call.args for call in mock_service.medicine_repo.update_reserved_stock.call_args_list]
    assert actual_calls == [(40, 5), (40, -5)]

    # Step 3: Physical stock deducted
    mock_service.medicine_repo.update_stock.assert_called_once_with(40, -5)
    assert item.dispensed_quantity == 5
    assert rx.status == "completed"


# =====================================================================
# 3. Dispensing when reservation is missing BUT unreserved stock is insufficient
# =====================================================================
@pytest.mark.asyncio
async def test_dispense_prescription_missing_reservation_blocked_if_unreserved_stock_insufficient(mock_service):
    # Total stock 5, already reserved = 2 (so unreserved available = 3).
    # Prescription item needs 5. Missing reservation needed = 5 - 2 = 3.
    # But wait: if stock is 4, reserved is 2 -> unreserved available = 2.
    # Missing reservation needed = 5 - 2 = 3. Available (2) < Missing (3).
    med = build_medicine(med_id=40, stock=4, reserved=2)
    item = build_prescription_item(item_id=1, prescription_id=3, medicine_id=40, quantity=5)
    rx = build_prescription(prescription_id=3, items=[item])

    mock_service.prescription_repo.get_by_id = AsyncMock(return_value=rx)
    mock_service.medicine_repo.get_by_id_for_update = AsyncMock(return_value=med)
    mock_service.medicine_repo.update_reserved_stock = AsyncMock()
    mock_service.medicine_repo.update_stock = AsyncMock()

    request_data = PrescriptionDispenseRequest(payment_mode="Cash", payment_status="paid")
    with pytest.raises(BadRequestException) as exc_info:
        await mock_service.dispense_prescription(3, user_id=1, data=request_data)

    assert "Insufficient physical stock" in str(exc_info.value) or "Insufficient available stock to reserve and dispense" in str(exc_info.value)
    # Ensure no stock or reservation was modified
    mock_service.medicine_repo.update_reserved_stock.assert_not_called()
    mock_service.medicine_repo.update_stock.assert_not_called()


# =====================================================================
# 4. Dispensing when physical stock is insufficient
# =====================================================================
@pytest.mark.asyncio
async def test_dispense_prescription_insufficient_physical_stock(mock_service):
    # Total physical stock is only 3, requested is 5
    med = build_medicine(med_id=40, stock=3, reserved=0)
    item = build_prescription_item(item_id=1, prescription_id=3, medicine_id=40, quantity=5)
    rx = build_prescription(prescription_id=3, items=[item])

    mock_service.prescription_repo.get_by_id = AsyncMock(return_value=rx)
    mock_service.medicine_repo.get_by_id_for_update = AsyncMock(return_value=med)
    mock_service.medicine_repo.update_reserved_stock = AsyncMock()
    mock_service.medicine_repo.update_stock = AsyncMock()

    request_data = PrescriptionDispenseRequest(payment_mode="Cash", payment_status="paid")
    with pytest.raises(BadRequestException) as exc_info:
        await mock_service.dispense_prescription(3, user_id=1, data=request_data)

    assert "Insufficient physical stock" in str(exc_info.value)
    mock_service.medicine_repo.update_reserved_stock.assert_not_called()
    mock_service.medicine_repo.update_stock.assert_not_called()


# =====================================================================
# 5. Multi-item pre-validation atomicity
# =====================================================================
@pytest.mark.asyncio
async def test_dispense_prescription_multi_item_atomicity(mock_service):
    # Item 1 has sufficient stock, but Item 2 fails.
    # Neither Item 1 nor Item 2 should have stock deducted or reservations changed.
    med1 = build_medicine(med_id=10, stock=50, reserved=2)
    med2 = build_medicine(med_id=20, stock=1, reserved=0)

    item1 = build_prescription_item(item_id=1, prescription_id=3, medicine_id=10, quantity=2)
    item2 = build_prescription_item(item_id=2, prescription_id=3, medicine_id=20, quantity=10)
    rx = build_prescription(prescription_id=3, items=[item1, item2])

    mock_service.prescription_repo.get_by_id = AsyncMock(return_value=rx)
    mock_service.medicine_repo.get_by_id_for_update = AsyncMock(side_effect=[med1, med2])
    mock_service.medicine_repo.update_reserved_stock = AsyncMock()
    mock_service.medicine_repo.update_stock = AsyncMock()

    request_data = PrescriptionDispenseRequest(payment_mode="Cash", payment_status="paid")
    with pytest.raises(BadRequestException) as exc_info:
        await mock_service.dispense_prescription(3, user_id=1, data=request_data)

    assert "Insufficient physical stock" in str(exc_info.value)
    # Neither medicine was modified
    mock_service.medicine_repo.update_reserved_stock.assert_not_called()
    mock_service.medicine_repo.update_stock.assert_not_called()


# =====================================================================
# 6. Reservation integrity during prescription update
# =====================================================================
@pytest.mark.asyncio
async def test_update_prescription_maintains_reservation_integrity(mock_service):
    # Old item: Med 10, quantity 3 (reserved 3)
    # New item: Med 20, quantity 4 (available 20, reserved 0)
    med_old = build_medicine(med_id=10, stock=50, reserved=3)
    med_new = build_medicine(med_id=20, stock=20, reserved=0)

    old_item = build_prescription_item(item_id=1, prescription_id=5, medicine_id=10, quantity=3)
    rx = build_prescription(prescription_id=5, doctor_id=1, items=[old_item], status="pending")

    mock_service.prescription_repo.get_by_id = AsyncMock(return_value=rx)
    mock_service.medicine_repo.get_by_id_for_update = AsyncMock(side_effect=[med_old, med_new])
    mock_service.medicine_repo.update_reserved_stock = AsyncMock()
    mock_service.batch_repo.get_available_batches_fefo = AsyncMock(return_value=[])
    mock_service.prescription_repo.update = AsyncMock(return_value=rx)

    update_payload = PrescriptionUpdate(
        items=[
            PrescriptionItemCreate(
                medicine_id=20,
                dosage="B",
                frequency="1-1",
                duration_days=2,
                quantity=4,
            )
        ]
    )

    mock_user = MagicMock(id=1, role=MagicMock(name="doctor"))
    await mock_service.update_prescription(
        prescription_id=5,
        data=update_payload,
        doctor_id=1,
        user_id=1,
        current_user=mock_user,
    )

    # Asserts:
    # 1. Released old reservation: update_reserved_stock(10, -3)
    # 2. Acquired new reservation: update_reserved_stock(20, 4)
    calls = [call.args for call in mock_service.medicine_repo.update_reserved_stock.call_args_list]
    assert (10, -3) in calls
    assert (20, 4) in calls


# =====================================================================
# 7. Reservation integrity during prescription cancellation
# =====================================================================
@pytest.mark.asyncio
async def test_update_prescription_status_cancellation_releases_reservation(mock_service):
    med = build_medicine(med_id=30, stock=20, reserved=5)
    item = build_prescription_item(item_id=1, prescription_id=7, medicine_id=30, quantity=5)
    rx = build_prescription(prescription_id=7, items=[item], status="pending")

    # Mock DB query in update_prescription_status
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = rx
    mock_service.db.execute = AsyncMock(return_value=mock_result)

    mock_service.prescription_repo.get_by_id = AsyncMock(return_value=rx)
    mock_service.medicine_repo.get_by_id_for_update = AsyncMock(return_value=med)
    mock_service.medicine_repo.update_reserved_stock = AsyncMock()
    mock_service.prescription_repo.update = AsyncMock(return_value=rx)

    status_update = PrescriptionStatusUpdate(status="cancelled")
    await mock_service.update_prescription_status(7, data=status_update, user_id=1)

    # Asserts:
    # Released reservation when cancelled: update_reserved_stock(30, -5)
    mock_service.medicine_repo.update_reserved_stock.assert_called_once_with(30, -5)


# =====================================================================
# 8. Reservation integrity during prescription delete
# =====================================================================
@pytest.mark.asyncio
async def test_delete_prescription_releases_reservation_safely(mock_service):
    med = build_medicine(med_id=30, stock=20, reserved=5)
    item = build_prescription_item(item_id=1, prescription_id=8, medicine_id=30, quantity=5)
    rx = build_prescription(prescription_id=8, doctor_id=1, items=[item], status="pending")

    mock_service.prescription_repo.get_by_id = AsyncMock(return_value=rx)
    mock_service.medicine_repo.get_by_id_for_update = AsyncMock(return_value=med)
    mock_service.medicine_repo.update_reserved_stock = AsyncMock()
    mock_service.prescription_repo.soft_delete = AsyncMock()

    await mock_service.delete_prescription(8, doctor_id=1, user_id=1)

    # Asserts:
    mock_service.medicine_repo.update_reserved_stock.assert_called_once_with(30, -5)
    mock_service.prescription_repo.soft_delete.assert_called_once_with(rx)
