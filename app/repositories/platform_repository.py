from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.hospital_model import Hospital
from app.models.user_model import User
from app.models.subscription_model import Subscription
from app.models.voice_model import VoiceCall
from app.models.chat_model import ChatMessage

class PlatformRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_metrics(self) -> dict:
        total_hospitals = await self.db.scalar(
            select(func.count(Hospital.id)).where(Hospital.is_deleted == False)
        ) or 0
        total_users = await self.db.scalar(select(func.count(User.id))) or 0
        active_subs = await self.db.scalar(
            select(func.count(Subscription.id)).where(Subscription.status == "active")
        ) or 0
        voice_calls = await self.db.scalar(select(func.count(VoiceCall.id))) or 0
        chat_messages = await self.db.scalar(select(func.count(ChatMessage.id))) or 0

        return {
            "total_hospitals": total_hospitals,
            "total_users": total_users,
            "active_subscriptions": active_subs,
            "voice_calls_made": voice_calls,
            "chat_messages_exchanged": chat_messages
        }
