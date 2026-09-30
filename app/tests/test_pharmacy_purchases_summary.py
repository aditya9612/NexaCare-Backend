from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.pharmacy_model import Purchase
from app.repositories.pharmacy_repository import PurchaseRepository
from app.schemas.pharmacy_schema import PurchaseListResponse, PurchaseSummary
from app.services.pharmacy_service import PharmacyService


@pytest.mark.asyncio
async def test_purchase_repository_get_summary_stats_mock():
    """Verify PurchaseRepository.get_summary_stats calculates all 4 metrics accurately."""
    mock_db = AsyncMock()
    # Mock scalars for total_orders=15, pending_orders=4, completed_orders=11, total_spent=14250.50
    mock_db.scalar.side_effect = [15, 4, 11, 14250.50]

    repo = PurchaseRepository(mock_db)
    stats = await repo.get_summary_stats()

    assert stats["total_orders"] == 15
    assert stats["pending_orders"] == 4
    assert stats["completed_orders"] == 11
    assert stats["total_spent"] == 14250.50


@pytest.mark.asyncio
async def test_pharmacy_service_list_purchases_summary_structure():
    """Verify PharmacyService.list_purchases returns PurchaseListResponse with summary card metrics."""
    mock_db = AsyncMock()

    service = PharmacyService(mock_db)
    service.purchase_repo = AsyncMock()

    # Mock sample purchase item
    sample_purchase = Purchase(
        id=1,
        purchase_number="PO-20260930-001",
        supplier_id=2,
        total_amount=1250.0,
        status="Received",
        ordered_at=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        items=[],
    )

    service.purchase_repo.list_all.return_value = [sample_purchase]
    service.purchase_repo.count_all.return_value = 1
    service.purchase_repo.get_summary_stats.return_value = {
        "total_orders": 1,
        "pending_orders": 0,
        "completed_orders": 1,
        "total_spent": 1250.0,
    }

    res = await service.list_purchases(page=1, size=20)

    assert isinstance(res, PurchaseListResponse)
    assert isinstance(res.summary, PurchaseSummary)
    assert res.summary.total_orders == 1
    assert res.summary.pending_orders == 0
    assert res.summary.completed_orders == 1
    assert res.summary.total_spent == 1250.0

    assert res.total == 1
    assert res.page == 1
    assert res.size == 20
    assert res.pages == 1
    assert len(res.items) == 1
    assert res.items[0].purchase_number == "PO-20260930-001"

    # Verify exact field ordering: items, total, page, size, pages, summary
    keys = list(res.model_dump().keys())
    assert keys == ["items", "total", "page", "size", "pages", "summary"]


@pytest.mark.asyncio
async def test_purchase_summary_empty_dataset_mock():
    """Verify empty dataset returns zero counts and total_spent = 0.0."""
    mock_db = AsyncMock()

    service = PharmacyService(mock_db)
    service.purchase_repo = AsyncMock()

    service.purchase_repo.list_all.return_value = []
    service.purchase_repo.count_all.return_value = 0
    service.purchase_repo.get_summary_stats.return_value = {
        "total_orders": 0,
        "pending_orders": 0,
        "completed_orders": 0,
        "total_spent": 0.0,
    }

    res = await service.list_purchases(page=1, size=20)

    assert res.summary.total_orders == 0
    assert res.summary.pending_orders == 0
    assert res.summary.completed_orders == 0
    assert res.summary.total_spent == 0.0
    assert res.items == []
    assert res.total == 0
    assert res.pages == 0
