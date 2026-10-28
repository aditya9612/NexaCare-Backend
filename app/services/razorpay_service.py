import asyncio
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import razorpay
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import BillingStatus, AppointmentStatus
from app.core.dependencies import resolve_tenant_id
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.models.billing_model import Billing, Payment
from app.models.discharge_model import Discharge
from app.models.final_bill_model import IPDFinalBill
from app.models.payment_order_model import RazorpayOrder, RazorpayWebhookEvent
from app.models.pharmacy_model import PharmacyInvoice, Prescription
from app.models.user_model import User
from app.schemas.payment_order_schema import (
    PaymentVerifyResponse,
    RazorpayOrderCreateRequest,
    RazorpayOrderResponse,
    RazorpayVerifyRequest,
    RazorpayWebhookResponse,
)
from app.services.patient_service import PatientService
from app.services.transaction_history_service import TransactionHistoryService
from app.repositories.audit_repository import AuditRepository
from app.utils.helpers import utc_now

logger = logging.getLogger(__name__)


class RazorpayService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.client = razorpay.Client(
            auth=(settings.RAZORPAY_KEY_ID or "", settings.RAZORPAY_KEY_SECRET or "")
        )
        self.audit_repo = AuditRepository(db)
        self.tx_service = TransactionHistoryService(db)

    async def _run_sync(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Run synchronous Razorpay SDK call in the worker thread pool."""
        return await asyncio.to_thread(func, *args, **kwargs)

    # -------------------------------------------------------------------------
    # 1. CREATE RAZORPAY ORDER
    # -------------------------------------------------------------------------
    async def create_order(
        self, data: RazorpayOrderCreateRequest, current_user: User
    ) -> RazorpayOrderResponse:
        if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
            raise BadRequestException("Razorpay gateway credentials are not configured. Please set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET.")

        hospital_id = resolve_tenant_id(current_user)
        bill_type = data.bill_type.lower()
        if bill_type in ("consultation", "billing"):
            bill_type = "opd"
        elif bill_type in ("ipd_final", "ipd_billing", "ipd-final", "ipd-bill", "ipd_bill"):
            bill_type = "ipd"
        bill_id = data.bill_id

        # Patient ownership check
        await self._verify_patient_ownership(bill_type, bill_id, current_user)

        # Re-fetch bill with row lock and calculate current Decimal balance
        bill_record, balance_due = await self._get_bill_and_balance(
            bill_type, bill_id, hospital_id, for_update=True
        )
        bill_id = bill_record.id

        if balance_due <= Decimal("0.00"):
            raise BadRequestException("Bill is already fully paid or has zero balance")

        amount_paise = int(
            (balance_due * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        amount_inr = balance_due.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # Idempotency check: look for active, unpaid order for this bill & exact amount
        existing_stmt = select(RazorpayOrder).where(
            RazorpayOrder.bill_type == bill_type,
            RazorpayOrder.bill_id == bill_id,
            RazorpayOrder.amount_paise == amount_paise,
            RazorpayOrder.status == "created",
        )
        if hospital_id is not None:
            existing_stmt = existing_stmt.where(RazorpayOrder.hospital_id == hospital_id)

        existing_order = (await self.db.scalars(existing_stmt)).first()
        if existing_order:
            return RazorpayOrderResponse(
                key_id=settings.RAZORPAY_KEY_ID or "",
                order_id=existing_order.razorpay_order_id,
                amount_inr=float(existing_order.amount_inr),
                amount_paise=existing_order.amount_paise,
                currency=existing_order.currency,
                bill_type=existing_order.bill_type,
                bill_id=existing_order.bill_id,
                local_order_id=existing_order.id,
            )

        # Create order in Razorpay using SDK in thread pool
        receipt_id = f"rcpt_{bill_type[:3]}_{bill_id}_{int(datetime.now(timezone.utc).timestamp())}"
        order_payload = {
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt_id,
            "notes": {
                "bill_type": bill_type,
                "bill_id": str(bill_id),
                "hospital_id": str(hospital_id or ""),
            },
        }

        try:
            rp_order = await self._run_sync(self.client.order.create, data=order_payload)
        except Exception as exc:
            logger.error("Failed to create Razorpay order: %s", exc, exc_info=True)
            raise BadRequestException(f"Failed to create payment order with gateway: {str(exc)}")

        rp_order_id = rp_order.get("id")
        if not rp_order_id:
            raise BadRequestException("Invalid response received from Razorpay")

        # Persist local RazorpayOrder
        local_order = RazorpayOrder(
            hospital_id=hospital_id,
            bill_type=bill_type,
            bill_id=bill_id,
            razorpay_order_id=rp_order_id,
            amount_paise=amount_paise,
            amount_inr=amount_inr,
            currency="INR",
            status="created",
            created_by=current_user.id if current_user else None,
        )
        self.db.add(local_order)
        await self.db.flush()

        return RazorpayOrderResponse(
            key_id=settings.RAZORPAY_KEY_ID or "",
            order_id=local_order.razorpay_order_id,
            amount_inr=float(local_order.amount_inr),
            amount_paise=local_order.amount_paise,
            currency=local_order.currency,
            bill_type=local_order.bill_type,
            bill_id=local_order.bill_id,
            local_order_id=local_order.id,
        )

    # -------------------------------------------------------------------------
    # 2. VERIFY CHECKOUT PAYMENT
    # -------------------------------------------------------------------------
    async def verify_payment(
        self, data: RazorpayVerifyRequest, current_user: User
    ) -> PaymentVerifyResponse:
        if not settings.RAZORPAY_KEY_SECRET:
            raise BadRequestException("Razorpay gateway secret is not configured. Please set RAZORPAY_KEY_SECRET.")

        hospital_id = resolve_tenant_id(current_user)

        # Fetch local order under row-lock
        order_stmt = (
            select(RazorpayOrder)
            .where(RazorpayOrder.razorpay_order_id == data.razorpay_order_id)
            .with_for_update()
        )
        if hospital_id is not None:
            order_stmt = order_stmt.where(RazorpayOrder.hospital_id == hospital_id)

        order = (await self.db.scalars(order_stmt)).first()
        if not order:
            raise NotFoundException("Payment order not found or unauthorized")

        # Patient ownership check
        await self._verify_patient_ownership(order.bill_type, order.bill_id, current_user)

        # Idempotent return if already settled
        if order.status in ("paid", "reconciliation_required") and order.razorpay_payment_id == data.razorpay_payment_id:
            is_fully_paid = order.status == "paid" and (order.excess_amount_inr or Decimal("0.00")) == Decimal("0.00")
            return PaymentVerifyResponse(
                status=order.status,
                message="Payment already verified and settled",
                payment_id=order.razorpay_payment_id,
                bill_type=order.bill_type,
                bill_id=order.bill_id,
                is_fully_paid=is_fully_paid,
                settled_amount=float(order.settled_amount_inr or order.amount_inr),
                excess_amount=float(order.excess_amount_inr or Decimal("0.00")),
            )

        # 1. Verify HMAC Checkout Signature via SDK utility in thread pool
        sig_data = {
            "razorpay_order_id": data.razorpay_order_id,
            "razorpay_payment_id": data.razorpay_payment_id,
            "razorpay_signature": data.razorpay_signature,
        }
        try:
            await self._run_sync(self.client.utility.verify_payment_signature, sig_data)
        except Exception:
            order.status = "failed"
            order.signature = data.razorpay_signature
            order.error_reason = "Invalid checkout signature"
            await self.db.flush()
            raise BadRequestException("Invalid payment signature")

        # 2. Fetch Server-Side Payment Status from Razorpay SDK
        try:
            rp_payment = await self._run_sync(self.client.payment.fetch, data.razorpay_payment_id)
        except Exception as exc:
            logger.error("Failed to fetch Razorpay payment %s: %s", data.razorpay_payment_id, exc)
            raise BadRequestException("Could not verify payment status with gateway")

        # Validate payment attributes match order
        if rp_payment.get("order_id") != data.razorpay_order_id:
            raise BadRequestException("Payment does not belong to this order")

        if rp_payment.get("currency") != "INR":
            raise BadRequestException("Unsupported currency: currency must be INR")

        if rp_payment.get("amount") != order.amount_paise:
            raise BadRequestException("Payment amount mismatch with order amount")

        payment_status = str(rp_payment.get("status", "")).lower()

        # Handle non-captured states
        if payment_status == "authorized":
            order.status = "authorized"
            order.razorpay_payment_id = data.razorpay_payment_id
            order.signature = data.razorpay_signature
            await self.db.flush()
            return PaymentVerifyResponse(
                status="authorized",
                message="Payment is authorized but pending gateway capture. Bill settlement will occur upon capture.",
                payment_id=data.razorpay_payment_id,
                bill_type=order.bill_type,
                bill_id=order.bill_id,
                is_fully_paid=False,
                settled_amount=0.0,
                excess_amount=0.0,
            )

        if payment_status == "pending":
            order.status = "pending"
            order.razorpay_payment_id = data.razorpay_payment_id
            order.signature = data.razorpay_signature
            await self.db.flush()
            return PaymentVerifyResponse(
                status="pending",
                message="Payment is currently pending. Bill will be settled once captured.",
                payment_id=data.razorpay_payment_id,
                bill_type=order.bill_type,
                bill_id=order.bill_id,
                is_fully_paid=False,
                settled_amount=0.0,
                excess_amount=0.0,
            )

        if payment_status != "captured":
            order.status = "failed"
            order.razorpay_payment_id = data.razorpay_payment_id
            order.signature = data.razorpay_signature
            order.error_code = rp_payment.get("error_code")
            order.error_reason = rp_payment.get("error_description")
            await self.db.flush()
            raise BadRequestException(f"Payment is not captured. Current gateway status: {payment_status}")

        # 3. Status is "captured" -> Settle bill atomically
        order.signature = data.razorpay_signature
        settled_amt, excess_amt, is_fully_paid = await self._settle_bill(
            order, data.razorpay_payment_id, current_user.id if current_user else None
        )

        return PaymentVerifyResponse(
            status=order.status,
            message="Payment captured and bill settled successfully",
            payment_id=data.razorpay_payment_id,
            bill_type=order.bill_type,
            bill_id=order.bill_id,
            is_fully_paid=is_fully_paid,
            settled_amount=float(settled_amt),
            excess_amount=float(excess_amt),
        )

    # -------------------------------------------------------------------------
    # 3. PUBLIC WEBHOOK HANDLER
    # -------------------------------------------------------------------------
    async def process_webhook(
        self, raw_body_bytes: bytes, signature: str | None, event_id_header: str | None
    ) -> RazorpayWebhookResponse:
        if not signature:
            raise BadRequestException("Missing X-Razorpay-Signature header")

        if not settings.RAZORPAY_WEBHOOK_SECRET:
            raise BadRequestException("Razorpay webhook secret is not configured. Please set RAZORPAY_WEBHOOK_SECRET.")

        # 1. Verify Raw-Body Webhook Signature via SDK utility in thread pool
        webhook_secret = settings.RAZORPAY_WEBHOOK_SECRET
        try:
            await self._run_sync(
                self.client.utility.verify_webhook_signature,
                raw_body_bytes.decode("utf-8"),
                signature,
                webhook_secret,
            )
        except Exception:
            raise BadRequestException("Invalid webhook signature")

        try:
            payload = json.loads(raw_body_bytes.decode("utf-8"))
        except Exception:
            raise BadRequestException("Invalid webhook JSON payload")

        event_name = payload.get("event")
        # Strictly prefer X-Razorpay-Event-Id header, then payload event_id
        resolved_event_id = event_id_header or payload.get("event_id") or payload.get("id")
        if not resolved_event_id:
            resolved_event_id = f"evt_{int(datetime.now(timezone.utc).timestamp())}_{hash(raw_body_bytes)}"

        # 2. Unique Event Deduplication with IntegrityError transaction recovery
        event_record = None
        try:
            async with self.db.begin_nested():
                event_record = RazorpayWebhookEvent(
                    event_id=resolved_event_id,
                    event_type=event_name or "unknown",
                    payload=raw_body_bytes.decode("utf-8", errors="ignore"),
                    processed=False,
                )
                self.db.add(event_record)
                await self.db.flush()
        except IntegrityError:
            # Duplicate event delivery
            existing_evt = (
                await self.db.scalars(
                    select(RazorpayWebhookEvent).where(RazorpayWebhookEvent.event_id == resolved_event_id)
                )
            ).first()
            if existing_evt and existing_evt.processed:
                return RazorpayWebhookResponse(status="already_processed", event_id=resolved_event_id)
            return RazorpayWebhookResponse(status="duplicate", event_id=resolved_event_id)

        # 3. Process Events
        try:
            if event_name == "payment.captured":
                await self._handle_webhook_payment_captured(payload)
            elif event_name == "order.paid":
                await self._handle_webhook_order_paid(payload)
            elif event_name == "payment.failed":
                await self._handle_webhook_payment_failed(payload)
            elif event_name in ("refund.created", "refund.processed", "payment.refunded"):
                await self._handle_webhook_refund(payload)
            elif event_name == "refund.failed":
                await self._handle_webhook_refund_failed(payload)
            else:
                logger.info("Ignoring unhandled or unknown Razorpay webhook event: %s", event_name)

            if event_record:
                event_record.processed = True
                event_record.processed_at = utc_now()
                await self.db.flush()

            return RazorpayWebhookResponse(status="processed", event_id=resolved_event_id)
        except Exception as exc:
            logger.error("Error processing webhook %s: %s", event_name, exc, exc_info=True)
            if event_record:
                event_record.error_message = str(exc)
                await self.db.flush()
            raise

    # -------------------------------------------------------------------------
    # WEBHOOK EVENT HELPERS
    # -------------------------------------------------------------------------
    async def _handle_webhook_payment_captured(self, payload: dict) -> None:
        p_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        order_id = p_entity.get("order_id")
        payment_id = p_entity.get("id")
        amount = p_entity.get("amount")
        currency = p_entity.get("currency")

        if not order_id or not payment_id:
            logger.warning("payment.captured event missing order_id or payment_id")
            return

        if currency != "INR":
            logger.warning("Unsupported currency in payment.captured: %s", currency)
            return

        order = (
            await self.db.scalars(
                select(RazorpayOrder)
                .where(RazorpayOrder.razorpay_order_id == order_id)
                .with_for_update()
            )
        ).first()

        if not order:
            logger.warning("No local order found for webhook order_id: %s", order_id)
            return

        # Dual-event deduplication: if already settled, return safely
        if order.status in ("paid", "reconciliation_required") and order.razorpay_payment_id == payment_id:
            return

        await self._settle_bill(order, payment_id, user_id=None)

    async def _handle_webhook_order_paid(self, payload: dict) -> None:
        o_entity = payload.get("payload", {}).get("order", {}).get("entity", {})
        order_id = o_entity.get("id")
        if not order_id:
            return

        order = (
            await self.db.scalars(
                select(RazorpayOrder)
                .where(RazorpayOrder.razorpay_order_id == order_id)
                .with_for_update()
            )
        ).first()

        if not order:
            return

        # Dual-event deduplication: if already settled, return safely
        if order.status in ("paid", "reconciliation_required"):
            return

        # Resolve payment_id
        payment_id = payload.get("payload", {}).get("payment", {}).get("entity", {}).get("id")
        if not payment_id:
            # Query SDK for payments associated with this order in thread pool
            try:
                payments_resp = await self._run_sync(self.client.order.payments, order_id)
                items = payments_resp.get("items", []) if isinstance(payments_resp, dict) else []
                captured_pmts = [
                    p for p in items
                    if p.get("status") == "captured"
                    and p.get("amount") == order.amount_paise
                    and p.get("currency") == "INR"
                ]
                if captured_pmts:
                    payment_id = captured_pmts[0].get("id")
            except Exception as exc:
                logger.warning("Failed to query order payments for %s: %s", order_id, exc)

        if not payment_id:
            # Cannot reliably resolve captured payment ID: defer settlement safely
            order.status = "reconciliation_deferred"
            order.error_reason = "order.paid received but no captured payment resolvable yet"
            await self.db.flush()
            return

        await self._settle_bill(order, payment_id, user_id=None)

    async def _handle_webhook_payment_failed(self, payload: dict) -> None:
        p_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        order_id = p_entity.get("order_id")
        if not order_id:
            return

        order = (
            await self.db.scalars(
                select(RazorpayOrder)
                .where(RazorpayOrder.razorpay_order_id == order_id)
                .with_for_update()
            )
        ).first()

        if not order:
            return

        # CRITICAL PROTECTION: A late failed event must NEVER overwrite a paid order!
        if order.status in ("paid", "reconciliation_required"):
            logger.info("Ignoring late payment.failed for already settled order %s", order_id)
            return

        order.status = "failed"
        order.razorpay_payment_id = p_entity.get("id")
        order.error_code = p_entity.get("error_code")
        order.error_reason = p_entity.get("error_description")
        await self.db.flush()

    async def _handle_webhook_refund(self, payload: dict) -> None:
        p_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        r_entity = payload.get("payload", {}).get("refund", {}).get("entity", {})
        payment_id = p_entity.get("id") or r_entity.get("payment_id")
        if not payment_id:
            logger.warning("Refund event missing payment_id in payload")
            return

        order = (
            await self.db.scalars(
                select(RazorpayOrder)
                .where(RazorpayOrder.razorpay_payment_id == payment_id)
                .with_for_update()
            )
        ).first()

        if not order:
            logger.warning("No local order found for refund payment_id: %s", payment_id)
            return

        if order.status == "refunded":
            # Idempotent deduplication
            return

        order.status = "refunded"
        refund_amt = float(order.settled_amount_inr or order.amount_inr)

        # Update underlying bill balance and status if appropriate
        if order.bill_type == "opd":
            billing = await self.db.get(Billing, order.bill_id)
            if billing:
                existing_refund = (await self.db.scalars(
                    select(Payment).where(
                        Payment.billing_id == billing.id,
                        Payment.transaction_ref == f"REF-{payment_id}",
                        Payment.is_refund.is_(True),
                    )
                )).first()
                if not existing_refund:
                    ref_payment = Payment(
                        billing_id=billing.id,
                        amount=refund_amt,
                        payment_method="razorpay_refund",
                        transaction_ref=f"REF-{payment_id}",
                        payment_date=utc_now(),
                        status="completed",
                        is_refund=True,
                        refund_reason="Razorpay webhook refund processed",
                        received_by=None,
                    )
                    self.db.add(ref_payment)
                    billing.paid_amount = round(max(0.0, float(billing.paid_amount or 0.0) - refund_amt), 2)
                    billing.balance_amount = round(max(0.0, float(billing.total_amount or 0.0) - float(billing.paid_amount)), 2)
                    if billing.paid_amount <= 0:
                        billing.status = BillingStatus.REFUNDED
                    else:
                        billing.status = BillingStatus.PARTIAL

        elif order.bill_type == "pharmacy":
            invoice = await self.db.get(PharmacyInvoice, order.bill_id)
            if invoice:
                invoice.paid_amount = round(max(0.0, float(invoice.paid_amount or 0.0) - refund_amt), 2)
                if invoice.paid_amount <= 0:
                    invoice.status = "refunded"
                else:
                    invoice.status = "partially_refunded"

        elif order.bill_type == "ipd":
            final_bill = await self.db.get(IPDFinalBill, order.bill_id)
            if final_bill:
                final_bill.refund_amount = round(float(final_bill.refund_amount or 0.0) + refund_amt, 2)
                final_bill.balance_amount = round(float(final_bill.balance_amount or 0.0) + refund_amt, 2)
                final_bill.status = "refunded"
                if final_bill.discharge_id:
                    discharge = await self.db.get(Discharge, final_bill.discharge_id)
                    if discharge:
                        discharge.payment_cleared = False
                        if discharge.discharge_status == "CLEARED":
                            discharge.discharge_status = "PENDING_CLEARANCES"

        await self.db.flush()

        await self.tx_service.create_event(
            event_type="REFUND_PROCESSED",
            reference_no=payment_id,
            description=f"Razorpay payment {payment_id} refunded for {order.bill_type} bill #{order.bill_id}",
            amount=refund_amt,
            source_module="payments",
            source_id=order.bill_id,
            status="completed",
            user_id=None,
            hospital_id=order.hospital_id,
        )

    async def _handle_webhook_refund_failed(self, payload: dict) -> None:
        p_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        r_entity = payload.get("payload", {}).get("refund", {}).get("entity", {})
        payment_id = p_entity.get("id") or r_entity.get("payment_id")
        refund_id = r_entity.get("id") or "unknown"
        if not payment_id:
            return

        order = (
            await self.db.scalars(
                select(RazorpayOrder)
                .where(RazorpayOrder.razorpay_payment_id == payment_id)
                .with_for_update()
            )
        ).first()

        if not order:
            return

        order.error_code = r_entity.get("error_code") or "REFUND_FAILED"
        order.error_reason = r_entity.get("error_description") or "Refund failed at gateway"
        await self.db.flush()

        await self.tx_service.create_event(
            event_type="REFUND_FAILED",
            reference_no=payment_id,
            description=f"Razorpay refund {refund_id} failed for payment {payment_id} ({order.bill_type} bill #{order.bill_id}): {order.error_reason}",
            amount=float(order.amount_inr),
            source_module="payments",
            source_id=order.bill_id,
            status="failed",
            user_id=None,
            hospital_id=order.hospital_id,
        )

    # -------------------------------------------------------------------------
    # 4. SETTLEMENT ENGINE (STALE ORDERS & OVERPAYMENT HANDLING)
    # -------------------------------------------------------------------------
    async def _settle_bill(
        self, order: RazorpayOrder, payment_id: str, user_id: int | None
    ) -> tuple[Decimal, Decimal, bool]:
        """
        Atomically settles bill, handles stale orders & overpayments, and updates RazorpayOrder.
        Returns: (settled_amount_decimal, excess_amount_decimal, is_fully_paid)
        """
        bill_type = order.bill_type.lower()
        bill_id = order.bill_id
        hospital_id = order.hospital_id

        # Re-fetch bill under row lock to get the current outstanding balance
        bill_record, current_balance = await self._get_bill_and_balance(
            bill_type, bill_id, hospital_id, for_update=True
        )

        captured_inr = (Decimal(str(order.amount_paise)) / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        settled_amount = Decimal("0.00")
        excess_amount = Decimal("0.00")
        is_fully_paid = False

        if current_balance <= Decimal("0.00"):
            # Bill was already paid before checkout completed: full overpayment
            settled_amount = Decimal("0.00")
            excess_amount = captured_inr
            order.status = "reconciliation_required"
            order.error_reason = f"Bill already fully paid. Captured ₹{captured_inr} flagged for refund/reconciliation."
        elif captured_inr > current_balance:
            # Overpayment: balance changed (e.g. partial cash collected or discount applied)
            settled_amount = current_balance
            excess_amount = captured_inr - current_balance
            order.status = "reconciliation_required"
            order.error_reason = f"Overpayment detected: captured ₹{captured_inr} exceeds current balance ₹{current_balance}. Excess ₹{excess_amount} flagged for refund."
        else:
            # Exact or partial payment
            settled_amount = captured_inr
            excess_amount = Decimal("0.00")
            order.status = "paid"

        order.settled_amount_inr = settled_amount
        order.excess_amount_inr = excess_amount
        order.razorpay_payment_id = payment_id

        # Execute settlement if settled_amount > 0
        if settled_amount > Decimal("0.00"):
            if bill_type == "opd":
                is_fully_paid = await self._settle_opd_billing(bill_record, settled_amount, payment_id, user_id)
            elif bill_type == "pharmacy":
                is_fully_paid = await self._settle_pharmacy_invoice(bill_record, settled_amount, payment_id, user_id)
            elif bill_type == "ipd":
                is_fully_paid = await self._settle_ipd_final_bill(bill_record, settled_amount, payment_id, user_id)

        # Audit overpayment if excess exists
        if excess_amount > Decimal("0.00"):
            try:
                await self.tx_service.create_event(
                    event_type="OVERPAYMENT_FLAGGED",
                    reference_no=payment_id,
                    description=f"Overpayment of ₹{excess_amount} on {bill_type} #{bill_id}. Needs manual refund/reconciliation.",
                    amount=float(excess_amount),
                    source_module="payments",
                    source_id=bill_id,
                    status="pending_action",
                    user_id=user_id,
                    hospital_id=hospital_id,
                )
            except Exception as exc:
                logger.warning("Failed to record overpayment audit event: %s", exc)

        await self.db.flush()
        return settled_amount, excess_amount, is_fully_paid

    # -------------------------------------------------------------------------
    # DEDICATED MODEL SETTLEMENT HANDLERS
    # -------------------------------------------------------------------------
    async def _settle_opd_billing(
        self, billing: Billing, amount_to_apply: Decimal, payment_id: str, user_id: int | None
    ) -> bool:
        # Create Payment row
        payment_record = Payment(
            billing_id=billing.id,
            amount=float(amount_to_apply),
            payment_method="razorpay",
            transaction_ref=payment_id,
            payment_date=utc_now(),
            status="completed",
            is_refund=False,
            received_by=user_id,
        )
        self.db.add(payment_record)

        # Update paid_amount & balance_amount using Decimal arithmetic
        new_paid = (Decimal(str(billing.paid_amount or 0.0)) + amount_to_apply).quantize(Decimal("0.01"))
        total_amt = Decimal(str(billing.total_amount or 0.0)).quantize(Decimal("0.01"))
        new_bal = max(Decimal("0.00"), total_amt - new_paid).quantize(Decimal("0.01"))

        billing.paid_amount = float(new_paid)
        billing.balance_amount = float(new_bal)

        if new_bal <= Decimal("0.00"):
            billing.status = BillingStatus.PAID
            is_fully_paid = True
        else:
            billing.status = BillingStatus.PARTIAL
            is_fully_paid = False

        await self.audit_repo.create("payment", "billing", user_id=user_id, resource_id=str(billing.id))

        try:
            await self.tx_service.create_event(
                event_type="PAYMENT_RECEIVED",
                reference_no=payment_id,
                description=f"Payment of ₹{amount_to_apply} received on OPD bill #{billing.bill_number} via Razorpay",
                amount=float(amount_to_apply),
                source_module="payments",
                source_id=billing.id,
                status="completed",
                user_id=user_id,
                hospital_id=billing.hospital_id,
            )
        except Exception:
            pass

        return is_fully_paid

    async def _settle_pharmacy_invoice(
        self, invoice: PharmacyInvoice, amount_to_apply: Decimal, payment_id: str, user_id: int | None
    ) -> bool:
        new_paid = (Decimal(str(invoice.paid_amount or 0.0)) + amount_to_apply).quantize(Decimal("0.01"))
        total_amt = Decimal(str(invoice.total_amount or 0.0)).quantize(Decimal("0.01"))
        new_bal = max(Decimal("0.00"), total_amt - new_paid).quantize(Decimal("0.01"))

        invoice.paid_amount = float(new_paid)

        # Preserve previous payment mode if mixed
        prev_mode = str(invoice.payment_mode or "").strip().lower()
        if prev_mode and prev_mode != "razorpay" and prev_mode != "mixed":
            invoice.payment_mode = f"Mixed ({invoice.payment_mode} + Razorpay)"
        elif not invoice.payment_mode:
            invoice.payment_mode = "razorpay"

        if new_bal <= Decimal("0.00"):
            invoice.status = "paid"
            is_fully_paid = True
        else:
            invoice.status = "partially_paid"
            is_fully_paid = False

        await self.audit_repo.create("payment", "pharmacy_invoice", user_id=user_id, resource_id=str(invoice.id))

        try:
            await self.tx_service.create_event(
                event_type="PAYMENT_RECEIVED",
                reference_no=payment_id,
                description=f"Payment of ₹{amount_to_apply} received on Pharmacy invoice #{invoice.invoice_number} via Razorpay",
                amount=float(amount_to_apply),
                source_module="pharmacy_billing",
                source_id=invoice.id,
                status="completed",
                user_id=user_id,
                hospital_id=invoice.hospital_id,
            )
        except Exception:
            pass

        return is_fully_paid

    async def _settle_ipd_final_bill(
        self, final_bill: IPDFinalBill, amount_to_apply: Decimal, payment_id: str, user_id: int | None
    ) -> bool:
        cur_bal = Decimal(str(final_bill.balance_amount or 0.0)).quantize(Decimal("0.01"))
        new_bal = max(Decimal("0.00"), cur_bal - amount_to_apply).quantize(Decimal("0.01"))
        final_bill.balance_amount = float(new_bal)

        # Preserve payment mode if advance payment was already adjusted
        if (final_bill.advance_adjusted or 0.0) > 0:
            final_bill.payment_mode = "Mixed (Advance + Razorpay)"
        else:
            final_bill.payment_mode = "razorpay"

        is_fully_paid = False
        if new_bal <= Decimal("0.00"):
            final_bill.status = "paid"
            final_bill.settled_at = utc_now()
            final_bill.settled_by = user_id
            is_fully_paid = True

            discharge = None
            # Discharge Clearance Evaluation
            if final_bill.discharge_id:
                discharge = (
                    await self.db.scalars(
                        select(Discharge)
                        .where(Discharge.id == final_bill.discharge_id)
                        .with_for_update()
                    )
                ).first()

            if discharge:
                # 1. Settle ONLY pharmacy invoices incorporated into this IPD final bill
                pharm_invoice_ids = set()
                if getattr(final_bill, "items", None):
                    for item in final_bill.items:
                        if getattr(item, "item_type", "") == "pharmacy_invoice" and getattr(item, "reference_id", None):
                            pharm_invoice_ids.add(item.reference_id)

                if pharm_invoice_ids:
                    unpaid_pharm_stmt = select(PharmacyInvoice).where(
                        PharmacyInvoice.id.in_(list(pharm_invoice_ids)),
                        PharmacyInvoice.patient_id == discharge.patient_id,
                        PharmacyInvoice.is_deleted == False,
                        PharmacyInvoice.status != "paid",
                    ).with_for_update()
                    if discharge.hospital_id is not None:
                        unpaid_pharm_stmt = unpaid_pharm_stmt.where(PharmacyInvoice.hospital_id == discharge.hospital_id)
                    unpaid_pharm = (await self.db.scalars(unpaid_pharm_stmt)).all()
                    for inv in (unpaid_pharm or []):
                        inv.paid_amount = float(inv.total_amount or 0.0)
                        inv.status = "paid"
                        inv.payment_mode = "razorpay"

                # 2. Settle associated general billing if explicitly linked to this discharge
                if discharge.billing_id:
                    gen_b = await self.db.get(Billing, discharge.billing_id)
                    if gen_b and gen_b.is_deleted is False:
                        bal_due = max(0.0, round(float(gen_b.total_amount or 0.0) - float(gen_b.paid_amount or 0.0), 2))
                        if bal_due > 0:
                            payment_rec = Payment(
                                billing_id=gen_b.id,
                                amount=bal_due,
                                payment_method="razorpay",
                                transaction_ref=payment_id,
                                payment_date=utc_now(),
                                status="completed",
                                received_by=user_id,
                            )
                            self.db.add(payment_rec)
                        gen_b.paid_amount = float(gen_b.total_amount or 0.0)
                        gen_b.balance_amount = 0.0
                        gen_b.status = BillingStatus.PAID

                # 3. Recalculate & strictly verify actual settlement state before setting payment_cleared
                from app.services.discharge_service import DischargeService
                dc_service = DischargeService(self.db)
                all_settled, outstanding = await dc_service.validate_applicable_ipd_bills_settled(
                    discharge, hospital_id=discharge.hospital_id
                )

                if all_settled:
                    discharge.payment_cleared = True
                    discharge.payment_cleared_by = user_id
                    discharge.payment_cleared_at = utc_now()
                    discharge.payment_notes = f"Payment of ₹{amount_to_apply} captured via Razorpay ({payment_id})"
                else:
                    discharge.payment_cleared = False

                # NOTE: Billing clearance is NOT automatically granted by payment webhook.
                # It requires authorized departmental action.
                # 4. Tri-Clearance Checkpoint evaluation
                if (
                    discharge.pharmacy_cleared
                    and discharge.billing_cleared
                    and discharge.payment_cleared
                    and discharge.discharge_status == "PENDING_CLEARANCES"
                ):
                    discharge.discharge_status = "CLEARED"
        else:
            final_bill.status = "partially_paid"
            # Partial payment: discharge payment_cleared remains False!
            if final_bill.discharge_id:
                discharge = (
                    await self.db.scalars(
                        select(Discharge).where(Discharge.id == final_bill.discharge_id)
                    )
                ).first()
                if discharge:
                    discharge.payment_cleared = False
                    if discharge.discharge_status == "CLEARED":
                        discharge.discharge_status = "PENDING_CLEARANCES"

        try:
            await self.tx_service.create_event(
                event_type="PAYMENT_RECEIVED",
                reference_no=payment_id,
                description=f"Payment of ₹{amount_to_apply} received on IPD Final Bill #{final_bill.bill_number} via Razorpay",
                amount=float(amount_to_apply),
                source_module="final_bills",
                source_id=final_bill.id,
                status="completed",
                user_id=user_id,
                hospital_id=final_bill.hospital_id,
            )
        except Exception:
            pass

        return is_fully_paid

    # -------------------------------------------------------------------------
    # UTILITIES: BALANCE CALCULATION & PATIENT OWNERSHIP
    # -------------------------------------------------------------------------
    async def _get_bill_and_balance(
        self, bill_type: str, bill_id: int, hospital_id: int | None, for_update: bool = False
    ) -> tuple[Any, Decimal]:
        """Fetch bill row with tenant scoping and calculate Decimal balance."""
        bill_type = bill_type.lower()
        if bill_type in ("consultation", "billing"):
            bill_type = "opd"
        elif bill_type in ("ipd_final", "ipd_billing", "ipd-final", "ipd-bill", "ipd_bill"):
            bill_type = "ipd"

        if bill_type == "opd":
            stmt = select(Billing).where(Billing.id == bill_id, Billing.is_deleted.is_(False))
            if hospital_id is not None:
                stmt = stmt.where(Billing.hospital_id == hospital_id)
            if for_update:
                stmt = stmt.with_for_update()

            billing = (await self.db.scalars(stmt)).first()
            if not billing:
                raise NotFoundException("OPD billing record not found")

            if str(billing.status).lower() in ("cancelled", "refunded"):
                raise BadRequestException(f"Cannot pay {billing.status} bill")

            total = Decimal(str(billing.total_amount or 0.0))
            paid = Decimal(str(billing.paid_amount or 0.0))
            balance = max(Decimal("0.00"), total - paid).quantize(Decimal("0.01"))
            return billing, balance

        elif bill_type == "pharmacy":
            stmt = select(PharmacyInvoice).where(
                PharmacyInvoice.id == bill_id, PharmacyInvoice.is_deleted.is_(False)
            )
            if hospital_id is not None:
                stmt = stmt.where(PharmacyInvoice.hospital_id == hospital_id)
            if for_update:
                stmt = stmt.with_for_update()

            invoice = (await self.db.scalars(stmt)).first()
            if not invoice:
                raise NotFoundException("Pharmacy invoice not found")

            if str(invoice.status).lower() in ("cancelled", "refunded"):
                raise BadRequestException(f"Cannot pay {invoice.status} invoice")

            total = Decimal(str(invoice.total_amount or 0.0))
            paid = Decimal(str(invoice.paid_amount or 0.0))
            balance = max(Decimal("0.00"), total - paid).quantize(Decimal("0.01"))
            return invoice, balance

        elif bill_type == "ipd":
            stmt = select(IPDFinalBill).where(
                or_(
                    IPDFinalBill.id == bill_id,
                    IPDFinalBill.discharge_id == bill_id,
                ),
                IPDFinalBill.is_deleted.is_(False)
            )
            if hospital_id is not None:
                stmt = stmt.where(IPDFinalBill.hospital_id == hospital_id)
            if for_update:
                stmt = stmt.with_for_update()

            final_bill = (await self.db.scalars(stmt)).first()
            if not final_bill:
                # Also fallback to check if bill_id was passed as patient_id
                stmt_pat = select(IPDFinalBill).where(
                    IPDFinalBill.patient_id == bill_id,
                    IPDFinalBill.is_deleted.is_(False)
                )
                if hospital_id is not None:
                    stmt_pat = stmt_pat.where(IPDFinalBill.hospital_id == hospital_id)
                stmt_pat = stmt_pat.order_by(IPDFinalBill.id.desc())
                if for_update:
                    stmt_pat = stmt_pat.with_for_update()
                final_bill = (await self.db.scalars(stmt_pat)).first()

            if not final_bill:
                raise NotFoundException("IPD Final Bill not found")

            if str(final_bill.status).lower() in ("refunded", "cancelled"):
                raise BadRequestException(f"Cannot pay {final_bill.status} IPD bill")

            balance = max(Decimal("0.00"), Decimal(str(final_bill.balance_amount or 0.0))).quantize(Decimal("0.01"))
            return final_bill, balance

        else:
            raise BadRequestException(f"Invalid billing type '{bill_type}'. Must be opd, pharmacy, or ipd.")

    async def _verify_patient_ownership(self, bill_type: str, bill_id: int, current_user: User) -> None:
        """Verify that a patient user owns the bill they are paying for."""
        if not current_user or not getattr(current_user, "role", None):
            return

        role_name = getattr(current_user.role, "name", "").lower()
        if role_name != "patient":
            return

        bill_type = bill_type.lower()
        if bill_type in ("consultation", "billing"):
            bill_type = "opd"
        elif bill_type in ("ipd_final", "ipd_billing", "ipd-final", "ipd-bill", "ipd_bill"):
            bill_type = "ipd"

        allowed_ids = await PatientService(self.db)._resolve_allowed_patient_ids(current_user)

        if bill_type == "opd":
            billing = await self.db.get(Billing, bill_id)
            if not billing or billing.patient_id not in allowed_ids:
                raise ForbiddenException("You do not have permission to pay this bill")
        elif bill_type == "pharmacy":
            invoice = await self.db.get(PharmacyInvoice, bill_id)
            if not invoice or invoice.patient_id not in allowed_ids:
                raise ForbiddenException("You do not have permission to pay this pharmacy invoice")
        elif bill_type == "ipd":
            final_bill = await self.db.get(IPDFinalBill, bill_id)
            if not final_bill:
                final_bill = (await self.db.scalars(
                    select(IPDFinalBill).where(
                        or_(
                            IPDFinalBill.discharge_id == bill_id,
                            IPDFinalBill.patient_id == bill_id
                        )
                    ).order_by(IPDFinalBill.id.desc())
                )).first()
            if not final_bill or final_bill.patient_id not in allowed_ids:
                raise ForbiddenException("You do not have permission to pay this IPD final bill")
