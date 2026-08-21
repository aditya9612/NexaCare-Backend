from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.appointment_assistant.assistant import AppointmentAssistant
from app.ai.symptom_analysis.analyzer import SymptomAnalyzer
from app.ai.rag.rag_service import TRANSFER_PHRASES
from app.models.chat_model import ChatSession
from app.services.faq_retrieval_service import FaqRetrievalService
from app.utils.ai_llm import llm_service


class ChatbotHandler:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.appointment_assistant = AppointmentAssistant(db)
        self.symptom_analyzer = SymptomAnalyzer()
        self.faq_service = FaqRetrievalService(db)

    async def detect_intent(self, message: str, language: str = "en") -> Dict[str, Any]:
        return await llm_service.detect_intent(message, language)

    async def respond(
        self,
        session: ChatSession,
        message: str,
        context: Optional[List[Dict[str, str]]] = None,
        language: str = "en",
        intent_name: str = "general_inquiry",
        user_id: int = 0,
        hospital_id: int | None = None,
    ) -> Dict[str, Any]:
        if intent_name in ("book_appointment", "reschedule_appointment"):
            turn = await self.appointment_assistant.handle_turn(
                session, message, user_id=user_id, language=language
            )
            return {
                "response_text": turn.message,
                "confidence_score": 0.9,
                "source": "appointment_assistant",
                "booking_state": turn.booking_state.to_dict(),
                "suggested_slots": [s.model_dump(mode="json") for s in turn.suggested_slots],
                "appointment": turn.appointment,
                "requires_confirmation": turn.requires_confirmation,
            }

        if intent_name == "symptom_check":
            tokens = [t.strip() for t in message.replace(",", " ").split() if t.strip()]
            analysis = await self.symptom_analyzer.analyze(tokens[:10] or [message])
            text = (
                f"Based on your symptoms, we suggest seeing a {analysis['recommended_specialist'].replace('_', ' ')}. "
                f"Urgency: {analysis['urgency']}. "
                "This is not a diagnosis — please consult a physician. "
                "Would you like me to book an appointment?"
            )
            return {
                "response_text": text,
                "confidence_score": 0.85,
                "source": "symptom_analyzer",
            }

        if intent_name == "faq":
            if not hospital_id:
                return {
                    "response_text": TRANSFER_PHRASES.get(language, TRANSFER_PHRASES["en"]),
                    "confidence_score": 0.0,
                    "source": "transfer",
                    "should_transfer": True,
                    "transfer_reason": "faq_no_hospital",
                }

            faq = await self.faq_service.answer(
                hospital_id,
                message,
                language,
                session_id=session.session_id,
            )
            return {
                "response_text": faq.answer,
                "confidence_score": faq.confidence,
                "source": faq.source or "faq_rag",
                "should_transfer": faq.should_transfer,
                "needs_clarification": faq.needs_clarification,
                "transfer_reason": faq.transfer_reason,
                "faq_hit": faq.faq_hit,
            }

        return await llm_service.generate_response(message, context, language)
