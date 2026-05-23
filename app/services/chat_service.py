import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.symptom_analysis.analyzer import SymptomAnalyzer
from app.core.config import settings
from app.core.constants import ChatSenderType, ChatSessionStatus
from app.core.exceptions import BadRequestException, NotFoundException
from app.models.chat_model import AIResponse, ChatIntent, ChatMessage, ChatSession
from app.repositories.chat_repository import ChatRepository
from app.repositories.patient_repository import PatientRepository
from app.schemas.chat_schema import (
    AIResponseSchema,
    ChatAnalyticsResponse,
    ChatBookAppointmentRequest,
    ChatHistoryResponse,
    ChatIntentResponse,
    ChatMessageResponse,
    ChatSessionCreate,
    ChatSessionResponse,
    EscalateHumanRequest,
    SendMessageRequest,
    SendMessageResponse,
    SymptomAnalysisRequest,
    SymptomAnalysisResponse,
)
from app.services.appointment_service import AppointmentService
from app.utils.ai_llm import llm_service
from app.utils.helpers import generate_chat_session_id, utc_now
from app.utils.redis_service import cache_get, cache_set


class ChatService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ChatRepository(db)
        self.patient_repo = PatientRepository(db)
        self.symptom_analyzer = SymptomAnalyzer()

    async def start_session(self, data: ChatSessionCreate) -> ChatSessionResponse:
        if not await self.patient_repo.get_by_id(data.patient_id):
            raise NotFoundException("Patient not found")

        session = ChatSession(
            session_id=generate_chat_session_id(),
            patient_id=data.patient_id,
            language=data.language,
            session_status=ChatSessionStatus.ACTIVE,
            started_at=utc_now(),
        )
        session = await self.repo.create_session(session)
        await self.repo.upsert_memory(session.id, "language", data.language)

        snapshot = ChatSessionResponse.model_validate(session).model_dump(mode="json")
        await cache_set(
            f"chat:session:{session.session_id}",
            snapshot,
            ttl=settings.CHAT_SESSION_TTL_SECONDS,
        )
        return ChatSessionResponse.model_validate(session)

    async def send_message(self, data: SendMessageRequest) -> SendMessageResponse:
        session = await self._get_active_session(data.session_id)
        language = data.language or session.language

        user_msg = ChatMessage(
            session_id=session.id,
            sender_type=ChatSenderType.USER,
            message=data.message,
            message_type=data.message_type,
            sent_at=utc_now(),
        )
        user_msg = await self.repo.add_message(user_msg)

        intent_data = await llm_service.detect_intent(data.message, language)
        intent = ChatIntent(
            session_id=session.id,
            intent_name=intent_data["intent_name"],
            confidence_score=intent_data["confidence_score"],
            detected_entities=intent_data.get("detected_entities"),
        )
        intent = await self.repo.add_intent(intent)

        context = await self._build_context(session.id)
        llm_result = await llm_service.generate_response(data.message, context, language)
        bot_text = llm_result["response_text"]

        if intent.intent_name == "escalate":
            bot_text = "Connecting you to a human agent. Please hold."
            session.session_status = ChatSessionStatus.ESCALATED

        ai_resp = AIResponse(
            session_id=session.id,
            response_text=bot_text,
            response_type="text",
            confidence_score=llm_result.get("confidence_score", 0.5),
            source=llm_result.get("source", "llm"),
        )
        ai_resp = await self.repo.add_ai_response(ai_resp)

        bot_msg = ChatMessage(
            session_id=session.id,
            sender_type=ChatSenderType.BOT,
            message=bot_text,
            message_type="Text",
            sent_at=utc_now(),
        )
        bot_msg = await self.repo.add_message(bot_msg)

        session.sentiment_score = await llm_service.analyze_sentiment(data.message)
        await self.repo.update_session(session)
        await self._update_redis_session(session)

        return SendMessageResponse(
            user_message=ChatMessageResponse.model_validate(user_msg),
            bot_message=ChatMessageResponse.model_validate(bot_msg),
            intent=ChatIntentResponse.model_validate(intent),
            ai_response=AIResponseSchema.model_validate(ai_resp),
        )

    async def get_history(self, session_id: str) -> ChatHistoryResponse:
        session = await self.repo.get_session_with_messages(session_id)
        if not session:
            raise NotFoundException("Chat session not found")
        messages = [
            ChatMessageResponse.model_validate(m)
            for m in sorted(session.messages, key=lambda m: m.sent_at)
        ]
        return ChatHistoryResponse(
            session=ChatSessionResponse.model_validate(session),
            messages=messages,
        )

    async def end_session(self, session_id: str) -> ChatSessionResponse:
        session = await self.repo.get_session_by_uuid(session_id)
        if not session:
            raise NotFoundException("Chat session not found")
        session.session_status = ChatSessionStatus.CLOSED
        session.ended_at = utc_now()
        session = await self.repo.update_session(session)
        await cache_delete_session(session.session_id)
        return ChatSessionResponse.model_validate(session)

    async def symptom_analysis(self, data: SymptomAnalysisRequest) -> SymptomAnalysisResponse:
        result = await self.symptom_analyzer.analyze(data.symptoms)
        if data.session_id:
            session = await self.repo.get_session_by_uuid(data.session_id)
            if session:
                await self.repo.upsert_memory(
                    session.id, "last_symptoms", json.dumps(data.symptoms)
                )
        return SymptomAnalysisResponse(
            symptoms=result["symptoms"],
            possible_conditions=result.get("possible_conditions", []),
            recommended_specialist=result.get("recommended_specialist", "general_physician"),
            urgency=result.get("urgency", "low"),
        )

    async def book_appointment_via_chat(
        self, data: ChatBookAppointmentRequest, user_id: int
    ):
        session = await self._get_active_session(data.session_id)
        appointment = await AppointmentService(self.db).create(data.appointment, user_id)
        await self.repo.upsert_memory(
            session.id, "last_appointment_id", str(appointment.id)
        )
        return appointment

    async def escalate_human(self, data: EscalateHumanRequest) -> ChatSessionResponse:
        session = await self.repo.get_session_by_uuid(data.session_id)
        if not session:
            raise NotFoundException("Chat session not found")
        session.session_status = ChatSessionStatus.ESCALATED
        if data.reason:
            await self.repo.upsert_memory(session.id, "escalation_reason", data.reason)
        session = await self.repo.update_session(session)
        await self._update_redis_session(session)
        return ChatSessionResponse.model_validate(session)

    async def list_intents(self, page: int = 1, size: int = 20) -> List[ChatIntentResponse]:
        skip = (page - 1) * size
        intents = await self.repo.list_intents(skip=skip, limit=size)
        return [ChatIntentResponse.model_validate(i) for i in intents]

    async def get_analytics(self) -> ChatAnalyticsResponse:
        cache_key = "analytics:ai_chat"
        cached = await cache_get(cache_key)
        if cached:
            return ChatAnalyticsResponse(**cached)

        total_sessions = await self.repo.count_sessions()
        active = await self.repo.count_sessions(ChatSessionStatus.ACTIVE)
        escalated = await self.repo.count_sessions(ChatSessionStatus.ESCALATED)
        total_messages = await self.repo.count_all_messages()
        top = await self.repo.top_intents()
        avg = total_messages / total_sessions if total_sessions else 0.0

        result = ChatAnalyticsResponse(
            total_sessions=total_sessions,
            active_sessions=active,
            escalated_sessions=escalated,
            total_messages=total_messages,
            top_intents=[{"intent": i[0], "count": i[1]} for i in top],
            avg_messages_per_session=round(avg, 2),
        )
        await cache_set(cache_key, result.model_dump(), ttl=settings.ANALYTICS_CACHE_TTL_SECONDS)
        return result

    async def sync_redis_snapshot(self, session_id: str, snapshot: dict) -> None:
        session = await self.repo.get_session_by_uuid(session_id)
        if not session:
            return
        if snapshot.get("sentiment_score") is not None:
            session.sentiment_score = snapshot["sentiment_score"]
            await self.repo.update_session(session)

    async def _get_active_session(self, session_id: str) -> ChatSession:
        session = await self.repo.get_session_by_uuid(session_id)
        if not session:
            raise NotFoundException("Chat session not found")
        if session.session_status == ChatSessionStatus.CLOSED:
            raise BadRequestException("Chat session is closed")
        return session

    async def _build_context(self, session_pk: int) -> List[Dict[str, str]]:
        messages = await self.repo.get_messages(session_pk, limit=20)
        context = []
        for msg in messages[-10:]:
            role = "user" if msg.sender_type == ChatSenderType.USER else "assistant"
            context.append({"role": role, "content": msg.message})
        return context

    async def _update_redis_session(self, session: ChatSession) -> None:
        snapshot = ChatSessionResponse.model_validate(session).model_dump(mode="json")
        await cache_set(
            f"chat:session:{session.session_id}",
            snapshot,
            ttl=settings.CHAT_SESSION_TTL_SECONDS,
        )


async def cache_delete_session(session_id: str) -> None:
    from app.utils.redis_service import cache_delete

    await cache_delete(f"chat:session:{session_id}")
