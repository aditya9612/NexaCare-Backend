import pytest
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock
from fastapi.encoders import jsonable_encoder

from app.models.discharge_model import Discharge
from app.schemas.common_schema import APIResponse
from app.schemas.discharge_schema import (
    ActiveDischargesResponse,
    ActiveDischargesWithSummaryResponse,
    DischargeActiveSummary,
    DischargeResponse,
)
from app.services.discharge_service import DischargeService


def make_dummy_discharge(
    id: int,
    hospital_id: int = 6,
    pharmacy_cleared: bool = False,
    billing_cleared: bool = False,
    payment_cleared: bool = False,
    doctor_approved: bool = False,
    discharge_status: str = "PENDING_CLEARANCES",
) -> Discharge:
    return Discharge(
        id=id,
        discharge_number=f"DIS-TEST-{id:04d}",
        appointment_id=10 + id,
        patient_id=100 + id,
        doctor_id=1,
        bed_id=id,
        admission_date=datetime(2026, 10, 1, 10, 0, 0),
        discharge_date=datetime(2026, 10, 5, 12, 0, 0),
        diagnosis_at_admission="Admission diagnosis",
        diagnosis_at_discharge="Discharge diagnosis",
        treatment_summary="Clinical procedure summary",
        condition_on_discharge="Stable",
        post_medications="Post medications",
        home_care_instructions="Home care instructions",
        follow_up_date=date(2026, 10, 15),
        pharmacy_cleared=pharmacy_cleared,
        billing_cleared=billing_cleared,
        payment_cleared=payment_cleared,
        doctor_approved=doctor_approved,
        discharge_status=discharge_status,
        hospital_id=hospital_id,
        created_at=datetime(2026, 10, 1, 10, 0, 0),
        updated_at=datetime(2026, 10, 5, 12, 0, 0),
    )


@pytest.mark.asyncio
async def test_list_active_discharges_summary_empty():
    mock_db = AsyncMock()
    service = DischargeService(mock_db)
    service.repo.get_all_active = AsyncMock(return_value=[])

    result = await service.list_active_discharges(hospital_id=6)

    assert isinstance(result, ActiveDischargesResponse)
    assert result.summary.active_discharges == 0
    assert result.summary.pharmacy_pending == 0
    assert result.summary.billing_pending == 0
    assert result.summary.payment_pending == 0
    assert result.summary.doctor_approval_pending == 0
    assert result.discharges == []
    assert result.items == []
    service.repo.get_all_active.assert_awaited_once_with(hospital_id=6)


@pytest.mark.asyncio
async def test_list_active_discharges_summary_calculation_matches_tester_scenario():
    """
    Matches the tester's reported scenario:
    Active Discharges: 5
    Pharmacy Pending: 0
    Billing Pending: 5
    Payment Pending: 5
    Doctor Approval Pending: 5
    """
    mock_db = AsyncMock()
    service = DischargeService(mock_db)

    # 5 records where pharmacy is cleared, but billing, payment, and doctor approval are pending
    mock_items = [
        make_dummy_discharge(
            id=i,
            pharmacy_cleared=True,
            billing_cleared=False,
            payment_cleared=False,
            doctor_approved=False,
        )
        for i in range(1, 6)
    ]
    service.repo.get_all_active = AsyncMock(return_value=mock_items)

    result = await service.list_active_discharges(hospital_id=6)

    assert result.summary.active_discharges == 5
    assert result.summary.pharmacy_pending == 0
    assert result.summary.billing_pending == 5
    assert result.summary.payment_pending == 5
    assert result.summary.doctor_approval_pending == 5

    # Python object fields still accessible
    assert result.active_discharges == 5
    assert result.pharmacy_pending == 0
    assert result.billing_pending == 5
    assert result.payment_pending == 5
    assert result.doctor_approval_pending == 5

    # Both discharges and items collections present in Python object
    assert len(result.discharges) == 5
    assert len(result.items) == 5
    assert result.discharges[0].id == 1
    assert result.discharges[4].id == 5


@pytest.mark.asyncio
async def test_list_active_discharges_summary_independent_category_counts():
    """
    Verifies that pending counts are calculated independently across stages.
    """
    mock_db = AsyncMock()
    service = DischargeService(mock_db)

    mock_items = [
        # Record 1: All pending
        make_dummy_discharge(1, pharmacy_cleared=False, billing_cleared=False, payment_cleared=False, doctor_approved=False),
        # Record 2: Pharmacy cleared, others pending
        make_dummy_discharge(2, pharmacy_cleared=True, billing_cleared=False, payment_cleared=False, doctor_approved=False),
        # Record 3: Pharmacy + Billing cleared, others pending
        make_dummy_discharge(3, pharmacy_cleared=True, billing_cleared=True, payment_cleared=False, doctor_approved=False),
        # Record 4: All cleared
        make_dummy_discharge(4, pharmacy_cleared=True, billing_cleared=True, payment_cleared=True, doctor_approved=True, discharge_status="CLEARED"),
    ]
    service.repo.get_all_active = AsyncMock(return_value=mock_items)

    result = await service.list_active_discharges(hospital_id=6)

    assert result.summary.active_discharges == 4
    # Pending pharmacy: only record 1 (1)
    assert result.summary.pharmacy_pending == 1
    # Pending billing: records 1 and 2 (2)
    assert result.summary.billing_pending == 2
    # Pending payment: records 1, 2, and 3 (3)
    assert result.summary.payment_pending == 3
    # Pending doctor approval: records 1, 2, and 3 (3)
    assert result.summary.doctor_approval_pending == 3


@pytest.mark.asyncio
async def test_list_active_discharges_tenant_filtering_passed_to_repository():
    mock_db = AsyncMock()
    service = DischargeService(mock_db)
    service.repo.get_all_active = AsyncMock(return_value=[])

    await service.list_active_discharges(hospital_id=12)

    service.repo.get_all_active.assert_awaited_once_with(hospital_id=12)


@pytest.mark.asyncio
async def test_items_and_root_counts_excluded_from_json_serialization():
    """
    Verifies:
    - Root-level counts and `items` remain defined and accessible in Python (`result.active_discharges`, `result.items`).
    - Root-level counts and `items` are excluded from JSON serialization (model_dump and jsonable_encoder).
    - `summary` (with all 5 counts) and `discharges` (with all records) appear only once in the JSON response.
    """
    mock_db = AsyncMock()
    service = DischargeService(mock_db)
    mock_items = [
        make_dummy_discharge(1, pharmacy_cleared=True, billing_cleared=False),
        make_dummy_discharge(2, pharmacy_cleared=True, billing_cleared=True),
    ]
    service.repo.get_all_active = AsyncMock(return_value=mock_items)

    result = await service.list_active_discharges(hospital_id=6)

    # 1. Accessible on Python instance
    assert hasattr(result, "items")
    assert len(result.items) == 2
    assert len(result.discharges) == 2
    assert result.active_discharges == 2
    assert result.pharmacy_pending == 0
    assert result.billing_pending == 1

    # 2. Excluded from Pydantic model_dump
    dumped = result.model_dump()
    assert "discharges" in dumped
    assert "summary" in dumped
    assert "items" not in dumped
    assert "active_discharges" not in dumped
    assert "pharmacy_pending" not in dumped
    assert "billing_pending" not in dumped
    assert "payment_pending" not in dumped
    assert "doctor_approval_pending" not in dumped
    assert dumped["summary"]["active_discharges"] == 2
    assert len(dumped["discharges"]) == 2

    # 3. Excluded from FastAPI jsonable_encoder / APIResponse serialization
    api_resp = APIResponse(success=True, message="Success", data=result)
    encoded = jsonable_encoder(api_resp)

    data_payload = encoded["data"]
    assert "discharges" in data_payload
    assert "summary" in data_payload
    assert "items" not in data_payload
    assert "active_discharges" not in data_payload
    assert "pharmacy_pending" not in data_payload
    assert "billing_pending" not in data_payload
    assert "payment_pending" not in data_payload
    assert "doctor_approval_pending" not in data_payload
    assert data_payload["summary"]["active_discharges"] == 2
    assert data_payload["summary"]["pharmacy_pending"] == 0
    assert data_payload["summary"]["billing_pending"] == 1
    assert data_payload["summary"]["payment_pending"] == 2
    assert data_payload["summary"]["doctor_approval_pending"] == 2
    assert len(data_payload["discharges"]) == 2
