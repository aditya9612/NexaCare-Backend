from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import BadRequestException, NotFoundException
from app.models.subscription_model import SubscriptionPlan, Subscription
from app.repositories.subscription_repository import SubscriptionRepository
from app.repositories.hospital_repository import HospitalRepository
from app.repositories.audit_repository import AuditRepository
from app.schemas.subscription_schema import (
    PlanCreate,
    PlanUpdate,
    PlanResponse,
    SubscriptionAssignRequest,
    SubscriptionResponse,
)

class SubscriptionService:
    def __init__(self, db: AsyncSession):
        self.repo = SubscriptionRepository(db)
        self.hospital_repo = HospitalRepository(db)
        self.audit_repo = AuditRepository(db)

    async def create_plan(self, data: PlanCreate, user_id: int) -> PlanResponse:
        existing = await self.repo.get_plan_by_name(data.name)
        if existing:
            raise BadRequestException("Plan with this name already exists")
        plan = SubscriptionPlan(**data.model_dump())
        plan = await self.repo.create_plan(plan)
        await self.audit_repo.create("create", "subscription_plans", user_id=user_id, resource_id=str(plan.id))
        return PlanResponse.model_validate(plan)

    async def list_plans(self, active_only: bool = True) -> list[PlanResponse]:
        plans = await self.repo.list_plans(active_only=active_only)
        return [PlanResponse.model_validate(p) for p in plans]

    async def assign_subscription(self, data: SubscriptionAssignRequest, user_id: int) -> SubscriptionResponse:
        hospital = await self.hospital_repo.get_by_id(data.hospital_id)
        if not hospital:
            raise NotFoundException("Hospital not found")
        plan = await self.repo.get_plan_by_id(data.plan_id)
        if not plan:
            raise NotFoundException("Subscription plan not found")

        start = datetime.utcnow()
        end = start + timedelta(days=plan.duration_days)

        sub = Subscription(
            hospital_id=data.hospital_id,
            plan_id=data.plan_id,
            status="active",
            start_date=start,
            end_date=end,
            price_paid=data.price_paid,
            transaction_id=data.transaction_id
        )
        sub = await self.repo.create_subscription(sub)
        await self.audit_repo.create("assign", "subscriptions", user_id=user_id, resource_id=str(sub.id))
        return SubscriptionResponse(
            id=sub.id,
            hospital_id=sub.hospital_id,
            plan_id=sub.plan_id,
            status=sub.status,
            start_date=sub.start_date,
            end_date=sub.end_date,
            price_paid=sub.price_paid,
            transaction_id=sub.transaction_id,
            created_at=sub.created_at,
            updated_at=sub.updated_at,
            plan_name=plan.name,
            hospital_name=hospital.name
        )

    async def list_subscription_history(self, hospital_id: int | None = None) -> list[SubscriptionResponse]:
        subs = await self.repo.list_subscriptions(hospital_id)
        return [
            SubscriptionResponse(
                id=s.id,
                hospital_id=s.hospital_id,
                plan_id=s.plan_id,
                status=s.status,
                start_date=s.start_date,
                end_date=s.end_date,
                price_paid=s.price_paid,
                transaction_id=s.transaction_id,
                created_at=s.created_at,
                updated_at=s.updated_at,
                plan_name=s.plan.name if s.plan else None,
                hospital_name=s.hospital.name if s.hospital else None
            )
            for s in subs
        ]

    async def update_subscription_status(self, sub_id: int, status: str, user_id: int) -> SubscriptionResponse:
        sub = await self.repo.get_subscription_by_id(sub_id)
        if not sub:
            raise NotFoundException("Subscription not found")
        sub.status = status
        sub = await self.repo.update_subscription(sub)
        await self.audit_repo.create("update", "subscriptions", user_id=user_id, resource_id=str(sub_id))
        return SubscriptionResponse(
            id=sub.id,
            hospital_id=sub.hospital_id,
            plan_id=sub.plan_id,
            status=sub.status,
            start_date=sub.start_date,
            end_date=sub.end_date,
            price_paid=sub.price_paid,
            transaction_id=sub.transaction_id,
            created_at=sub.created_at,
            updated_at=sub.updated_at,
            plan_name=sub.plan.name if sub.plan else None,
            hospital_name=sub.hospital.name if sub.hospital else None
        )
