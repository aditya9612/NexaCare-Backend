import uuid
from datetime import date
import pytest
from app.core.database import AsyncSessionLocal
from app.core.exceptions import BadRequestException
from app.models.expense_model import ExpenseCategory, Expense
from app.models.vendor_model import Vendor
from app.schemas.expense_schema import VendorPaymentCreate
from app.services.expense_service import ExpenseService


@pytest.mark.asyncio
async def test_vendor_payment_duplicate_validation():
    uid = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        expense_service = ExpenseService(session)

        # 1. Create prerequisite Vendor & Expense Category
        vendor = Vendor(
            name=f"Test Vendor {uid}",
            vendor_type="supplier",
            is_active=True,
        )
        category = ExpenseCategory(
            name=f"Test Cat {uid}",
            description="Testing vendor payment validations",
            is_active=True,
        )
        session.add(vendor)
        session.add(category)
        await session.commit()
        await session.refresh(vendor)
        await session.refresh(category)

        # 2. Test Partial Payment followed by duplicate payment for the same expense
        # Create test Expense (amount: 500.0, Pending)
        expense = Expense(
            category_id=category.id,
            vendor_id=vendor.id,
            amount=500.0,
            description="Vendor Test Expense",
            expense_date=date.today(),
            status="Pending",
            is_deleted=False,
        )
        session.add(expense)
        await session.commit()
        await session.refresh(expense)

        # First payment: amount = 100.0 -> Succeeds
        payment_data1 = VendorPaymentCreate(
            vendor_id=vendor.id,
            expense_id=expense.id,
            amount=100.0,
            payment_method="cash",
        )
        payment_resp1 = await expense_service.create_payment(payment_data1, user_id=1)
        assert payment_resp1 is not None
        assert payment_resp1.amount == 100.0

        # Second identical/subsequent payment for the same expense -> MUST fail with "Payment record already exists for this expense"
        payment_data2 = VendorPaymentCreate(
            vendor_id=vendor.id,
            expense_id=expense.id,
            amount=100.0,
            payment_method="cash",
        )
        with pytest.raises(BadRequestException) as exc_info:
            await expense_service.create_payment(payment_data2, user_id=1)
        assert exc_info.value.detail == "Payment record already exists for this expense"
        assert exc_info.value.detail != "Payment amount exceeds remaining expense amount"

        # 3. Over-payment on an unpaid expense -> MUST fail with "Payment amount exceeds remaining expense amount"
        expense_over = Expense(
            category_id=category.id,
            vendor_id=vendor.id,
            amount=500.0,
            description="Unpaid Vendor Test Expense",
            expense_date=date.today(),
            status="Pending",
            is_deleted=False,
        )
        session.add(expense_over)
        await session.commit()
        await session.refresh(expense_over)

        over_payment_data = VendorPaymentCreate(
            vendor_id=vendor.id,
            expense_id=expense_over.id,
            amount=600.0,
            payment_method="cash",
        )
        with pytest.raises(BadRequestException) as exc_over:
            await expense_service.create_payment(over_payment_data, user_id=1)
        assert exc_over.value.detail == "Payment amount exceeds remaining expense amount"
