from fastapi import APIRouter, Depends
from app.core.dependencies import CurrentUser, DbSession
from app.core.exceptions import ForbiddenException
from app.core.constants import UserRole
from app.schemas.common_schema import APIResponse
from app.schemas.subscription_schema import (
    PlanCreate,
    PlanResponse,
    SubscriptionAssignRequest,
    SubscriptionResponse,
)
from app.services.subscription_service import SubscriptionService
from app.models.user_model import User

router = APIRouter()

async def require_super_admin(user: CurrentUser) -> User:
    if not user.role or user.role.name != UserRole.SUPER_ADMIN:
        raise ForbiddenException("Requires Super Admin role")
    return user

@router.post("/plans", response_model=APIResponse[PlanResponse], status_code=201)
async def create_plan(
    data: PlanCreate,
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    plan = await SubscriptionService(db).create_plan(data, current_user.id)
    return APIResponse(message="Subscription plan created successfully", data=plan)

@router.get("/plans", response_model=APIResponse[list[PlanResponse]])
async def list_plans(db: DbSession, _: CurrentUser):
    plans = await SubscriptionService(db).list_plans()
    return APIResponse(message="Subscription plans retrieved successfully", data=plans)

@router.post("/assign", response_model=APIResponse[SubscriptionResponse], status_code=201)
async def assign_subscription(
    data: SubscriptionAssignRequest,
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    sub = await SubscriptionService(db).assign_subscription(data, current_user.id)
    return APIResponse(message="Subscription assigned successfully", data=sub)

@router.get("/history", response_model=APIResponse[list[SubscriptionResponse]])
async def list_subscription_history(
    db: DbSession,
    current_user: CurrentUser
):
    h_id = None
    if current_user.role and current_user.role.name == UserRole.HOSPITAL_ADMIN:
        h_id = current_user.hospital_id
    elif current_user.role and current_user.role.name != UserRole.SUPER_ADMIN:
        raise ForbiddenException("Access denied")
        
    history = await SubscriptionService(db).list_subscription_history(hospital_id=h_id)
    return APIResponse(message="Subscription history retrieved successfully", data=history)

@router.put("/{id}", response_model=APIResponse[SubscriptionResponse])
async def update_subscription_status(
    id: int,
    status: str,
    db: DbSession,
    current_user: User = Depends(require_super_admin)
):
    sub = await SubscriptionService(db).update_subscription_status(id, status, current_user.id)
    return APIResponse(message="Subscription status updated successfully", data=sub)
