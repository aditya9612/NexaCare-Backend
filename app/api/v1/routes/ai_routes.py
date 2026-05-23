from fastapi import APIRouter, Depends

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.common_schema import APIResponse
from app.schemas.chat_schema import SymptomAnalysisRequest, SymptomAnalysisResponse
from app.services.chat_service import ChatService

router = APIRouter()


@router.post("/symptoms/analyze", response_model=APIResponse[SymptomAnalysisResponse])
async def analyze_symptoms(
    data: SymptomAnalysisRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("ai_chat", "read")),
):
    result = await ChatService(db).symptom_analysis(data)
    return APIResponse(message="Symptom analysis complete", data=result)
