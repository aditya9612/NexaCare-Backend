from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, NotFoundException, ConflictException
from app.models.expense_model import ExpenseCategory, Expense, VendorPayment
from app.repositories.audit_repository import AuditRepository
from app.repositories.expense_repository import (
    ExpenseCategoryRepository,
    ExpenseRepository,
    VendorPaymentRepository
)
from app.repositories.vendor_repository import VendorRepository
from app.schemas.expense_schema import (
    ExpenseCategoryCreate, ExpenseCategoryUpdate, ExpenseCategoryResponse,
    ExpenseCreate, ExpenseUpdate, ExpenseResponse, ExpenseQuery,
    VendorPaymentCreate, VendorPaymentUpdate, VendorPaymentResponse,
    ExpenseSummaryResponse
)
from app.schemas.vendor_schema import VendorResponse
from app.utils.pagination import build_paginated_result


class ExpenseService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.category_repo = ExpenseCategoryRepository(db)
        self.vendor_repo = VendorRepository(db)
        self.expense_repo = ExpenseRepository(db)
        self.payment_repo = VendorPaymentRepository(db)
        self.audit_repo = AuditRepository(db)

    # --- Expense Category Services ---
    async def create_category(self, data: ExpenseCategoryCreate, user_id: int) -> ExpenseCategoryResponse:
        existing = await self.category_repo.get_by_name(data.name)
        if existing:
            raise ConflictException(f"Expense category with name '{data.name}' already exists")

        category = ExpenseCategory(**data.model_dump())
        category = await self.category_repo.create(category)
        await self.audit_repo.create("create", "expense_category", user_id=user_id, resource_id=str(category.id))
        return ExpenseCategoryResponse.model_validate(category)

    async def list_categories(self, page: int = 1, size: int = 20):
        skip = (page - 1) * size
        categories = await self.category_repo.list_all(skip=skip, limit=size)
        total = await self.category_repo.count_all()
        return build_paginated_result(
            [ExpenseCategoryResponse.model_validate(c) for c in categories], total, page, size
        )

    async def get_category(self, category_id: int) -> ExpenseCategoryResponse:
        category = await self.category_repo.get_by_id(category_id)
        if not category:
            raise NotFoundException(f"Expense category with ID {category_id} not found")
        return ExpenseCategoryResponse.model_validate(category)

    async def update_category(self, category_id: int, data: ExpenseCategoryUpdate, user_id: int) -> ExpenseCategoryResponse:
        category = await self.category_repo.get_by_id(category_id)
        if not category:
            raise NotFoundException(f"Expense category with ID {category_id} not found")

        if data.name:
            existing = await self.category_repo.get_by_name(data.name)
            if existing and existing.id != category_id:
                raise ConflictException(f"Expense category with name '{data.name}' already exists")

        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(category, key, value)

        category = await self.category_repo.update(category)
        await self.audit_repo.create("update", "expense_category", user_id=user_id, resource_id=str(category.id))
        return ExpenseCategoryResponse.model_validate(category)

    async def delete_category(self, category_id: int, user_id: int) -> None:
        category = await self.category_repo.get_by_id(category_id)
        if not category:
            raise NotFoundException(f"Expense category with ID {category_id} not found")

        expense_count = await self.expense_repo.count_all(category_id=category_id)
        if expense_count > 0:
            raise BadRequestException("Cannot delete category as it is linked to one or more expenses")

        await self.category_repo.soft_delete(category)
        await self.audit_repo.create("delete", "expense_category", user_id=user_id, resource_id=str(category.id))

    # --- Vendor Services Removed (Centralized in VendorService) ---

    # --- Expense Services ---
    async def create_expense(self, data: ExpenseCreate, user_id: int) -> ExpenseResponse:
        # Validate Category
        category = await self.category_repo.get_by_id(data.category_id)
        if not category:
            raise NotFoundException(f"Expense category with ID {data.category_id} not found")

        # Validate Vendor
        if data.vendor_id is not None:
            vendor = await self.vendor_repo.get_by_id(data.vendor_id)
            if not vendor:
                raise NotFoundException(f"Vendor with ID {data.vendor_id} not found")

        expense = Expense(**data.model_dump())
        expense = await self.expense_repo.create(expense)
        await self.audit_repo.create("create", "expense", user_id=user_id, resource_id=str(expense.id))

        from app.services.transaction_history_service import TransactionHistoryService
        await TransactionHistoryService(self.db).create_event(
            event_type="EXPENSE_RECORDED",
            reference_no=f"EXP-{expense.id}",
            description=f"Expense Recorded: {expense.description or ''}",
            amount=expense.amount,
            source_module="expenses",
            source_id=expense.id,
            status="completed",
            user_id=user_id
        )

        return ExpenseResponse.model_validate(expense)

    async def list_expenses(self, query: ExpenseQuery):
        skip = (query.page - 1) * query.size
        expenses = await self.expense_repo.list_all(
            skip=skip,
            limit=query.size,
            sort_by=query.sort_by,
            sort_order=query.sort_order,
            category_id=query.category_id,
            vendor_id=query.vendor_id,
            status=query.status,
            start_date=query.start_date,
            end_date=query.end_date,
            description=query.description
        )
        total = await self.expense_repo.count_all(
            category_id=query.category_id,
            vendor_id=query.vendor_id,
            status=query.status,
            start_date=query.start_date,
            end_date=query.end_date,
            description=query.description
        )
        return build_paginated_result(
            [ExpenseResponse.model_validate(e) for e in expenses], total, query.page, query.size
        )

    async def get_expense(self, expense_id: int) -> ExpenseResponse:
        expense = await self.expense_repo.get_by_id(expense_id)
        if not expense:
            raise NotFoundException(f"Expense with ID {expense_id} not found")
        return ExpenseResponse.model_validate(expense)

    async def update_expense(self, expense_id: int, data: ExpenseUpdate, user_id: int) -> ExpenseResponse:
        expense = await self.expense_repo.get_by_id(expense_id)
        if not expense:
            raise NotFoundException(f"Expense with ID {expense_id} not found")

        if data.category_id is not None:
            category = await self.category_repo.get_by_id(data.category_id)
            if not category:
                raise NotFoundException(f"Expense category with ID {data.category_id} not found")

        if data.vendor_id is not None:
            vendor = await self.vendor_repo.get_by_id(data.vendor_id)
            if not vendor:
                raise NotFoundException(f"Vendor with ID {data.vendor_id} not found")

        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(expense, key, value)

        expense = await self.expense_repo.update(expense)
        if "status" not in data.model_fields_set:
            await self._update_expense_status(expense.id)
        # Re-fetch with loaded relationships
        expense = await self.expense_repo.get_by_id(expense.id)
        await self.audit_repo.create("update", "expense", user_id=user_id, resource_id=str(expense.id))

        # Sync transaction history
        from sqlalchemy import select
        from app.models.transaction_history_model import TransactionHistory
        stmt = select(TransactionHistory).where(
            TransactionHistory.source_module == "expenses",
            TransactionHistory.source_id == expense.id,
            TransactionHistory.is_deleted.is_(False)
        )
        tx_result = await self.db.execute(stmt)
        tx_history = tx_result.scalar_one_or_none()

        from datetime import datetime, time
        event_datetime = datetime.combine(expense.expense_date, time.min)

        if tx_history:
            tx_history.amount = expense.amount
            tx_history.description = f"Expense Recorded: {expense.description or ''}"
            tx_history.event_date = event_datetime
            tx_history.status = expense.status
            from app.repositories.transaction_history_repository import TransactionHistoryRepository
            await TransactionHistoryRepository(self.db).update(tx_history)
        else:
            from app.services.transaction_history_service import TransactionHistoryService
            await TransactionHistoryService(self.db).create_event(
                event_type="EXPENSE_RECORDED",
                reference_no=f"EXP-{expense.id}",
                description=f"Expense Recorded: {expense.description or ''}",
                amount=expense.amount,
                source_module="expenses",
                source_id=expense.id,
                status=expense.status,
                event_date=event_datetime,
                user_id=user_id
            )

        return ExpenseResponse.model_validate(expense)

    async def delete_expense(self, expense_id: int, user_id: int) -> None:
        expense = await self.expense_repo.get_by_id(expense_id)
        if not expense:
            raise NotFoundException(f"Expense with ID {expense_id} not found")

        await self.expense_repo.soft_delete(expense)
        await self.audit_repo.create("delete", "expense", user_id=user_id, resource_id=str(expense.id))

    async def get_expense_summary(self, start_date: date | None = None, end_date: date | None = None) -> ExpenseSummaryResponse:
        summary = await self.expense_repo.get_summary(start_date, end_date)
        return ExpenseSummaryResponse.model_validate(summary)

    # --- Vendor Payment Services ---
    async def create_payment(self, data: VendorPaymentCreate, user_id: int) -> VendorPaymentResponse:
        # Validate vendor
        vendor = await self.vendor_repo.get_by_id(data.vendor_id)
        if not vendor:
            raise NotFoundException(f"Vendor with ID {data.vendor_id} not found")

        # Validate expense
        expense = await self.expense_repo.get_by_id(data.expense_id)
        if not expense:
            raise NotFoundException(f"Expense with ID {data.expense_id} not found")

        payment = VendorPayment(**data.model_dump())
        payment = await self.payment_repo.create(payment)

        # Update expense status
        await self._update_expense_status(expense.id)

        await self.audit_repo.create("create", "vendor_payment", user_id=user_id, resource_id=str(payment.id))
        return VendorPaymentResponse.model_validate(payment)

    async def list_payments(self, page: int = 1, size: int = 20, vendor_id: int | None = None, expense_id: int | None = None):
        skip = (page - 1) * size
        payments = await self.payment_repo.list_all(skip=skip, limit=size, vendor_id=vendor_id, expense_id=expense_id)
        total = await self.payment_repo.count_all(vendor_id=vendor_id, expense_id=expense_id)
        return build_paginated_result(
            [VendorPaymentResponse.model_validate(p) for p in payments], total, page, size
        )

    async def get_payment(self, payment_id: int) -> VendorPaymentResponse:
        payment = await self.payment_repo.get_by_id(payment_id)
        if not payment:
            raise NotFoundException(f"Vendor payment with ID {payment_id} not found")
        return VendorPaymentResponse.model_validate(payment)

    async def update_payment(self, payment_id: int, data: VendorPaymentUpdate, user_id: int) -> VendorPaymentResponse:
        payment = await self.payment_repo.get_by_id(payment_id)
        if not payment:
            raise NotFoundException(f"Vendor payment with ID {payment_id} not found")

        old_expense_id = payment.expense_id

        if data.vendor_id is not None:
            vendor = await self.vendor_repo.get_by_id(data.vendor_id)
            if not vendor:
                raise NotFoundException(f"Vendor with ID {data.vendor_id} not found")

        if data.expense_id is not None:
            expense = await self.expense_repo.get_by_id(data.expense_id)
            if not expense:
                raise NotFoundException(f"Expense with ID {data.expense_id} not found")

        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(payment, key, value)

        payment = await self.payment_repo.update(payment)

        # Update old and new expense statuses
        await self._update_expense_status(old_expense_id)
        if payment.expense_id != old_expense_id:
            await self._update_expense_status(payment.expense_id)

        await self.audit_repo.create("update", "vendor_payment", user_id=user_id, resource_id=str(payment.id))
        return VendorPaymentResponse.model_validate(payment)

    async def delete_payment(self, payment_id: int, user_id: int) -> None:
        payment = await self.payment_repo.get_by_id(payment_id)
        if not payment:
            raise NotFoundException(f"Vendor payment with ID {payment_id} not found")

        expense_id = payment.expense_id
        await self.payment_repo.soft_delete(payment)

        # Recalculate expense status
        await self._update_expense_status(expense_id)

        await self.audit_repo.create("delete", "vendor_payment", user_id=user_id, resource_id=str(payment.id))

    # --- Private Helper Methods ---
    async def _update_expense_status(self, expense_id: int) -> None:
        expense = await self.expense_repo.get_by_id(expense_id)
        if not expense:
            return

        payments = await self.payment_repo.get_payments_by_expense(expense_id)
        total_paid = sum(p.amount for p in payments)

        new_status = "Paid" if total_paid >= expense.amount else "Pending"
        if expense.status != new_status:
            expense.status = new_status
            await self.expense_repo.update(expense)
