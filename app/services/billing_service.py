from datetime import date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import BillingStatus
from app.core.exceptions import BadRequestException, NotFoundException
from app.models.billing_model import BillItem, Billing, Insurance, InsuranceClaim, Payment
from app.repositories.audit_repository import AuditRepository
from app.repositories.billing_repository import BillingRepository, InsuranceClaimRepository, InsuranceRepository
from app.repositories.patient_repository import PatientRepository
from app.schemas.billing_schema import (
    BillingCreate,
    BillingResponse,
    BillingSummary,
    BillingUpdate,
    BillItemResponse,
    DailyCollectionSummary,
    InsuranceClaimCreate,
    InsuranceClaimResponse,
    InsuranceCreate,
    InsuranceResponse,
    PaymentCreate,
    PaymentResponse,
    RefundCreate,
    RevenueReport,
)
from app.utils.helpers import (
    calculate_bill_totals,
    calculate_line_total,
    generate_bill_number,
    generate_claim_number,
    utc_now,
)
from app.utils.pagination import build_paginated_result
from app.utils.pdf_generator import generate_invoice_html


class BillingService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = BillingRepository(db)
        self.patient_repo = PatientRepository(db)
        self.audit_repo = AuditRepository(db)

    def _to_response(self, billing: Billing) -> BillingResponse:
        data = BillingResponse.model_validate(billing)
        data.items = [BillItemResponse.model_validate(i) for i in billing.items]
        return data

    async def _recalculate_billing(self, billing: Billing) -> Billing:
        subtotal = sum(
            (item.quantity * item.unit_price) for item in billing.items
        ) if billing.items else billing.subtotal
        totals = calculate_bill_totals(
            subtotal=subtotal,
            discount_percent=billing.discount_percent,
            discount_amount=billing.discount_amount,
            gst_rate=billing.gst_rate,
            tax_amount=billing.tax_amount,
        )
        billing.subtotal = totals["subtotal"]
        billing.discount_amount = totals["discount_amount"]
        billing.gst_amount = totals["gst_amount"]
        billing.tax_amount = totals["tax_amount"]
        billing.total_amount = totals["total_amount"]
        billing.balance_amount = round(billing.total_amount - billing.paid_amount, 2)
        if billing.balance_amount <= 0:
            billing.status = BillingStatus.PAID
        elif billing.paid_amount > 0:
            billing.status = BillingStatus.PARTIAL
        elif billing.due_date and billing.due_date < utc_now():
            billing.status = BillingStatus.OVERDUE
        else:
            billing.status = BillingStatus.PENDING
        return await self.repo.update(billing)

    async def create(self, data: BillingCreate, user_id: int) -> BillingResponse:
        patient = await self.patient_repo.get_by_id(data.patient_id)
        if not patient:
            raise NotFoundException("Patient not found")

        billing = Billing(
            patient_id=data.patient_id,
            bill_number=generate_bill_number(),
            discount_percent=data.discount_percent,
            discount_amount=data.discount_amount,
            gst_rate=data.gst_rate,
            tax_amount=data.tax_amount,
            due_date=data.due_date,
            notes=data.notes,
            insurance_id=data.insurance_id,
            created_by=user_id,
        )
        billing = await self.repo.create(billing)

        subtotal = 0.0
        for item_data in data.items:
            _, gst_amt, line_total = calculate_line_total(
                item_data.quantity, item_data.unit_price, item_data.gst_rate
            )
            item = BillItem(
                billing_id=billing.id,
                description=item_data.description,
                quantity=item_data.quantity,
                unit_price=item_data.unit_price,
                gst_rate=item_data.gst_rate,
                gst_amount=gst_amt,
                line_total=line_total,
                item_type=item_data.item_type,
            )
            await self.repo.add_item(item)
            subtotal += item_data.quantity * item_data.unit_price

        billing.subtotal = subtotal
        billing = await self._recalculate_billing(billing)
        billing = await self.repo.get_by_id(billing.id)
        await self.audit_repo.create("create", "billing", user_id=user_id, resource_id=str(billing.id))
        return self._to_response(billing)

    async def list_billings(
        self, page: int = 1, size: int = 20, sort_by: str = "created_at",
        sort_order: str = "desc", status: str | None = None, patient_id: int | None = None,
    ):
        skip = (page - 1) * size
        items = await self.repo.list_all(skip=skip, limit=size, sort_by=sort_by, sort_order=sort_order,
                                         status=status, patient_id=patient_id)
        total = await self.repo.count_all(status=status, patient_id=patient_id)
        return build_paginated_result([self._to_response(b) for b in items], total, page, size)

    async def search(self, q: str, page: int = 1, size: int = 20, status: str | None = None):
        skip = (page - 1) * size
        items = await self.repo.search(q, skip=skip, limit=size, status=status)
        total = await self.repo.count_search(q, status=status)
        return build_paginated_result([self._to_response(b) for b in items], total, page, size)

    async def get_by_id(self, billing_id: int) -> BillingResponse:
        billing = await self.repo.get_by_id(billing_id)
        if not billing:
            raise NotFoundException("Billing record not found")
        return self._to_response(billing)

    async def update(self, billing_id: int, data: BillingUpdate, user_id: int) -> BillingResponse:
        billing = await self.repo.get_by_id(billing_id)
        if not billing:
            raise NotFoundException("Billing record not found")
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(billing, key, value)
        billing = await self._recalculate_billing(billing)
        billing = await self.repo.get_by_id(billing.id)
        await self.audit_repo.create("update", "billing", user_id=user_id, resource_id=str(billing.id))
        return self._to_response(billing)

    async def delete(self, billing_id: int, user_id: int) -> None:
        billing = await self.repo.get_by_id(billing_id)
        if not billing:
            raise NotFoundException("Billing record not found")
        await self.repo.soft_delete(billing)
        await self.audit_repo.create("delete", "billing", user_id=user_id, resource_id=str(billing.id))

    async def collect_payment(self, billing_id: int, data: PaymentCreate, user_id: int) -> PaymentResponse:
        billing = await self.repo.get_by_id(billing_id)
        if not billing:
            raise NotFoundException("Billing record not found")
        if billing.status == BillingStatus.CANCELLED:
            raise BadRequestException("Cannot collect payment on cancelled bill")
        if data.amount > billing.balance_amount:
            raise BadRequestException("Payment amount exceeds balance due")

        payment = Payment(
            billing_id=billing_id,
            amount=data.amount,
            payment_method=data.payment_method,
            transaction_ref=data.transaction_ref,
            payment_date=utc_now(),
            received_by=user_id,
        )
        payment = await self.repo.add_payment(payment)
        billing.paid_amount = round(billing.paid_amount + data.amount, 2)
        await self._recalculate_billing(billing)
        await self.audit_repo.create("payment", "billing", user_id=user_id, resource_id=str(billing_id))
        return PaymentResponse.model_validate(payment)

    async def process_refund(self, billing_id: int, data: RefundCreate, user_id: int) -> PaymentResponse:
        billing = await self.repo.get_by_id(billing_id)
        if not billing:
            raise NotFoundException("Billing record not found")
        if data.amount > billing.paid_amount:
            raise BadRequestException("Refund amount exceeds paid amount")

        payment = Payment(
            billing_id=billing_id,
            amount=data.amount,
            payment_method="refund",
            payment_date=utc_now(),
            is_refund=True,
            refund_reason=data.refund_reason,
            received_by=user_id,
            status="completed",
        )
        payment = await self.repo.add_payment(payment)
        billing.paid_amount = round(billing.paid_amount - data.amount, 2)
        billing = await self._recalculate_billing(billing)
        if billing.paid_amount == 0 and billing.balance_amount > 0:
            billing.status = BillingStatus.PENDING
        await self.audit_repo.create("refund", "billing", user_id=user_id, resource_id=str(billing_id))
        return PaymentResponse.model_validate(payment)

    async def generate_invoice(self, billing_id: int, user_id: int) -> str:
        billing = await self.repo.get_by_id(billing_id)
        if not billing:
            raise NotFoundException("Billing record not found")
        patient = await self.patient_repo.get_by_id(billing.patient_id)
        patient_name = f"{patient.first_name} {patient.last_name}" if patient else "N/A"
        items = [
            {"description": i.description, "amount": f"{i.line_total:.2f}"}
            for i in billing.items
        ]
        path = await generate_invoice_html(
            billing.bill_number,
            {
                "patient_name": patient_name,
                "date": utc_now().strftime("%Y-%m-%d"),
                "items": items,
                "total_amount": f"{billing.total_amount:.2f}",
            },
        )
        billing.invoice_path = path
        await self.repo.update(billing)
        await self.audit_repo.create("export", "billing", user_id=user_id, resource_id=str(billing.id))
        return path

    async def get_pending_payments(self, page: int = 1, size: int = 20):
        skip = (page - 1) * size
        items = await self.repo.get_pending_payments(skip=skip, limit=size)
        total = await self.repo.count_pending_payments()
        return build_paginated_result([self._to_response(b) for b in items], total, page, size)

    async def get_revenue_summary(self) -> BillingSummary:
        data = await self.repo.get_revenue_summary()
        return BillingSummary(**data)

    async def get_daily_report(self, target_date: date | None = None) -> DailyCollectionSummary:
        target = target_date or date.today()
        data = await self.repo.get_daily_collection(target)
        return DailyCollectionSummary(date=str(target), **data)

    async def get_period_report(self, period: str) -> RevenueReport:
        now = utc_now()
        if period == "daily":
            start = datetime.combine(now.date(), datetime.min.time())
            end = now
            label = str(now.date())
        elif period == "monthly":
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end = now
            label = start.strftime("%Y-%m")
        else:
            start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            end = now
            label = str(now.year)
        data = await self.repo.get_period_report(start, end)
        return RevenueReport(period=label, **data)


class InsuranceService:
    def __init__(self, db: AsyncSession):
        self.repo = InsuranceRepository(db)
        self.claim_repo = InsuranceClaimRepository(db)
        self.audit_repo = AuditRepository(db)

    async def create_insurance(self, data: InsuranceCreate, user_id: int) -> InsuranceResponse:
        insurance = Insurance(**data.model_dump())
        insurance = await self.repo.create(insurance)
        await self.audit_repo.create("create", "billing_insurance", user_id=user_id, resource_id=str(insurance.id))
        return InsuranceResponse.model_validate(insurance)

    async def submit_claim(self, data: InsuranceClaimCreate, user_id: int) -> InsuranceClaimResponse:
        claim = InsuranceClaim(
            claim_number=generate_claim_number(),
            submitted_at=utc_now(),
            **data.model_dump(),
        )
        claim = await self.claim_repo.create(claim)
        await self.audit_repo.create("create", "billing_claim", user_id=user_id, resource_id=str(claim.id))
        return InsuranceClaimResponse.model_validate(claim)
