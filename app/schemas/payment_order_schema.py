from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field


class RazorpayOrderCreateRequest(BaseModel):
    bill_type: str = Field(..., pattern="^(opd|pharmacy|ipd|consultation|billing)$", description="Type of billing: opd, pharmacy, ipd, consultation, or billing")
    bill_id: int = Field(..., gt=0, description="Database ID of the bill to pay")


class RazorpayOrderResponse(BaseModel):
    key_id: str
    order_id: str
    amount_inr: float
    amount_paise: int
    currency: str = "INR"
    bill_type: str
    bill_id: int
    local_order_id: int

    model_config = ConfigDict(from_attributes=True)


class RazorpayVerifyRequest(BaseModel):
    razorpay_order_id: str = Field(..., min_length=1, description="Razorpay Order ID")
    razorpay_payment_id: str = Field(..., min_length=1, description="Razorpay Payment ID")
    razorpay_signature: str = Field(..., min_length=1, description="HMAC SHA256 checkout signature")


class PaymentVerifyResponse(BaseModel):
    status: str
    message: str
    payment_id: str
    bill_type: str
    bill_id: int
    is_fully_paid: bool
    settled_amount: float
    excess_amount: float = 0.0

    model_config = ConfigDict(from_attributes=True)


class RazorpayWebhookResponse(BaseModel):
    status: str
    event_id: str | None = None
