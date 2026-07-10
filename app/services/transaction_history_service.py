from datetime import date, datetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.models.transaction_history_model import TransactionHistory
from app.repositories.audit_repository import AuditRepository
from app.repositories.transaction_history_repository import TransactionHistoryRepository
from app.schemas.transaction_history_schema import (
    TransactionHistoryCreate,
    TransactionHistoryResponse,
    DashboardSummaryResponse,
)
from app.utils.helpers import utc_now
from app.utils.pagination import build_paginated_result


class TransactionHistoryService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = TransactionHistoryRepository(db)
        self.audit_repo = AuditRepository(db)

    async def create_transaction_history(
        self, data: TransactionHistoryCreate, user_id: int
    ) -> TransactionHistoryResponse:
        tx_history = TransactionHistory(
            event_type=data.event_type.strip().upper(),
            reference_no=data.reference_no.strip(),
            description=data.description,
            amount=data.amount,
            status=data.status or "completed",
            source_module=data.source_module.strip().lower(),
            source_id=data.source_id,
            event_date=data.event_date or utc_now(),
        )
        tx_history = await self.repo.create(tx_history)
        await self.audit_repo.create("create", "transaction_history", user_id=user_id, resource_id=str(tx_history.id))
        return TransactionHistoryResponse.model_validate(tx_history)

    async def create_event(
        self,
        event_type: str,
        reference_no: str,
        description: str | None,
        amount: float,
        source_module: str,
        source_id: int,
        status: str = "completed",
        event_date: datetime | None = None,
        user_id: int | None = None,
    ) -> TransactionHistory:
        tx_history = TransactionHistory(
            event_type=event_type.strip().upper(),
            reference_no=reference_no.strip(),
            description=description,
            amount=amount,
            status=status,
            source_module=source_module.strip().lower(),
            source_id=source_id,
            event_date=event_date or utc_now(),
        )
        tx_history = await self.repo.create(tx_history)
        await self.audit_repo.create("create", "transaction_history", user_id=user_id or 1, resource_id=str(tx_history.id))
        return tx_history

    async def _sync_pharmacy_transactions(self) -> None:
        from app.models.pharmacy_model import PharmacyInvoice, Purchase
        from sqlalchemy import select
        
        # Sync Invoices
        invoice_query = select(PharmacyInvoice).outerjoin(
            TransactionHistory,
            (TransactionHistory.source_module == "pharmacy_billing") &
            (TransactionHistory.source_id == PharmacyInvoice.id) &
            (TransactionHistory.is_deleted == False)
        ).where(
            TransactionHistory.id.is_(None),
            PharmacyInvoice.is_deleted == False
        )
        invoice_result = await self.db.execute(invoice_query)
        invoices_to_sync = invoice_result.scalars().all()
        
        for invoice in invoices_to_sync:
            # Create INVOICE_CREATED
            self.db.add(TransactionHistory(
                event_type="INVOICE_CREATED",
                reference_no=invoice.invoice_number,
                description=f"Pharmacy Invoice Created: {invoice.invoice_number}",
                amount=invoice.total_amount,
                source_module="pharmacy_billing",
                source_id=invoice.id,
                status="completed",
                event_date=invoice.created_at or utc_now(),
                created_at=invoice.created_at or utc_now(),
                updated_at=invoice.updated_at or utc_now()
            ))
            # Create PAYMENT_RECEIVED
            self.db.add(TransactionHistory(
                event_type="PAYMENT_RECEIVED",
                reference_no=invoice.invoice_number,
                description=f"Pharmacy Invoice Paid: {invoice.invoice_number}",
                amount=invoice.total_amount,
                source_module="pharmacy_billing",
                source_id=invoice.id,
                status="completed",
                event_date=invoice.created_at or utc_now(),
                created_at=invoice.created_at or utc_now(),
                updated_at=invoice.updated_at or utc_now()
            ))

        # Sync Purchases
        purchase_query = select(Purchase).outerjoin(
            TransactionHistory,
            (TransactionHistory.source_module == "pharmacy_purchases") &
            (TransactionHistory.source_id == Purchase.id) &
            (TransactionHistory.is_deleted == False)
        ).where(
            TransactionHistory.id.is_(None)
        )
        purchase_result = await self.db.execute(purchase_query)
        purchases_to_sync = purchase_result.scalars().all()
        
        for purchase in purchases_to_sync:
            self.db.add(TransactionHistory(
                event_type="EXPENSE_RECORDED",
                reference_no=purchase.purchase_number,
                description=f"Pharmacy Purchase: {purchase.purchase_number}",
                amount=purchase.total_amount,
                source_module="pharmacy_purchases",
                source_id=purchase.id,
                status="completed",
                event_date=purchase.created_at or utc_now(),
                created_at=purchase.created_at or utc_now(),
                updated_at=purchase.updated_at or utc_now()
            ))

        if invoices_to_sync or purchases_to_sync:
            await self.db.flush()

    async def list_transaction_histories(
        self,
        page: int = 1,
        size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        event_type: str | None = None,
        status: str | None = None,
        start_date: date | datetime | None = None,
        end_date: date | datetime | None = None,
        reference_no: str | None = None,
        q: str | None = None,
    ):
        await self._sync_pharmacy_transactions()
        skip = (page - 1) * size
        items = await self.repo.list_all(
            skip=skip,
            limit=size,
            sort_by=sort_by,
            sort_order=sort_order,
            event_type=event_type,
            status=status,
            start_date=start_date,
            end_date=end_date,
            reference_no=reference_no,
            q=q,
        )
        total = await self.repo.count_all(
            event_type=event_type,
            status=status,
            start_date=start_date,
            end_date=end_date,
            reference_no=reference_no,
            q=q,
        )
        responses = [TransactionHistoryResponse.model_validate(item) for item in items]
        return build_paginated_result(responses, total, page, size)

    async def get_transaction_history(self, tx_id: int) -> TransactionHistoryResponse:
        tx_history = await self.repo.get_by_id(tx_id)
        if not tx_history:
            raise NotFoundException("Transaction History record not found")
        return TransactionHistoryResponse.model_validate(tx_history)

    async def delete_transaction_history(self, tx_id: int, user_id: int) -> None:
        tx_history = await self.repo.get_by_id(tx_id)
        if not tx_history:
            raise NotFoundException("Transaction History record not found")
        await self.repo.soft_delete(tx_history)
        await self.audit_repo.create("delete", "transaction_history", user_id=user_id, resource_id=str(tx_id))

    async def get_dashboard_summary(self) -> DashboardSummaryResponse:
        await self._sync_pharmacy_transactions()
        stats = await self.repo.get_aggregated_stats()

        totals = {
            "EXPENSE_RECORDED": 0.0,
            "INVOICE_CREATED": 0.0,
            "PAYMENT_RECEIVED": 0.0,
            "INSURANCE_CLAIM": 0.0,
            "REFUND_ISSUED": 0.0,
        }
        counts = {
            "EXPENSE_RECORDED": 0,
            "INVOICE_CREATED": 0,
            "PAYMENT_RECEIVED": 0,
            "INSURANCE_CLAIM": 0,
            "REFUND_ISSUED": 0,
        }

        for event_type, amt, count in stats:
            upper_event = event_type.upper()
            totals[upper_event] = amt
            counts[upper_event] = count

        total_income = totals["PAYMENT_RECEIVED"]
        total_expense = totals["EXPENSE_RECORDED"]
        total_refunds = totals["REFUND_ISSUED"]
        net_cash_flow = total_income - total_expense - total_refunds
        total_receivables = max(0.0, totals["INVOICE_CREATED"] - total_income)

        return DashboardSummaryResponse(
            total_income=total_income,
            total_expense=total_expense,
            net_cash_flow=net_cash_flow,
            total_refunds=total_refunds,
            total_receivables=total_receivables,
            event_counts=counts,
        )
