import pytest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.models.bed_allocation_model import Bed
from app.models.discharge_model import Discharge
from app.models.final_bill_model import IPDFinalBill
from app.schemas.discharge_schema import ClearBillingRequest, ClearPaymentRequest
from app.services.discharge_service import DischargeService


def make_discharge_fixture(
    id: int = 1,
    hospital_id: int = 6,
    pharmacy_cleared: bool = False,
    billing_cleared: bool = False,
    payment_cleared: bool = False,
    doctor_approved: bool = False,
    discharge_status: str = "PENDING_CLEARANCES",
    final_bill_id: int | None = 10,
    billing_id: int | None = 20,
    bed_id: int | None = 5,
) -> Discharge:
    return Discharge(
        id=id,
        discharge_number=f"DIS-TEST-{id:04d}",
        appointment_id=100 + id,
        patient_id=200 + id,
        doctor_id=1,
        bed_id=bed_id,
        admission_date=datetime(2026, 11, 1, 10, 0, 0),
        discharge_date=datetime(2026, 11, 3, 12, 0, 0),
        diagnosis_at_admission="Fever and dehydration",
        diagnosis_at_discharge="Recovered viral fever",
        treatment_summary="IV fluids and antipyretics",
        condition_on_discharge="Stable",
        post_medications="Paracetamol 650mg SOS",
        home_care_instructions="Rest and adequate hydration",
        follow_up_date=date(2026, 11, 10),
        pharmacy_cleared=pharmacy_cleared,
        billing_cleared=billing_cleared,
        payment_cleared=payment_cleared,
        doctor_approved=doctor_approved,
        discharge_status=discharge_status,
        final_bill_id=final_bill_id,
        billing_id=billing_id,
        hospital_id=hospital_id,
        created_at=datetime(2026, 11, 1, 10, 0, 0),
        updated_at=datetime(2026, 11, 3, 12, 0, 0),
    )


@pytest.mark.asyncio
async def test_clear_billing_succeeds_when_final_bill_pending_with_outstanding_balance():
    """
    Scenario 1:
    Billing Clearance succeeds when the final bill is pending with an outstanding balance.
    The premature validate_applicable_ipd_bills_settled() must NOT be called or block billing clearance.
    """
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    service = DischargeService(mock_db)

    discharge = make_discharge_fixture(
        pharmacy_cleared=True,
        billing_cleared=False,
        final_bill_id=10,
    )
    def mock_update(d):
        d.discharge_date = datetime(2026, 11, 3, 12, 0, 0)
        return d

    service.repo.get_by_id = AsyncMock(return_value=discharge)
    service.repo.update = AsyncMock(side_effect=mock_update)

    request_data = ClearBillingRequest(notes="Audited all room and procedure charges.")
    result = await service.clear_billing(
        discharge_id=discharge.id,
        user_id=42,
        data=request_data,
        hospital_id=6,
    )

    assert result.billing_cleared is True
    assert result.billing_notes == "Audited all room and procedure charges."
    assert discharge.billing_cleared is True
    assert discharge.billing_cleared_by == 42
    assert discharge.discharge_status == "PENDING_CLEARANCES"  # Payment is still pending
    service.repo.update.assert_awaited_once_with(discharge)


@pytest.mark.asyncio
async def test_clear_billing_fails_when_pharmacy_clearance_incomplete():
    """
    Scenario 2:
    Billing Clearance fails when pharmacy clearance is incomplete (pharmacy_cleared=False).
    """
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    service = DischargeService(mock_db)

    discharge = make_discharge_fixture(
        pharmacy_cleared=False,
        billing_cleared=False,
        final_bill_id=10,
    )
    service.repo.get_by_id = AsyncMock(return_value=discharge)

    with pytest.raises(BadRequestException) as exc_info:
        await service.clear_billing(
            discharge_id=discharge.id,
            user_id=42,
            data=ClearBillingRequest(notes="Trying to clear early"),
            hospital_id=6,
        )

    assert "Pharmacy Clearance must be completed before billing clearance" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_clear_billing_fails_when_final_bill_not_generated():
    """
    Scenario 3:
    Billing Clearance fails when final bill has not been generated (final_bill_id=None, billing_id=None).
    """
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    service = DischargeService(mock_db)

    discharge = make_discharge_fixture(
        pharmacy_cleared=True,
        billing_cleared=False,
        final_bill_id=None,
        billing_id=None,
    )
    service.repo.get_by_id = AsyncMock(return_value=discharge)

    with pytest.raises(BadRequestException) as exc_info:
        await service.clear_billing(
            discharge_id=discharge.id,
            user_id=42,
            data=ClearBillingRequest(notes="No bill generated"),
            hospital_id=6,
        )

    assert "IPD final bill must be generated before billing clearance" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_clear_payment_fails_when_billing_clearance_incomplete():
    """
    Scenario 4:
    Payment Clearance fails if billing clearance is incomplete (billing_cleared=False).
    """
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    service = DischargeService(mock_db)

    discharge = make_discharge_fixture(
        pharmacy_cleared=True,
        billing_cleared=False,
        payment_cleared=False,
        final_bill_id=10,
    )
    service.repo.get_by_id = AsyncMock(return_value=discharge)

    with pytest.raises(BadRequestException) as exc_info:
        await service.clear_payment(
            discharge_id=discharge.id,
            data=ClearPaymentRequest(payment_method="cash", notes="Cash payment"),
            user_id=55,
            hospital_id=6,
        )

    assert "Billing Clearance must be completed before payment clearance" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_clear_payment_succeeds_after_billing_clearance_and_valid_settlement():
    """
    Scenario 5:
    Payment Clearance succeeds after billing clearance is True and payment settlement resolves all dues.
    """
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    service = DischargeService(mock_db)

    discharge = make_discharge_fixture(
        pharmacy_cleared=True,
        billing_cleared=True,
        payment_cleared=False,
        final_bill_id=10,
        billing_id=20,
    )
    def mock_update(d):
        d.discharge_date = datetime(2026, 11, 3, 12, 0, 0)
        return d

    service.repo.get_by_id = AsyncMock(return_value=discharge)
    service.repo.update = AsyncMock(side_effect=mock_update)

    dummy_final_bill = IPDFinalBill(
        id=10,
        hospital_id=6,
        bill_number="IPD-BILL-20261103-0007",
        discharge_id=discharge.id,
        patient_id=discharge.patient_id,
        appointment_id=discharge.appointment_id,
        doctor_id=discharge.doctor_id,
        gross_total=5000.0,
        net_total=4195.0,
        advance_adjusted=0.0,
        balance_amount=4195.0,
        status="pending",
    )
    dummy_final_bill.items = []
    service.final_bill_repo.get_by_id_with_items = AsyncMock(return_value=dummy_final_bill)
    service.final_bill_repo.update = AsyncMock(return_value=dummy_final_bill)

    # Empty billing query and empty pharmacy query
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_db.scalars.return_value = mock_scalars

    # Settlement validation returns success
    service.validate_applicable_ipd_bills_settled = AsyncMock(return_value=(True, []))

    payment_data = ClearPaymentRequest(
        payment_method="upi",
        transaction_ref="UPI-REF-987654",
        notes="Settled in full via UPI",
    )

    result = await service.clear_payment(
        discharge_id=discharge.id,
        data=payment_data,
        user_id=55,
        hospital_id=6,
    )

    assert result.payment_cleared is True
    assert discharge.payment_cleared is True
    assert discharge.payment_cleared_by == 55
    assert dummy_final_bill.status == "paid"
    assert dummy_final_bill.balance_amount == 0.0
    assert dummy_final_bill.payment_mode == "upi"
    # All 3 clearances are now True, so discharge_status becomes CLEARED
    assert discharge.discharge_status == "CLEARED"


@pytest.mark.asyncio
async def test_clear_payment_fails_when_payment_already_cleared_preventing_duplicates():
    """
    Scenario 5b (Idempotency / Duplicate Prevention):
    Calling clear_payment() when payment_cleared is already True must raise ConflictException
    and must NOT perform any database mutations, update the final bill, or insert duplicate transactions.
    """
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    service = DischargeService(mock_db)

    discharge = make_discharge_fixture(
        pharmacy_cleared=True,
        billing_cleared=True,
        payment_cleared=True,  # Payment ALREADY cleared
        discharge_status="CLEARED",
        final_bill_id=10,
        billing_id=20,
    )
    service.repo.get_by_id = AsyncMock(return_value=discharge)
    service.final_bill_repo.get_by_id_with_items = AsyncMock()
    service.final_bill_repo.update = AsyncMock()

    payment_data = ClearPaymentRequest(
        payment_method="cash",
        transaction_ref="REPEAT-TXN-111",
        notes="Attempting duplicate payment",
    )

    with pytest.raises(ConflictException) as exc_info:
        await service.clear_payment(
            discharge_id=discharge.id,
            data=payment_data,
            user_id=55,
            hospital_id=6,
        )

    assert "Payment clearance has already been completed for this discharge" in str(exc_info.value.detail)
    # Verify no database mutation or final bill update was triggered
    service.final_bill_repo.get_by_id_with_items.assert_not_called()
    service.final_bill_repo.update.assert_not_called()
    mock_db.add.assert_not_called()


@pytest.mark.asyncio
async def test_doctor_approval_fails_if_any_applicable_bill_remains_unpaid():
    """
    Scenario 6:
    Doctor Approval fails with ConflictException (HTTP 409) if any applicable bill remains unpaid.
    """
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    service = DischargeService(mock_db)

    discharge = make_discharge_fixture(
        pharmacy_cleared=True,
        billing_cleared=True,
        payment_cleared=True,
        doctor_approved=False,
        discharge_status="CLEARED",
    )
    service.repo.get_by_id = AsyncMock(return_value=discharge)

    # validate_applicable_ipd_bills_settled reports an unsettled bill
    outstanding_bill = {
        "bill_type": "ipd_final_bill",
        "bill_id": 10,
        "bill_number": "IPD-BILL-20261103-0007",
        "status": "pending",
        "total_amount": 4195.0,
        "paid_amount": 0.0,
        "outstanding_balance": 4195.0,
        "reason": "Outstanding balance remains",
    }
    service.validate_applicable_ipd_bills_settled = AsyncMock(return_value=(False, [outstanding_bill]))

    with pytest.raises(ConflictException) as exc_info:
        await service.doctor_approve_discharge(
            discharge_id=discharge.id,
            doctor_user_id=1,
            hospital_id=6,
        )

    assert "Cannot approve discharge. Outstanding unpaid bills remain" in str(exc_info.value.detail)
    assert "IPD-BILL-20261103-0007" in str(exc_info.value.detail)
    assert discharge.doctor_approved is False
    assert discharge.discharge_status != "DISCHARGED"


@pytest.mark.asyncio
async def test_doctor_approval_succeeds_when_all_clearance_stages_complete_and_all_bills_settled():
    """
    Scenario 7:
    Doctor Approval succeeds when pharmacy, billing, and payment clearances are True,
    and validate_applicable_ipd_bills_settled() confirms zero outstanding dues.
    """
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    service = DischargeService(mock_db)

    dummy_bed = Bed(id=5, status="Occupied", patient_id=201, room_id=1)
    mock_db.get = AsyncMock(return_value=dummy_bed)

    discharge = make_discharge_fixture(
        pharmacy_cleared=True,
        billing_cleared=True,
        payment_cleared=True,
        doctor_approved=False,
        discharge_status="CLEARED",
        bed_id=5,
    )
    discharge.appointment = MagicMock()
    def mock_update(d):
        d.discharge_date = datetime(2026, 11, 3, 12, 0, 0)
        return d

    service.repo.get_by_id = AsyncMock(return_value=discharge)
    service.repo.update = AsyncMock(side_effect=mock_update)
    service.validate_applicable_ipd_bills_settled = AsyncMock(return_value=(True, []))

    result = await service.doctor_approve_discharge(
        discharge_id=discharge.id,
        doctor_user_id=10,
        hospital_id=6,
    )

    assert result.doctor_approved is True
    assert discharge.doctor_approved is True
    assert discharge.doctor_approved_by == 10
    assert discharge.discharge_status == "DISCHARGED"
    assert discharge.gate_pass_number is not None
    assert dummy_bed.status == "Cleaning"
    assert dummy_bed.patient_id is None
    assert discharge.appointment.admission_status == "Discharged"


@pytest.mark.asyncio
async def test_validate_applicable_ipd_bills_settled_with_none_discharge_date():
    """
    Scenario 8:
    validate_applicable_ipd_bills_settled() succeeds without NameError when discharge_date is None
    and falls back safely to utc_now().
    """
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    service = DischargeService(mock_db)

    discharge = make_discharge_fixture(
        pharmacy_cleared=True,
        billing_cleared=True,
        final_bill_id=10,
    )
    discharge.discharge_date = None  # Crucial: test None discharge date fallback
    discharge.admission_date = datetime(2026, 11, 1, 10, 0, 0)

    dummy_final_bill = IPDFinalBill(
        id=10,
        hospital_id=6,
        bill_number="IPD-BILL-20261103-0007",
        discharge_id=discharge.id,
        patient_id=discharge.patient_id,
        appointment_id=discharge.appointment_id,
        doctor_id=discharge.doctor_id,
        gross_total=5000.0,
        net_total=4195.0,
        advance_adjusted=4195.0,
        balance_amount=0.0,
        status="paid",
    )
    dummy_final_bill.items = []
    service.final_bill_repo.get_by_id_with_items = AsyncMock(return_value=dummy_final_bill)

    # Mock DB queries for billing and pharmacy to return empty lists
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_db.scalars.return_value = mock_scalars

    # This would crash with NameError: name 'now_dt' is not defined before the fix
    all_settled, outstanding = await service.validate_applicable_ipd_bills_settled(discharge, hospital_id=6)

    assert all_settled is True
    assert outstanding == []


@pytest.mark.asyncio
async def test_clear_payment_with_none_discharge_date():
    """
    Scenario 9:
    clear_payment() succeeds without NameError when discharge_date is None
    and falls back safely to utc_now() during pharmacy invoice settlement.
    """
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    service = DischargeService(mock_db)

    discharge = make_discharge_fixture(
        pharmacy_cleared=True,
        billing_cleared=True,
        payment_cleared=False,
        final_bill_id=10,
        billing_id=20,
    )
    discharge.discharge_date = None  # Crucial: test None discharge date fallback
    discharge.admission_date = datetime(2026, 11, 1, 10, 0, 0)

    def mock_update(d):
        d.discharge_date = datetime(2026, 11, 3, 12, 0, 0)
        return d

    service.repo.get_by_id = AsyncMock(return_value=discharge)
    service.repo.update = AsyncMock(side_effect=mock_update)

    dummy_final_bill = IPDFinalBill(
        id=10,
        hospital_id=6,
        bill_number="IPD-BILL-20261103-0007",
        discharge_id=discharge.id,
        patient_id=discharge.patient_id,
        appointment_id=discharge.appointment_id,
        doctor_id=discharge.doctor_id,
        gross_total=5000.0,
        net_total=4195.0,
        advance_adjusted=0.0,
        balance_amount=4195.0,
        status="pending",
    )
    dummy_final_bill.items = []
    service.final_bill_repo.get_by_id_with_items = AsyncMock(return_value=dummy_final_bill)
    service.final_bill_repo.update = AsyncMock(return_value=dummy_final_bill)

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_db.scalars.return_value = mock_scalars

    service.validate_applicable_ipd_bills_settled = AsyncMock(return_value=(True, []))

    payment_data = ClearPaymentRequest(
        payment_method="cash",
        notes="Cash payment with None discharge_date",
    )

    # This would crash with NameError: name 'now_dt' is not defined before the fix
    result = await service.clear_payment(
        discharge_id=discharge.id,
        data=payment_data,
        user_id=55,
        hospital_id=6,
    )

    assert result.payment_cleared is True
    assert discharge.payment_cleared is True
    assert dummy_final_bill.status == "paid"
    assert dummy_final_bill.balance_amount == 0.0
