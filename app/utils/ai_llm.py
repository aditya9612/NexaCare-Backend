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
        if settings.OPENAI_API_KEY:
            llm_intent = await self._openai_detect_intent(message, language)
            if llm_intent:
                return llm_intent
        return self._keyword_detect_intent(message, language)

    async def extract_booking_entities(
        self, message: str, language: str = "en"
    ) -> Dict[str, Any]:
        if settings.OPENAI_API_KEY:
            entities = await self._openai_extract_booking(message, language)
            if entities:
                return entities
        return self._keyword_extract_booking(message)

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

    def _keyword_detect_intent(self, message: str, language: str) -> Dict[str, Any]:
        lowered = message.lower()
        intents = {
            "book_appointment": ["appointment", "book", "schedule", "visit"],
            "reschedule_appointment": ["reschedule", "change appointment", "move appointment"],
            "symptom_check": ["symptom", "pain", "fever", "headache", "cough"],
            "faq": ["hours", "location", "cost", "insurance", "contact", "address", "open"],
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

    def _keyword_extract_booking(self, message: str) -> Dict[str, Any]:
        lowered = message.lower()
        entities: Dict[str, Any] = {}
        if any(w in lowered for w in ["fever", "pain", "cough", "headache", "symptom"]):
            entities["symptoms"] = message.strip()
        return entities

    async def _openai_detect_intent(self, message: str, language: str) -> Optional[Dict[str, Any]]:
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            response = await client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Classify user intent for a hospital chatbot. "
                            "Return JSON only: "
                            '{"intent_name": one of book_appointment, reschedule_appointment, '
                            'symptom_check, faq, escalate, cancel_appointment, general_inquiry, '
                            '"confidence_score": 0.0-1.0}'
                        ),
                    },
                    {"role": "user", "content": f"[{language}] {message}"},
                ],
                temperature=0,
                max_completion_tokens=120,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or "{}"
            data = json.loads(raw)
            if "intent_name" in data:
                data["detected_entities"] = json.dumps({"language": language})
                return data
        except Exception as exc:
            logger.error("OpenAI intent detection error: %s", exc)
        return None

    async def _openai_extract_booking(self, message: str, language: str) -> Dict[str, Any]:
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            response = await client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Extract appointment booking fields from the user message. "
                            "Return JSON with optional keys: symptoms, doctor_name, doctor_id, "
                            "appointment_date (YYYY-MM-DD), appointment_time (HH:MM), "
                            "recommended_specialist. Use null for missing fields."
                        ),
                    },
                    {"role": "user", "content": f"[{language}] {message}"},
                ],
                temperature=0,
                max_completion_tokens=200,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or "{}"
            data = json.loads(raw)
            return {k: v for k, v in data.items() if v is not None}
        except Exception as exc:
            logger.error("OpenAI booking extraction error: %s", exc)
            return {}

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
                max_completion_tokens=500,
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
