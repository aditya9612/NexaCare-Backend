import json
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import ChatSessionStatus
from app.models.chat_model import AIResponse, ChatIntent, ChatMessage, ChatSession, ConversationMemory


class ChatRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_session(self, session: ChatSession) -> ChatSession:
        self.db.add(session)
        await self.db.flush()
        await self.db.refresh(session)
        return session

    async def get_session_by_uuid(self, session_id: str) -> ChatSession | None:
        result = await self.db.execute(
            select(ChatSession).where(ChatSession.session_id == session_id)
        )
        return result.scalar_one_or_none()

    async def get_session_by_id(self, session_pk: int) -> ChatSession | None:
        result = await self.db.execute(select(ChatSession).where(ChatSession.id == session_pk))
        return result.scalar_one_or_none()

    async def update_session(self, session: ChatSession) -> ChatSession:
        await self.db.flush()
        await self.db.refresh(session)
        return session

    async def add_message(self, message: ChatMessage) -> ChatMessage:
        self.db.add(message)
        await self.db.flush()
        await self.db.refresh(message)
        return message

    async def get_messages(self, session_pk: int, skip: int = 0, limit: int = 100) -> list[ChatMessage]:
        result = await self.db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_pk)
            .order_by(ChatMessage.sent_at.asc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_messages(self, session_pk: int) -> int:
        result = await self.db.scalar(
            select(func.count()).select_from(ChatMessage).where(ChatMessage.session_id == session_pk)
        )
        return result or 0

    async def add_intent(self, intent: ChatIntent) -> ChatIntent:
        self.db.add(intent)
        await self.db.flush()
        await self.db.refresh(intent)
        return intent

    async def add_ai_response(self, response: AIResponse) -> AIResponse:
        self.db.add(response)
        await self.db.flush()
        await self.db.refresh(response)
        return response

    async def upsert_memory(self, session_pk: int, key: str, value: str, expires_at: datetime | None = None) -> ConversationMemory:
        result = await self.db.execute(
            select(ConversationMemory).where(
                ConversationMemory.session_id == session_pk,
                ConversationMemory.memory_key == key,
            )
        )
        memory = result.scalar_one_or_none()
        if memory:
            memory.memory_value = value
            memory.expires_at = expires_at
        else:
            memory = ConversationMemory(
                session_id=session_pk,
                memory_key=key,
                memory_value=value,
                expires_at=expires_at,
            )
            self.db.add(memory)
        await self.db.flush()
        await self.db.refresh(memory)
        return memory

    async def get_memories(self, session_pk: int) -> list[ConversationMemory]:
        result = await self.db.execute(
            select(ConversationMemory).where(ConversationMemory.session_id == session_pk)
        )
        return list(result.scalars().all())

    async def get_session_with_messages(self, session_id: str) -> ChatSession | None:
        result = await self.db.execute(
            select(ChatSession)
            .options(selectinload(ChatSession.messages))
            .where(ChatSession.session_id == session_id)
        )
        return result.scalar_one_or_none()

    async def list_intents(self, skip: int = 0, limit: int = 50) -> list[ChatIntent]:
        result = await self.db.execute(
            select(ChatIntent).order_by(ChatIntent.created_at.desc()).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def count_sessions(self, status: str | None = None) -> int:
        query = select(func.count()).select_from(ChatSession)
        if status:
            query = query.where(ChatSession.session_status == status)
        return await self.db.scalar(query) or 0

    async def count_all_messages(self) -> int:
        return await self.db.scalar(select(func.count()).select_from(ChatMessage)) or 0

    async def top_intents(self, limit: int = 10) -> list[tuple[str, int]]:
        result = await self.db.execute(
            select(ChatIntent.intent_name, func.count(ChatIntent.id))
            .group_by(ChatIntent.intent_name)
            .order_by(func.count(ChatIntent.id).desc())
            .limit(limit)
        )
        return list(result.all())

    async def list_active_sessions(self, patient_id: int | None = None) -> list[ChatSession]:
        query = select(ChatSession).where(ChatSession.session_status == ChatSessionStatus.ACTIVE)
        if patient_id:
            query = query.where(ChatSession.patient_id == patient_id)
        result = await self.db.execute(query.order_by(ChatSession.started_at.desc()))
        return list(result.scalars().all())

    async def save_entities_json(self, session_pk: int, entities: dict) -> None:
        await self.upsert_memory(session_pk, "entities", json.dumps(entities))
