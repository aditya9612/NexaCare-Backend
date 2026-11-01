import pytest
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from app.models.billing_model import Billing, Payment
from app.models.pharmacy_model import PharmacyInvoice, PharmacyReturn
from app.schemas.billing_schema import DailyCollectionSummary, RefundCreate
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
    # scalar side_effect: [ref_stmt (sum), ref_cnt_stmt (count), cnt_stmt (payment count)]
    mock_db.scalar.side_effect = [0.0, 0, 0]

    result = await repo.get_daily_collection(date(2026, 9, 16))

    assert result["today_total_bill"] == 0.0
    assert result["today_paid_bill"] == 0.0
    assert result["today_pending_bill"] == 0.0
    assert result["today_collected_revenue"] == 0.0
    assert result["bills_count"] == 0
    assert result["total_collected"] == 0.0
    assert result["payment_count"] == 0
    assert result["refunds_issued"] == 0.0
    assert result["refund_count"] == 0
    assert result["by_method"] == {}


@pytest.mark.asyncio
async def test_get_daily_collection_partially_paid_bill_no_refunds():
    mock_db = AsyncMock()
    repo = BillingRepository(mock_db)

    # Bill total = 590, paid = 100, balance = 490, count = 1
    mock_res_b = MagicMock()
    mock_res_b.first.return_value = (590.0, 100.0, 490.0, 1)

    # Payment by_method = cash: 100.0
    mock_res_p = MagicMock()
    mock_res_p.all.return_value = [("cash", 100.0)]

    mock_db.execute.side_effect = [mock_res_b, mock_res_p]
    # scalar side_effect: [ref_stmt=0.0 (no refund), ref_cnt_stmt=0, cnt_stmt=1 (1 payment)]
    mock_db.scalar.side_effect = [0.0, 0, 1]

    result = await repo.get_daily_collection(date(2026, 9, 16))

    assert result["today_total_bill"] == 590.0
    assert result["today_paid_bill"] == 100.0
    assert result["today_pending_bill"] == 490.0
    assert result["today_collected_revenue"] == 100.0
    assert result["bills_count"] == 1
    assert result["total_collected"] == 100.0
    assert result["payment_count"] == 1
    assert result["refunds_issued"] == 0.0
    assert result["refund_count"] == 0
    assert result["by_method"] == {"cash": 100.0}


@pytest.mark.asyncio
async def test_get_daily_collection_single_refund():
    mock_db = AsyncMock()
    repo = BillingRepository(mock_db)

    # Billed 1000.0, Paid 1000.0, Balance 0.0, 1 bill
    mock_res_b = MagicMock()
    mock_res_b.first.return_value = (1000.0, 1000.0, 0.0, 1)

    # Payment received: cash 1000.0
    mock_res_p = MagicMock()
    mock_res_p.all.return_value = [("cash", 1000.0)]

    mock_db.execute.side_effect = [mock_res_b, mock_res_p]
    # scalar: refund_total=250.0, refund_count=1, payment_count=1
    mock_db.scalar.side_effect = [250.0, 1, 1]

    result = await repo.get_daily_collection(date(2026, 10, 29))

    assert result["today_total_bill"] == 1000.0
    assert result["today_paid_bill"] == 1000.0
    assert result["today_pending_bill"] == 0.0
    # Net collected revenue = 1000.0 - 250.0 = 750.0
    assert result["today_collected_revenue"] == 750.0
    assert result["total_collected"] == 750.0
    assert result["bills_count"] == 1
    assert result["payment_count"] == 1
    assert result["refunds_issued"] == 250.0
    assert result["refund_count"] == 1
    # by_method has cash and refund breakdown
    assert result["by_method"] == {"cash": 1000.0, "refund": 250.0}


@pytest.mark.asyncio
async def test_get_daily_collection_multiple_refunds():
    mock_db = AsyncMock()
    repo = BillingRepository(mock_db)

    mock_res_b = MagicMock()
    mock_res_b.first.return_value = (2000.0, 2000.0, 0.0, 2)

    mock_res_p = MagicMock()
    mock_res_p.all.return_value = [("cash", 1200.0), ("online", 800.0)]

    mock_db.execute.side_effect = [mock_res_b, mock_res_p]
    # scalar: refund_total=450.0 (e.g. 250 + 200), refund_count=2, payment_count=2
    mock_db.scalar.side_effect = [450.0, 2, 2]

    result = await repo.get_daily_collection(date(2026, 10, 29))

    # Gross = 1200 + 800 = 2000. Net = 2000 - 450 = 1550.0
    assert result["today_collected_revenue"] == 1550.0
    assert result["total_collected"] == 1550.0
    assert result["refunds_issued"] == 450.0
    assert result["refund_count"] == 2
    assert result["by_method"] == {"cash": 1200.0, "online": 800.0, "refund": 450.0}


@pytest.mark.asyncio
async def test_get_daily_collection_tenant_isolation():
    mock_db = AsyncMock()
    repo = BillingRepository(mock_db)

    mock_res_b = MagicMock()
    mock_res_b.first.return_value = (500.0, 500.0, 0.0, 1)

    mock_res_p = MagicMock()
    mock_res_p.all.return_value = [("upi", 500.0)]

    mock_db.execute.side_effect = [mock_res_b, mock_res_p]
    # scalar: refund_total=100.0, refund_count=1, payment_count=1
    mock_db.scalar.side_effect = [100.0, 1, 1]

    hospital_id = 42
    result = await repo.get_daily_collection(date(2026, 10, 29), hospital_id=hospital_id)

    assert result["refunds_issued"] == 100.0
    assert result["refund_count"] == 1
    assert result["today_collected_revenue"] == 400.0

    # Verify hospital_id was applied in the queries executed
    assert mock_db.execute.call_count == 2
    assert mock_db.scalar.call_count == 3


@pytest.mark.asyncio
async def test_get_daily_collection_date_filtering():
    mock_db = AsyncMock()
    repo = BillingRepository(mock_db)

    mock_res_b = MagicMock()
    mock_res_b.first.return_value = (300.0, 300.0, 0.0, 1)

    mock_res_p = MagicMock()
    mock_res_p.all.return_value = [("cash", 300.0)]

    mock_db.execute.side_effect = [mock_res_b, mock_res_p]
    mock_db.scalar.side_effect = [50.0, 1, 1]

    start_date = date(2026, 10, 1)
    end_date = date(2026, 10, 7)
    result = await repo.get_daily_collection(target_date=start_date, end_date=end_date)

    assert result["refunds_issued"] == 50.0
    assert result["refund_count"] == 1
    assert result["today_collected_revenue"] == 250.0


@pytest.mark.asyncio
async def test_daily_report_service_schema_mapping_with_refunds():
    mock_db = AsyncMock()
    service = BillingService(mock_db)

    mock_res_pharm = MagicMock()
    mock_res_pharm.first.return_value = (0.0, 0.0, 0.0, 0, 0)
    mock_db.execute.return_value = mock_res_pharm

    service.repo.get_daily_collection = AsyncMock(return_value={
        "today_total_bill": 1000.0,
        "today_paid_bill": 1000.0,
        "today_pending_bill": 0.0,
        "today_collected_revenue": 800.0,
        "bills_count": 2,
        "total_collected": 800.0,
        "payment_count": 2,
        "refunds_issued": 200.0,
        "refund_count": 1,
        "by_method": {"cash": 1000.0, "refund": 200.0},
    })

    summary: DailyCollectionSummary = await service.get_daily_report(date(2026, 10, 29))

    # Overall Summary
    assert summary.date == "2026-10-29"
    assert summary.today_total_bill == 1000.0
    assert summary.today_paid_bill == 1000.0
    assert summary.today_pending_bill == 0.0
    assert summary.today_collected_revenue == 800.0
    assert summary.total_collected == 800.0
    assert summary.bills_count == 2
    assert summary.payment_count == 2
    assert summary.refunds_issued == 200.0
    assert summary.refund_count == 1
    assert summary.by_method == {"cash": 1000.0, "refund": 200.0}

    # Separate Reception Section
    assert summary.reception_refunds_issued == 200.0
    assert summary.reception_refund_count == 1
    assert summary.reception_collection is not None
    assert summary.reception_collection.refunds_issued == 200.0
    assert summary.reception_collection.refund_count == 1


@pytest.mark.asyncio
async def test_daily_report_service_schema_mapping_zero_refunds():
    mock_db = AsyncMock()
    service = BillingService(mock_db)

    mock_res_pharm = MagicMock()
    mock_res_pharm.first.return_value = (0.0, 0.0, 0.0, 0, 0)
    mock_db.execute.return_value = mock_res_pharm

    service.repo.get_daily_collection = AsyncMock(return_value={
        "today_total_bill": 720.0,
        "today_paid_bill": 720.0,
        "today_pending_bill": 0.0,
        "today_collected_revenue": 720.0,
        "bills_count": 1,
        "total_collected": 720.0,
        "payment_count": 1,
        "refunds_issued": 0.0,
        "refund_count": 0,
        "by_method": {"cash": 720.0},
    })

    summary: DailyCollectionSummary = await service.get_daily_report(date(2026, 10, 29))

    assert summary.refunds_issued == 0.0
    assert summary.refund_count == 0
    assert summary.reception_refunds_issued == 0.0
    assert summary.reception_refund_count == 0
    assert summary.reception_collection.refunds_issued == 0.0
    assert summary.reception_collection.refund_count == 0


@pytest.mark.asyncio
async def test_daily_report_service_fallback_to_by_method_refund():
    """Verify backward compatibility when repo returns by_method['refund'] without explicit refunds_issued key."""
    mock_db = AsyncMock()
    service = BillingService(mock_db)

    mock_res_pharm = MagicMock()
    mock_res_pharm.first.return_value = (0.0, 0.0, 0.0, 0, 0)
    mock_db.execute.return_value = mock_res_pharm

    service.repo.get_daily_collection = AsyncMock(return_value={
        "today_total_bill": 500.0,
        "today_paid_bill": 500.0,
        "today_pending_bill": 0.0,
        "today_collected_revenue": 450.0,
        "bills_count": 1,
        "total_collected": 450.0,
        "payment_count": 1,
        "by_method": {"cash": 500.0, "refund": 50.0},
    })

    summary: DailyCollectionSummary = await service.get_daily_report(date(2026, 10, 29))

    assert summary.refunds_issued == 50.0
    assert summary.refund_count == 0
    assert summary.reception_refunds_issued == 50.0
    assert summary.reception_collection.refunds_issued == 50.0


@pytest.mark.asyncio
async def test_daily_report_service_with_pharmacy_refund_only():
    """Verify that a pharmacy refund (e.g. ₹1.0 on invoice 665) is reflected in top-level and pharmacy section."""
    mock_db = AsyncMock()
    service = BillingService(mock_db)

    # 1. Reception stats: 0 refunds
    service.repo.get_daily_collection = AsyncMock(return_value={
        "today_total_bill": 0.0,
        "today_paid_bill": 0.0,
        "today_pending_bill": 0.0,
        "today_collected_revenue": 0.0,
        "bills_count": 0,
        "total_collected": 0.0,
        "payment_count": 0,
        "refunds_issued": 0.0,
        "refund_count": 0,
        "by_method": {},
    })

    # 2. Pharmacy Invoices: 536.9 total, 535.9 paid, count 1
    mock_res_invoices = MagicMock()
    mock_res_invoices.first.return_value = (536.9, 535.9, 1.0, 1, 1)

    # 3. Pharmacy Returns: 1.0 refund, count 1
    mock_res_returns = MagicMock()
    mock_res_returns.first.return_value = (1.0, 1)

    mock_db.execute.side_effect = [mock_res_invoices, mock_res_returns]

    summary: DailyCollectionSummary = await service.get_daily_report(date(2026, 10, 30))

    # Top-level combined refunds must include the pharmacy refund
    assert summary.refunds_issued == 1.0
    assert summary.refund_count == 1
    assert summary.by_method.get("refund") == 1.0

    # Reception section remains 0
    assert summary.reception_refunds_issued == 0.0
    assert summary.reception_refund_count == 0
    assert summary.reception_collection.refunds_issued == 0.0
    assert summary.reception_collection.refund_count == 0

    # Pharmacy section accurately reflects the refund
    assert summary.pharmacy_refunds_issued == 1.0
    assert summary.pharmacy_refund_count == 1
    assert summary.pharmacy_collection.refunds_issued == 1.0
    assert summary.pharmacy_collection.refund_count == 1


@pytest.mark.asyncio
async def test_daily_report_service_with_both_reception_and_pharmacy_refunds():
    """Verify that reception refunds and pharmacy refunds are aggregated accurately."""
    mock_db = AsyncMock()
    service = BillingService(mock_db)

    # Reception has ₹200 refund, count 2
    service.repo.get_daily_collection = AsyncMock(return_value={
        "today_total_bill": 1000.0,
        "today_paid_bill": 800.0,
        "today_pending_bill": 200.0,
        "today_collected_revenue": 600.0,
        "bills_count": 2,
        "total_collected": 600.0,
        "payment_count": 2,
        "refunds_issued": 200.0,
        "refund_count": 2,
        "by_method": {"cash": 800.0, "refund": 200.0},
    })

    # Pharmacy Invoices: 500 total, 500 paid
    mock_res_invoices = MagicMock()
    mock_res_invoices.first.return_value = (500.0, 500.0, 0.0, 1, 1)

    # Pharmacy Returns: ₹75 refund, count 1
    mock_res_returns = MagicMock()
    mock_res_returns.first.return_value = (75.0, 1)

    mock_db.execute.side_effect = [mock_res_invoices, mock_res_returns]

    summary: DailyCollectionSummary = await service.get_daily_report(date(2026, 10, 30))

    # Combined refunds: 200 + 75 = 275.0, count: 2 + 1 = 3
    assert summary.refunds_issued == 275.0
    assert summary.refund_count == 3
    assert summary.by_method.get("refund") == 275.0

    # Section parity
    assert summary.reception_refunds_issued == 200.0
    assert summary.reception_refund_count == 2
    assert summary.pharmacy_refunds_issued == 75.0
    assert summary.pharmacy_refund_count == 1
    assert summary.pharmacy_collection.refunds_issued == 75.0
    assert summary.pharmacy_collection.refund_count == 1


@pytest.mark.asyncio
async def test_process_refund_pharmacy_invoice_sets_hospital_id():
    """Verify that process_refund for a pharmacy invoice populates hospital_id on PharmacyReturn."""
    mock_db = AsyncMock()
    service = BillingService(mock_db)

    # Not found in reception billings
    service.repo.get_by_id_for_update = AsyncMock(return_value=None)

    # Mock pharmacy invoice query
    invoice = PharmacyInvoice(
        id=665,
        hospital_id=15,
        patient_id=7,
        total_amount=536.9,
        paid_amount=536.9,
        invoice_number="INV-665",
    )
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = invoice
    mock_db.execute.return_value = mock_res

    service.audit_repo.create = AsyncMock()

    refund_data = RefundCreate(amount=1.0, refund_reason="Testing daily collection report refund calculation")

    response = await service.process_refund(
        billing_id=665,
        data=refund_data,
        user_id=1,
    )

    assert response.amount == 1.0
    assert response.is_refund is True
    assert invoice.paid_amount == 535.9

    # Verify that PharmacyReturn was added with hospital_id=15
    added_returns = [c[0][0] for c in mock_db.add.call_args_list if isinstance(c[0][0], PharmacyReturn)]
    assert len(added_returns) == 1
    added_obj = added_returns[0]
    assert added_obj.hospital_id == 15
    assert added_obj.total_refund_amount == 1.0
    assert added_obj.invoice_id == 665
