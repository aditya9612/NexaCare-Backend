from typing import Any, Dict, List, Optional

from app.utils.ai_llm import llm_service


class ChatbotHandler:
    async def respond(
        self,
        message: str,
        context: Optional[List[Dict[str, str]]] = None,
        language: str = "en",
    ) -> Dict[str, Any]:
        return await llm_service.generate_response(message, context, language)

    async def detect_intent(self, message: str, language: str = "en") -> Dict[str, Any]:
        return await llm_service.detect_intent(message, language)
