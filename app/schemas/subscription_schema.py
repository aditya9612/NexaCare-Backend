from datetime import datetime
from pydantic import Field
from app.schemas.common_schema import BaseSchema

class PlanBase(BaseSchema):
    name: str = Field(..., min_length=2, max_length=100)
    price: float = Field(..., ge=0.0)
    duration_days: int = Field(30, ge=1)
    description: str | None = Field(None, max_length=255)
    max_doctors: int = Field(5, ge=1)
    max_patients: int = Field(100, ge=1)
    features: str | None = Field(None, max_length=1000)

class PlanCreate(PlanBase):
    pass

class PlanUpdate(BaseSchema):
    name: str | None = Field(None, min_length=2, max_length=100)
    price: float | None = Field(None, ge=0.0)
    duration_days: int | None = Field(None, ge=1)
    description: str | None = Field(None, max_length=255)
    max_doctors: int | None = Field(None, ge=1)
    max_patients: int | None = Field(None, ge=1)
    features: str | None = Field(None, max_length=1000)
    is_active: bool | None = None

class PlanResponse(PlanBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SubscriptionAssignRequest(BaseSchema):
    hospital_id: int
    plan_id: int
    price_paid: float = Field(..., ge=0.0)
    transaction_id: str | None = Field(None, max_length=100)

class SubscriptionResponse(BaseSchema):
    id: int
    hospital_id: int
    plan_id: int
    status: str
    start_date: datetime
    end_date: datetime
    price_paid: float
    transaction_id: str | None
    created_at: datetime
    updated_at: datetime
    
    plan_name: str | None = None
    hospital_name: str | None = None
