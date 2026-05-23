import json
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logger import logger


class LLMService:
    """OpenAI-ready LLM integration with graceful fallback."""

    async def generate_response(
        self,
        message: str,
        context: Optional[List[Dict[str, str]]] = None,
        language: str = "en",
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        if settings.OPENAI_API_KEY:
            return await self._openai_generate(message, context, language, system_prompt)
        return self._fallback_response(message, language)

    async def detect_intent(self, message: str, language: str = "en") -> Dict[str, Any]:
        lowered = message.lower()
        intents = {
            "book_appointment": ["appointment", "book", "schedule", "visit"],
            "symptom_check": ["symptom", "pain", "fever", "headache", "cough"],
            "faq": ["hours", "location", "cost", "insurance", "contact"],
            "escalate": ["human", "agent", "speak to", "representative"],
            "cancel_appointment": ["cancel"],
        }
        for intent_name, keywords in intents.items():
            if any(kw in lowered for kw in keywords):
                return {
                    "intent_name": intent_name,
                    "confidence_score": 0.85,
                    "detected_entities": json.dumps({"language": language}),
                }
        return {
            "intent_name": "general_inquiry",
            "confidence_score": 0.6,
            "detected_entities": json.dumps({"language": language}),
        }

    async def analyze_sentiment(self, message: str) -> float:
        negative = ["angry", "frustrated", "terrible", "worst", "hate"]
        positive = ["thank", "great", "good", "helpful", "excellent"]
        lowered = message.lower()
        score = 0.5
        if any(w in lowered for w in negative):
            score = 0.2
        elif any(w in lowered for w in positive):
            score = 0.8
        return score

    async def _openai_generate(
        self,
        message: str,
        context: Optional[List[Dict[str, str]]],
        language: str,
        system_prompt: Optional[str],
    ) -> Dict[str, Any]:
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            messages = [
                {
                    "role": "system",
                    "content": system_prompt
                    or (
                        "You are a helpful healthcare assistant for a hospital. "
                        f"Respond in language code '{language}'. "
                        "Never provide definitive diagnoses. Encourage professional care."
                    ),
                },
            ]
            if context:
                messages.extend(context)
            messages.append({"role": "user", "content": message})

            response = await client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=messages,
                temperature=0.4,
                max_tokens=500,
            )
            text = response.choices[0].message.content or ""
            return {
                "response_text": text,
                "confidence_score": 0.9,
                "source": "openai",
            }
        except Exception as exc:
            logger.error("OpenAI error: %s", exc)
            fallback = self._fallback_response(message, language)
            fallback["source"] = "fallback"
            return fallback

    def _fallback_response(self, message: str, language: str) -> Dict[str, Any]:
        replies = {
            "en": (
                "I'm your healthcare assistant. I can help with appointments, "
                "symptoms, and FAQs. How can I help you today?"
            ),
            "hi": "मैं आपकी स्वास्थ्य सहायक हूँ। मैं अपॉइंटमेंट और लक्षणों में मदद कर सकती हूँ।",
            "es": "Soy su asistente de salud. Puedo ayudar con citas y síntomas.",
        }
        return {
            "response_text": replies.get(language, replies["en"]),
            "confidence_score": 0.5,
            "source": "stub",
        }


llm_service = LLMService()
