from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.whatsapp_model import (
    MessageDelivery,
    WhatsAppAnalytics,
    WhatsAppCampaign,
    WhatsAppMessage,
    WhatsAppTemplate,
)


class WhatsAppRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_message(self, message: WhatsAppMessage) -> WhatsAppMessage:
        self.db.add(message)
        await self.db.flush()
        await self.db.refresh(message)
        return message

    async def get_message(self, message_id: int) -> WhatsAppMessage | None:
        result = await self.db.execute(
            select(WhatsAppMessage)
            .options(selectinload(WhatsAppMessage.delivery_records))
            .where(WhatsAppMessage.id == message_id)
        )
        return result.scalar_one_or_none()

    async def get_by_provider_id(self, provider_message_id: str) -> WhatsAppMessage | None:
        result = await self.db.execute(
            select(WhatsAppMessage).where(WhatsAppMessage.provider_message_id == provider_message_id)
        )
        return result.scalar_one_or_none()

    async def update_message(self, message: WhatsAppMessage) -> WhatsAppMessage:
        await self.db.flush()
        await self.db.refresh(message)
        return message

    async def add_delivery(self, delivery: MessageDelivery) -> MessageDelivery:
        self.db.add(delivery)
        await self.db.flush()
        await self.db.refresh(delivery)
        return delivery

    async def get_template(self, template_name: str) -> WhatsAppTemplate | None:
        result = await self.db.execute(
            select(WhatsAppTemplate).where(
                WhatsAppTemplate.template_name == template_name,
                WhatsAppTemplate.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def create_campaign(self, campaign: WhatsAppCampaign) -> WhatsAppCampaign:
        self.db.add(campaign)
        await self.db.flush()
        await self.db.refresh(campaign)
        return campaign

    async def update_campaign(self, campaign: WhatsAppCampaign) -> WhatsAppCampaign:
        await self.db.flush()
        await self.db.refresh(campaign)
        return campaign

    async def list_messages(
        self,
        skip: int = 0,
        limit: int = 20,
        patient_id: int | None = None,
        delivery_status: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[WhatsAppMessage]:
        query = select(WhatsAppMessage)
        if patient_id:
            query = query.where(WhatsAppMessage.patient_id == patient_id)
        if delivery_status:
            query = query.where(WhatsAppMessage.delivery_status == delivery_status)
        if start:
            query = query.where(WhatsAppMessage.created_at >= start)
        if end:
            query = query.where(WhatsAppMessage.created_at <= end)
        result = await self.db.execute(query.order_by(WhatsAppMessage.created_at.desc()).offset(skip).limit(limit))
        return list(result.scalars().all())

    async def count_messages(
        self,
        patient_id: int | None = None,
        delivery_status: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> int:
        query = select(func.count()).select_from(WhatsAppMessage)
        if patient_id:
            query = query.where(WhatsAppMessage.patient_id == patient_id)
        if delivery_status:
            query = query.where(WhatsAppMessage.delivery_status == delivery_status)
        if start:
            query = query.where(WhatsAppMessage.created_at >= start)
        if end:
            query = query.where(WhatsAppMessage.created_at <= end)
        return await self.db.scalar(query) or 0

    async def message_type_breakdown(self) -> list[tuple[str, int]]:
        result = await self.db.execute(
            select(WhatsAppMessage.message_type, func.count(WhatsAppMessage.id)).group_by(
                WhatsAppMessage.message_type
            )
        )
        return list(result.all())

    async def delivery_counts(self) -> dict[str, int]:
        statuses = ["Sent", "Delivered", "Read", "Failed", "Pending"]
        counts = {}
        for status in statuses:
            counts[status] = await self.db.scalar(
                select(func.count()).select_from(WhatsAppMessage).where(
                    WhatsAppMessage.delivery_status == status
                )
            ) or 0
        return counts

    async def save_analytics(self, analytics: WhatsAppAnalytics) -> WhatsAppAnalytics:
        self.db.add(analytics)
        await self.db.flush()
        await self.db.refresh(analytics)
        return analytics
