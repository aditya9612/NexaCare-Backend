from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from app.models.subscription_model import SubscriptionPlan, Subscription

class SubscriptionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_plan(self, plan: SubscriptionPlan) -> SubscriptionPlan:
        self.db.add(plan)
        await self.db.flush()
        await self.db.refresh(plan)
        return plan

    async def get_plan_by_id(self, id: int) -> SubscriptionPlan | None:
        result = await self.db.execute(select(SubscriptionPlan).where(SubscriptionPlan.id == id))
        return result.scalar_one_or_none()

    async def get_plan_by_name(self, name: str) -> SubscriptionPlan | None:
        result = await self.db.execute(select(SubscriptionPlan).where(SubscriptionPlan.name == name))
        return result.scalar_one_or_none()

    async def list_plans(self, active_only: bool = True) -> list[SubscriptionPlan]:
        query = select(SubscriptionPlan)
        if active_only:
            query = query.where(SubscriptionPlan.is_active == True)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def update_plan(self, plan: SubscriptionPlan) -> SubscriptionPlan:
        await self.db.flush()
        await self.db.refresh(plan)
        return plan

    async def create_subscription(self, sub: Subscription) -> Subscription:
        self.db.add(sub)
        await self.db.flush()
        await self.db.refresh(sub)
        return sub

    async def get_subscription_by_id(self, id: int) -> Subscription | None:
        result = await self.db.execute(
            select(Subscription)
            .options(joinedload(Subscription.plan), joinedload(Subscription.hospital))
            .where(Subscription.id == id)
        )
        return result.scalar_one_or_none()

    async def update_subscription(self, sub: Subscription) -> Subscription:
        await self.db.flush()
        await self.db.refresh(sub)
        return sub

    async def list_subscriptions(self, hospital_id: int | None = None) -> list[Subscription]:
        query = select(Subscription).options(
            joinedload(Subscription.plan),
            joinedload(Subscription.hospital)
        )
        if hospital_id:
            query = query.where(Subscription.hospital_id == hospital_id)
        result = await self.db.execute(query)
        return list(result.scalars().unique().all())
