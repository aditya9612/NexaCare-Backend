from datetime import date, datetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import BillingStatus
from app.core.exceptions import BadRequestException, NotFoundException
from app.models.billing_model import Payment
from app.repositories.audit_repository import AuditRepository
from app.repositories.billing_repository import BillingRepository
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.transaction_schema import TransactionCreate, TransactionUpdate, TransactionResponse
from app.services.billing_service import BillingService
from app.utils.helpers import utc_now
from app.utils.pagination import build_paginated_result


class TransactionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = TransactionRepository(db)
        self.billing_repo = BillingRepository(db)
        self.audit_repo = AuditRepository(db)

    async def create_transaction(self, data: TransactionCreate, user_id: int) -> TransactionResponse:
        billing = await self.billing_repo.get_by_id(data.billing_id)
        if not billing:
            raise NotFoundException("Billing record not found")

        if billing.status == BillingStatus.CANCELLED:
            raise BadRequestException("Cannot add transaction to a cancelled bill")

        is_refund = data.is_refund or False
        is_completed = data.status is None or data.status.lower() == "completed"

        if is_completed:
            if is_refund:
                if data.amount > billing.paid_amount:
                    raise BadRequestException("Refund amount exceeds paid amount")
                billing.paid_amount = round(billing.paid_amount - data.amount, 2)
            else:
                if data.amount > billing.balance_amount:
                    raise BadRequestException("Payment amount exceeds balance due")
                billing.paid_amount = round(billing.paid_amount + data.amount, 2)

        payment = Payment(
            billing_id=data.billing_id,
            amount=data.amount,
            payment_method=data.payment_method,
            transaction_ref=data.transaction_ref,
            payment_date=data.payment_date or utc_now(),
            status=data.status or "completed",
            is_refund=is_refund,
            refund_reason=data.refund_reason,
            received_by=user_id,
        )

        payment = await self.repo.create(payment)

        if is_completed:
            await BillingService(self.db)._recalculate_billing(billing)

        await self.audit_repo.create("create", "transaction", user_id=user_id, resource_id=str(payment.id))
        return TransactionResponse.model_validate(payment)

    async def get_transaction(self, transaction_id: int) -> TransactionResponse:
        payment = await self.repo.get_by_id(transaction_id)
        if not payment:
            raise NotFoundException("Transaction not found")
        return TransactionResponse.model_validate(payment)

    async def update_transaction(self, transaction_id: int, data: TransactionUpdate, user_id: int) -> TransactionResponse:
        payment = await self.repo.get_by_id(transaction_id)
        if not payment:
            raise NotFoundException("Transaction not found")

        billing = await self.billing_repo.get_by_id(payment.billing_id)
        if not billing:
            raise NotFoundException("Billing record not found")

        old_completed = payment.status.lower() == "completed"
        old_is_refund = payment.is_refund or False
        old_amount = payment.amount

        # Update the payment properties
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(payment, key, value)

        new_completed = payment.status.lower() == "completed"
        new_is_refund = payment.is_refund or False
        new_amount = payment.amount

        # Recalculate billing balance & status if completion or amount changed
        if old_completed or new_completed:
            temp_paid = billing.paid_amount
            if old_completed:
                if old_is_refund:
                    temp_paid = round(temp_paid + old_amount, 2)
                else:
                    temp_paid = round(temp_paid - old_amount, 2)

            if new_completed:
                if new_is_refund:
                    temp_paid = round(temp_paid - new_amount, 2)
                else:
                    temp_paid = round(temp_paid + new_amount, 2)

            if temp_paid < 0:
                raise BadRequestException("Invalid transaction update: paid amount cannot be negative")
            if temp_paid > round(billing.total_amount, 2):
                raise BadRequestException("Invalid transaction update: paid amount exceeds bill total amount")

            billing.paid_amount = temp_paid
            await BillingService(self.db)._recalculate_billing(billing)

        payment = await self.repo.update(payment)
        await self.audit_repo.create("update", "transaction", user_id=user_id, resource_id=str(payment.id))
        return TransactionResponse.model_validate(payment)

    async def delete_transaction(self, transaction_id: int, user_id: int) -> None:
        payment = await self.repo.get_by_id(transaction_id)
        if not payment:
            raise NotFoundException("Transaction not found")

        billing = await self.billing_repo.get_by_id(payment.billing_id)
        if not billing:
            raise NotFoundException("Billing record not found")

        if payment.status.lower() == "completed":
            if payment.is_refund:
                billing.paid_amount = round(billing.paid_amount + payment.amount, 2)
            else:
                billing.paid_amount = round(billing.paid_amount - payment.amount, 2)

            if billing.paid_amount < 0:
                billing.paid_amount = 0.0

            await BillingService(self.db)._recalculate_billing(billing)

        await self.repo.delete(payment)
        await self.audit_repo.create("delete", "transaction", user_id=user_id, resource_id=str(transaction_id))

    async def list_transactions(
        self,
        page: int = 1,
        size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        billing_id: int | None = None,
        payment_method: str | None = None,
        status: str | None = None,
        start_date: date | datetime | None = None,
        end_date: date | datetime | None = None,
        q: str | None = None,
    ):
        skip = (page - 1) * size
        items = await self.repo.list_all(
            skip=skip,
            limit=size,
            sort_by=sort_by,
            sort_order=sort_order,
            billing_id=billing_id,
            payment_method=payment_method,
            status=status,
            start_date=start_date,
            end_date=end_date,
            q=q,
        )
        total = await self.repo.count_all(
            billing_id=billing_id,
            payment_method=payment_method,
            status=status,
            start_date=start_date,
            end_date=end_date,
            q=q,
        )
        responses = [TransactionResponse.model_validate(item) for item in items]
        return build_paginated_result(responses, total, page, size)
