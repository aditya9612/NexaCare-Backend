import logging
from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_active_user
from app.models.user_model import User
from app.schemas.payment_order_schema import (
    PaymentVerifyResponse,
    RazorpayOrderCreateRequest,
    RazorpayOrderResponse,
    RazorpayVerifyRequest,
    RazorpayWebhookResponse,
)
from app.services.razorpay_service import RazorpayService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Payments"])


@router.post(
    "/razorpay/create-order",
    response_model=RazorpayOrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Razorpay Order for a Bill",
    description="Creates a Razorpay order server-side with Decimal-calculated payable balance. Never trusts frontend amounts.",
)
async def create_razorpay_order(
    data: RazorpayOrderCreateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> RazorpayOrderResponse:
    service = RazorpayService(db)
    return await service.create_order(data, current_user)


@router.post(
    "/razorpay/verify",
    response_model=PaymentVerifyResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify Checkout Payment Signature & Gateway Status",
    description="Validates HMAC SHA256 checkout signature and verifies server-side captured payment status before settling bills.",
)
async def verify_razorpay_payment(
    data: RazorpayVerifyRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> PaymentVerifyResponse:
    service = RazorpayService(db)
    return await service.verify_payment(data, current_user)


@router.post(
    "/razorpay/webhook",
    response_model=RazorpayWebhookResponse,
    status_code=status.HTTP_200_OK,
    summary="Razorpay Webhook Callback",
    description="Unauthenticated webhook receiver. Verifies raw request body with RAZORPAY_WEBHOOK_SECRET and provides deduplication.",
)
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str | None = Header(None, alias="X-Razorpay-Signature"),
    x_razorpay_event_id: str | None = Header(None, alias="X-Razorpay-Event-Id"),
    db: AsyncSession = Depends(get_db),
) -> RazorpayWebhookResponse:
    raw_body_bytes = await request.body()
    service = RazorpayService(db)
    return await service.process_webhook(raw_body_bytes, x_razorpay_signature, x_razorpay_event_id)
