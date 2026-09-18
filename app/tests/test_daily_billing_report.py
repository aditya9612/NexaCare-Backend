import pytest
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from app.models.billing_model import Billing, Payment
from app.schemas.billing_schema import DailyCollectionSummary
from app.services.billing_service import BillingService
from app.repositories.billing_repository import BillingRepository

@pytest.mark.asyncio
async def test_get_daily_collection_no_bills():
    mock_db = AsyncMock()
    repo = BillingRepository(mock_db)

    # Return 0 for bill stats & payments
    mock_res_b = MagicMock()
    mock_res_b.first.return_value = (0.0, 0.0, 0.0, 0)
    
    mock_res_p = MagicMock()
    mock_res_p.all.return_value = []

    mock_db.execute.side_effect = [mock_res_b, mock_res_p]
    mock_db.scalar.side_effect = [0.0, 0]

    result = await repo.get_daily_collection(date(2026, 9, 16))

    assert result["today_total_bill"] == 0.0
    assert result["today_paid_bill"] == 0.0
    assert result["today_pending_bill"] == 0.0
    assert result["today_collected_revenue"] == 0.0
    assert result["bills_count"] == 0
    assert result["total_collected"] == 0.0
    assert result["payment_count"] == 0
    assert result["by_method"] == {}

@pytest.mark.asyncio
async def test_get_daily_collection_partially_paid_bill():
    mock_db = AsyncMock()
    repo = BillingRepository(mock_db)

    # Bill total = 590, paid = 1, balance = 589, count = 1
    mock_res_b = MagicMock()
    mock_res_b.first.return_value = (590.0, 1.0, 589.0, 1)

    # Payment by_method = cash: 1.0
    mock_res_p = MagicMock()
    mock_res_p.all.return_value = [("cash", 1.0)]

    mock_db.execute.side_effect = [mock_res_b, mock_res_p]
    mock_db.scalar.side_effect = [0.0, 1]  # refund_total = 0, payment_count = 1

    result = await repo.get_daily_collection(date(2026, 9, 16))

    assert result["today_total_bill"] == 590.0
    assert result["today_paid_bill"] == 1.0
    assert result["today_pending_bill"] == 589.0
    assert result["today_collected_revenue"] == 1.0
    assert result["bills_count"] == 1
    assert result["total_collected"] == 1.0
    assert result["payment_count"] == 1
    assert result["by_method"] == {"cash": 1.0}

@pytest.mark.asyncio
async def test_daily_report_service_schema_mapping():
    mock_db = AsyncMock()
    service = BillingService(mock_db)

    # Mock pharmacy execute to return 0
    mock_res_pharm = MagicMock()
    mock_res_pharm.first.return_value = (0.0, 0)
    mock_db.execute.return_value = mock_res_pharm

    service.repo.get_daily_collection = AsyncMock(return_value={
        "today_total_bill": 590.0,
        "today_paid_bill": 1.0,
        "today_pending_bill": 589.0,
        "today_collected_revenue": 1.0,
        "bills_count": 1,
        "total_collected": 1.0,
        "payment_count": 1,
        "by_method": {"cash": 1.0}
    })

    summary = await service.get_daily_report(date(2026, 9, 16))

    assert summary.date == "2026-09-16"
    assert summary.today_total_bill == 590.0
    assert summary.today_paid_bill == 1.0
    assert summary.today_pending_bill == 589.0
    assert summary.today_collected_revenue == 1.0
    assert summary.bills_count == 1
    assert summary.total_collected == 1.0
    assert summary.payment_count == 1
    assert summary.by_method == {"cash": 1.0}
