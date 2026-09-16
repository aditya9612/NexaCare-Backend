import pytest
from app.core.constants import BillingStatus
from app.core.database import AsyncSessionLocal
from app.core.exceptions import BadRequestException
from app.models.billing_model import Billing
from app.schemas.billing_schema import PaymentCreate
from app.schemas.transaction_schema import TransactionCreate
from app.services.billing_service import BillingService
from app.services.transaction_service import TransactionService
from app.utils.helpers import utc_now, generate_bill_number


@pytest.mark.asyncio
async def test_payment_duplicate_validation_service_flow():
    async with AsyncSessionLocal() as session:
        billing_service = BillingService(session)
        transaction_service = TransactionService(session)

        # 1. Create a test billing record in DB
        bill = Billing(
            bill_number=generate_bill_number(),
            patient_id=1,
            subtotal=500.0,
            gst_rate=0.0,
            total_amount=500.0,
            paid_amount=0.0,
            status=BillingStatus.PENDING,
            is_deleted=False,
            created_at=utc_now(),
        )
        session.add(bill)
        await session.commit()
        await session.refresh(bill)

        # 2. Valid payment creation -> succeeds
        payment_data = PaymentCreate(
            amount=500.0,
            payment_method="cash",
            transaction_ref=None,
        )
        payment_resp = await billing_service.collect_payment(bill.id, payment_data, user_id=1)
        assert payment_resp is not None
        assert payment_resp.amount == 500.0

        # Refresh bill to confirm state
        await session.refresh(bill)
        assert bill.paid_amount == 500.0
        assert str(bill.status).lower() == BillingStatus.PAID.lower()

        # 3. Second payment attempt on the same fully-paid bill -> MUST return "Payment record already exists for this bill"
        with pytest.raises(BadRequestException) as exc_info:
            await billing_service.collect_payment(bill.id, payment_data, user_id=1)
        assert exc_info.value.detail == "Payment record already exists for this bill"
        assert exc_info.value.detail != "Payment amount exceeds balance due"
        assert exc_info.value.detail != "Payment amount exceeds remaining amount"

        # Also test via TransactionService.create_transaction
        tx_data = TransactionCreate(
            billing_id=bill.id,
            amount=500.0,
            payment_method="cash",
            status="completed",
            is_refund=False,
        )
        with pytest.raises(BadRequestException) as exc_info_tx:
            await transaction_service.create_transaction(tx_data, user_id=1)
        assert exc_info_tx.value.detail == "Payment record already exists for this bill"

        # 4. Over-balance payment on an unpaid bill -> MUST return "Payment amount exceeds balance due"
        unpaid_bill = Billing(
            bill_number=generate_bill_number(),
            patient_id=1,
            subtotal=200.0,
            gst_rate=0.0,
            total_amount=200.0,
            paid_amount=0.0,
            status=BillingStatus.PENDING,
            is_deleted=False,
            created_at=utc_now(),
        )
        session.add(unpaid_bill)
        await session.commit()
        await session.refresh(unpaid_bill)

        over_payment = PaymentCreate(
            amount=300.0,
            payment_method="cash",
        )
        with pytest.raises(BadRequestException) as exc_over:
            await billing_service.collect_payment(unpaid_bill.id, over_payment, user_id=1)
        assert exc_over.value.detail == "Payment amount exceeds balance due"

        # 5. Payment on cancelled bill -> MUST return "Cannot collect payment on cancelled bill"
        cancelled_bill = Billing(
            bill_number=generate_bill_number(),
            patient_id=1,
            subtotal=100.0,
            gst_rate=0.0,
            total_amount=100.0,
            paid_amount=0.0,
            status=BillingStatus.CANCELLED,
            is_deleted=False,
            created_at=utc_now(),
        )
        session.add(cancelled_bill)
        await session.commit()
        await session.refresh(cancelled_bill)

        with pytest.raises(BadRequestException) as exc_cancel:
            await billing_service.collect_payment(cancelled_bill.id, payment_data, user_id=1)
        assert exc_cancel.value.detail == "Cannot collect payment on cancelled bill"

        # 6. Partial payment followed by duplicate request rejection
        partial_bill = Billing(
            bill_number=generate_bill_number(),
            patient_id=1,
            subtotal=500.0,
            gst_rate=0.0,
            total_amount=500.0,
            paid_amount=0.0,
            status=BillingStatus.PENDING,
            is_deleted=False,
            created_at=utc_now(),
        )
        session.add(partial_bill)
        await session.commit()
        await session.refresh(partial_bill)

        # First partial payment: amount = 1.0, CASH
        req1 = PaymentCreate(amount=1.0, payment_method="CASH")
        resp1 = await billing_service.collect_payment(partial_bill.id, req1, user_id=1)
        assert resp1 is not None
        assert resp1.amount == 1.0

        await session.refresh(partial_bill)
        assert partial_bill.paid_amount == 1.0

        # Duplicate request (exact same parameters: amount = 1.0, CASH) -> MUST fail with "Payment record already exists for this bill"
        req_dup = PaymentCreate(amount=1.0, payment_method="CASH")
        with pytest.raises(BadRequestException) as exc_dup:
            await billing_service.collect_payment(partial_bill.id, req_dup, user_id=1)
        assert exc_dup.value.detail == "Payment record already exists for this bill"
        assert exc_dup.value.detail != "Payment amount exceeds balance due"

        # Verify bill paid_amount is still 1.0 and no 2nd payment was added
        await session.refresh(partial_bill)
        assert partial_bill.paid_amount == 1.0

        # Legitimate non-duplicate partial payment: amount = 50.0, CARD -> SUCCEEDS
        req_valid_partial = PaymentCreate(amount=50.0, payment_method="CARD", transaction_ref="TXN_CARD_001")
        resp2 = await billing_service.collect_payment(partial_bill.id, req_valid_partial, user_id=1)
        assert resp2 is not None
        assert resp2.amount == 50.0

        await session.refresh(partial_bill)
        assert partial_bill.paid_amount == 51.0

        # Over-balance non-duplicate payment: amount = 1000.0, UPI -> fails with "Payment amount exceeds balance due"
        req_over_partial = PaymentCreate(amount=1000.0, payment_method="UPI", transaction_ref="TXN_UPI_999")
        with pytest.raises(BadRequestException) as exc_over_p:
            await billing_service.collect_payment(partial_bill.id, req_over_partial, user_id=1)
        assert exc_over_p.value.detail == "Payment amount exceeds balance due"

