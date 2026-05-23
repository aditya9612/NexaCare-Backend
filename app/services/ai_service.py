from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings


class AIService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def chat(self, message: str) -> dict:
        if settings.OPENAI_API_KEY:
            return {"reply": f"AI response to: {message}", "source": "openai"}
        return {"reply": "AI service not configured. Set OPENAI_API_KEY.", "source": "stub"}

    async def analyze_symptoms(self, symptoms: list[str]) -> dict:
        return {
            "symptoms": symptoms,
            "suggestions": ["Consult a physician for accurate diagnosis"],
            "urgency": "medium",
        }
