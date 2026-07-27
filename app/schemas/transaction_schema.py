from datetime import datetime
from pydantic import Field, model_validator
from app.schemas.common_schema import BaseSchema


class TransactionCreate(BaseSchema):
    billing_id: int
    amount: float = Field(..., gt=0)
    payment_method: str
    transaction_ref: str | None = None
    payment_date: datetime | None = None
    status: str | None = "completed"
    is_refund: bool | None = False
    refund_reason: str | None = None

    @model_validator(mode="after")
    def validate_transaction_details(self) -> "TransactionCreate":
        pm = self.payment_method.strip()
        pm_lower = pm.lower()

        if pm_lower not in {"cash", "upi", "cheque", "cheques"}:
            raise ValueError("payment_method must be one of: cash, upi, cheque")

        self.payment_method = pm

        if pm_lower in {"upi", "cheque", "cheques"}:
            ref = self.transaction_ref
            if not ref or len(ref.strip()) == 0 or ref.strip().lower() == "string":
                raise ValueError(f"transaction_ref is required when payment_method is {pm}")
            self.transaction_ref = ref.strip()
        return self


class TransactionUpdate(BaseSchema):
    amount: float | None = Field(None, gt=0)
    payment_method: str | None = None
    transaction_ref: str | None = None
    payment_date: datetime | None = None
    status: str | None = None
    is_refund: bool | None = None
    refund_reason: str | None = None

    @model_validator(mode="after")
    def validate_transaction_details(self) -> "TransactionUpdate":
        pm = self.payment_method
        ref = self.transaction_ref

        if pm is not None:
            pm_stripped = pm.strip()
            pm_lower = pm_stripped.lower()
            if pm_lower not in {"cash", "upi", "cheque", "cheques"}:
                raise ValueError("payment_method must be one of: cash, upi, cheque")
            self.payment_method = pm_stripped

            if pm_lower in {"upi", "cheque", "cheques"}:
                # If transaction_ref is not updated but payment_method is set to upi/cheque,
                # we don't have the original transaction_ref context here unless it's provided.
                # However, during update, if they are switching to upi/cheque, they must provide transaction_ref.
                if ref is None or len(ref.strip()) == 0 or ref.strip().lower() == "string":
                    raise ValueError(f"transaction_ref is required when payment_method is {pm}")
                self.transaction_ref = ref.strip()
        elif ref is not None:
            if len(ref.strip()) == 0 or ref.strip().lower() == "string":
                raise ValueError("transaction_ref cannot be empty or 'string'")
            self.transaction_ref = ref.strip()

        return self



class TransactionResponse(BaseSchema):
    id: int
    billing_id: int
    amount: float
    payment_method: str
    transaction_ref: str | None
    payment_date: datetime
    status: str
    is_refund: bool
    refund_reason: str | None
    created_at: datetime
    updated_at: datetime
