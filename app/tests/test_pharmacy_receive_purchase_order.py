"""
Regression tests for PATCH /api/v1/pharmacy/purchases/{purchase_id}/receive

Bug fixed: Purchase Orders with status "In Transit" were rejected with
           400 "Invalid Purchase Order status".

Tests cover:
  1. "In Transit" (title-case, space)  — the exact tester-reported failure
  2. "in_transit"  (underscore variant) — normalises the same way
  3. All previously-allowed statuses still work
  4. Invalid / terminal statuses are still rejected
  5. Idempotency: receiving twice does NOT duplicate stock or raise an
     unexpected error beyond "already received"
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.exceptions import BadRequestException, NotFoundException
from app.models.pharmacy_model import Purchase, PurchaseItem
from app.services.pharmacy_service import PharmacyService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow():
    return datetime.now(timezone.utc)


def _make_purchase(
    status: str,
    received_at=None,
    purchase_id: int = 1,
    hospital_id: int = 10,
    is_deleted: bool = False,
) -> Purchase:
    """Create a minimal Purchase model instance for unit testing."""
    p = Purchase(
        id=purchase_id,
        purchase_number=f"PO-TEST-{purchase_id:04d}",
        supplier_id=1,
        hospital_id=hospital_id,
        total_amount=500.0,
        status=status,
        ordered_at=_utcnow(),
        received_at=received_at,
        notes=None,
        created_by=99,
        received_by=None,
    )
    p.items = []
    p.is_deleted = is_deleted
    return p


def _make_service_with_purchase(purchase: Purchase) -> PharmacyService:
    """
    Wire a PharmacyService so that both the direct SELECT-FOR-UPDATE path
    and the fallback get_by_id path return the given purchase object.
    The _process_stock_receipt method is stubbed out to avoid DB calls.
    """
    mock_db = AsyncMock()

    # SELECT FOR UPDATE result
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = purchase
    mock_db.execute = AsyncMock(return_value=mock_result)

    service = PharmacyService(mock_db)

    # Fallback repo path
    service.purchase_repo = AsyncMock()
    service.purchase_repo.get_by_id = AsyncMock(return_value=purchase)

    return service


def _make_current_user(user_id: int = 42, hospital_id: int = 10):
    user = MagicMock()
    user.id = user_id
    user.hospital_id = hospital_id
    return user


# ---------------------------------------------------------------------------
# 1. In Transit (title-case + space) — the reported bug
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_receive_in_transit_title_case_succeeds():
    """
    PATCH /purchases/{id}/receive must succeed when the PO status is
    'In Transit' (the exact value the tester reported).
    """
    purchase = _make_purchase(status="In Transit")
    service = _make_service_with_purchase(purchase)
    user = _make_current_user()

    received_purchase = _make_purchase(status="received", received_at=_utcnow())
    received_purchase.items = []

    with patch.object(
        service,
        "_process_stock_receipt",
        new=AsyncMock(return_value=received_purchase),
    ):
        result = await service.receive_purchase_order(
            purchase_order_id=1,
            current_user=user,
        )

    assert result.status == "received"


# ---------------------------------------------------------------------------
# 2. in_transit (lowercase, underscore)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_receive_in_transit_underscore_succeeds():
    """
    'in_transit' (underscore) must also be accepted after .lower()
    normalisation produces 'in_transit'.
    """
    purchase = _make_purchase(status="in_transit")
    service = _make_service_with_purchase(purchase)
    user = _make_current_user()

    received_purchase = _make_purchase(status="received", received_at=_utcnow())
    received_purchase.items = []

    with patch.object(
        service,
        "_process_stock_receipt",
        new=AsyncMock(return_value=received_purchase),
    ):
        result = await service.receive_purchase_order(
            purchase_order_id=1,
            current_user=user,
        )

    assert result.status == "received"


# ---------------------------------------------------------------------------
# 3. In Transit all-uppercase (normalisation boundary check)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_receive_in_transit_upper_case_succeeds():
    """
    'IN TRANSIT' must normalise to 'in transit' and be accepted.
    """
    purchase = _make_purchase(status="IN TRANSIT")
    service = _make_service_with_purchase(purchase)
    user = _make_current_user()

    received_purchase = _make_purchase(status="received", received_at=_utcnow())
    received_purchase.items = []

    with patch.object(
        service,
        "_process_stock_receipt",
        new=AsyncMock(return_value=received_purchase),
    ):
        result = await service.receive_purchase_order(
            purchase_order_id=1,
            current_user=user,
        )

    assert result.status == "received"


# ---------------------------------------------------------------------------
# 4. Existing valid statuses still pass (regression guard)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("existing_status", [
    "ordered",
    "Ordered",
    "pending",
    "Pending",
    "partially_received",
    "draft",
])
async def test_receive_previously_allowed_statuses_still_succeed(existing_status):
    """
    All statuses that were accepted before the fix must continue to be
    accepted — purely additive change must not regress existing behaviour.
    """
    purchase = _make_purchase(status=existing_status)
    service = _make_service_with_purchase(purchase)
    user = _make_current_user()

    received_purchase = _make_purchase(status="received", received_at=_utcnow())
    received_purchase.items = []

    with patch.object(
        service,
        "_process_stock_receipt",
        new=AsyncMock(return_value=received_purchase),
    ):
        result = await service.receive_purchase_order(
            purchase_order_id=1,
            current_user=user,
        )

    assert result.status == "received"


# ---------------------------------------------------------------------------
# 5. Invalid / terminal statuses are still rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("bad_status", [
    "cancelled",
    "Cancelled",
    "unknown",
    "shipped",
    "approved",
    "",
])
async def test_receive_invalid_statuses_still_rejected(bad_status):
    """
    Statuses that were not allowed before the fix (and are not 'In Transit')
    must still raise BadRequestException("Invalid Purchase Order status").
    """
    purchase = _make_purchase(status=bad_status)
    service = _make_service_with_purchase(purchase)
    user = _make_current_user()

    with pytest.raises(BadRequestException) as exc_info:
        await service.receive_purchase_order(
            purchase_order_id=1,
            current_user=user,
        )

    assert exc_info.value.status_code == 400
    assert "Invalid Purchase Order status" in str(exc_info.value.detail)


# ---------------------------------------------------------------------------
# 6. Already-received status triggers the "already received" guard,
#    NOT the whitelist guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_status", ["received", "Received", "delivered", "Delivered"])
async def test_already_received_status_raises_already_received(terminal_status):
    """
    'received' and 'delivered' must hit the first guard (already received),
    not the whitelist guard.
    """
    purchase = _make_purchase(status=terminal_status)
    service = _make_service_with_purchase(purchase)
    user = _make_current_user()

    with pytest.raises(BadRequestException) as exc_info:
        await service.receive_purchase_order(
            purchase_order_id=1,
            current_user=user,
        )

    assert exc_info.value.status_code == 400
    assert "already received" in str(exc_info.value.detail).lower()


# ---------------------------------------------------------------------------
# 7. Idempotency: received_at already set → "already received" (no stock dup)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_receive_twice_does_not_duplicate_stock():
    """
    If a PO has received_at already set (regardless of status string),
    the service must return "already received" without calling
    _process_stock_receipt — guaranteeing stock is not credited twice.
    """
    purchase = _make_purchase(status="In Transit", received_at=_utcnow())
    service = _make_service_with_purchase(purchase)
    user = _make_current_user()

    mock_receipt = AsyncMock()

    with patch.object(service, "_process_stock_receipt", new=mock_receipt):
        with pytest.raises(BadRequestException) as exc_info:
            await service.receive_purchase_order(
                purchase_order_id=1,
                current_user=user,
            )

    # _process_stock_receipt must NOT have been called
    mock_receipt.assert_not_called()
    assert "already received" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_receive_in_transit_twice_status_received_second_call_blocked():
    """
    After first receive, PO status becomes 'received'. A second call must
    be blocked by the first guard (already received), not reach stock logic.
    """
    # Simulate second call: status is now 'received', received_at is set
    purchase = _make_purchase(status="received", received_at=_utcnow())
    service = _make_service_with_purchase(purchase)
    user = _make_current_user()

    mock_receipt = AsyncMock()

    with patch.object(service, "_process_stock_receipt", new=mock_receipt):
        with pytest.raises(BadRequestException) as exc_info:
            await service.receive_purchase_order(
                purchase_order_id=1,
                current_user=user,
            )

    mock_receipt.assert_not_called()
    assert "already received" in str(exc_info.value.detail).lower()


# ---------------------------------------------------------------------------
# 8. Not found / soft-deleted PO still raises NotFoundException
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_receive_nonexistent_purchase_raises_not_found():
    """A PO that does not exist must raise NotFoundException."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    service = PharmacyService(mock_db)
    service.purchase_repo = AsyncMock()
    service.purchase_repo.get_by_id = AsyncMock(return_value=None)

    user = _make_current_user()

    with pytest.raises(NotFoundException) as exc_info:
        await service.receive_purchase_order(purchase_order_id=9999, current_user=user)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_receive_soft_deleted_purchase_raises_not_found():
    """A soft-deleted PO must raise NotFoundException."""
    purchase = _make_purchase(status="In Transit", is_deleted=True)

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    service = PharmacyService(mock_db)
    service.purchase_repo = AsyncMock()
    # Repo returns it but is_deleted is True
    service.purchase_repo.get_by_id = AsyncMock(return_value=purchase)

    user = _make_current_user()

    with pytest.raises(NotFoundException) as exc_info:
        await service.receive_purchase_order(purchase_order_id=1, current_user=user)

    assert exc_info.value.status_code == 404
