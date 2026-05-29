from fastapi import APIRouter, Depends

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.common_schema import APIResponse
from app.schemas.chat_schema import SymptomAnalysisRequest, SymptomAnalysisResponse
from app.services.chat_service import ChatService
from app.schemas.ai_config_schema import AIConfigResponse, AIConfigUpdate, AIFeatureToggleRequest
from app.services.ai_config_service import AIConfigService

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


@router.get("/configurations", response_model=APIResponse[list[AIConfigResponse]])
async def list_ai_configurations(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("ai_chat", "read")),
):
    configs = await AIConfigService(db).list_configurations()
    return APIResponse(message="AI configurations retrieved successfully", data=configs)


@router.put("/configurations/{feature_name}", response_model=APIResponse[AIConfigResponse])
async def update_ai_configuration(
    feature_name: str,
    data: AIConfigUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("ai_chat", "update")),
):
    config = await AIConfigService(db).update_configuration(feature_name, data, current_user.id)
    return APIResponse(message="AI configuration updated successfully", data=config)


@router.post("/toggle-feature", response_model=APIResponse[AIConfigResponse])
async def toggle_ai_feature(
    data: AIFeatureToggleRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("ai_chat", "update")),
):
    config = await AIConfigService(db).toggle_feature(data, current_user.id)
    return APIResponse(message="AI feature toggled successfully", data=config)
