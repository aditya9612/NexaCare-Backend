from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.core.constants import UserRole
from app.core.dependencies import CurrentUser, DbSession, bearer_scheme
from app.core.exceptions import ForbiddenException
from app.models.user_model import User
from app.schemas.common_schema import APIResponse
from app.schemas.hospital_voice_schema import (
    HospitalFaqCreate,
    HospitalFaqResponse,
    HospitalFaqUpdate,
    HospitalPolicyCreate,
    HospitalPolicyResponse,
    HospitalPolicyUpdate,
    HospitalVoiceConfigCreate,
    HospitalVoiceConfigResponse,
    HospitalVoiceConfigUpdate,
    HospitalVoiceDocumentCreate,
    HospitalVoiceDocumentResponse,
    HospitalVoiceDocumentUpdate,
    VoiceAnalyticsSummary,
    VoiceCallbackTicketResponse,
)
from app.services.hospital_knowledge_service import HospitalKnowledgeService
from app.services.hospital_voice_config_service import HospitalVoiceConfigService
from app.services.reception_transfer_service import ReceptionTransferService
from app.services.voice_analytics_service import VoiceAnalyticsService

router = APIRouter(dependencies=[Depends(bearer_scheme)])


def _require_admin(user: User) -> User:
    if not user.role or user.role.name not in (UserRole.SUPER_ADMIN, UserRole.HOSPITAL_ADMIN):
        raise ForbiddenException("Requires Hospital Admin or Super Admin")
    return user


def _hospital_scope(user: User, hospital_id: int) -> int:
    if user.role and user.role.name == UserRole.SUPER_ADMIN:
        return hospital_id
    if user.hospital_id and user.hospital_id == hospital_id:
        return hospital_id
    if user.role and user.role.name == UserRole.HOSPITAL_ADMIN and user.hospital_id:
        return user.hospital_id
    raise ForbiddenException("Hospital scope mismatch")


@router.get(
    "/hospitals/{hospital_id}/voice-config",
    response_model=APIResponse[HospitalVoiceConfigResponse],
)
async def get_voice_config(hospital_id: int, db: DbSession, current_user: CurrentUser):
    _require_admin(current_user)
    hospital_id = _hospital_scope(current_user, hospital_id)
    data = await HospitalVoiceConfigService(db).get_for_hospital(hospital_id)
    if not data:
        return APIResponse(success=False, message="Voice config not found", data=None)
    return APIResponse(message="Voice config retrieved", data=data)


@router.put(
    "/hospitals/{hospital_id}/voice-config",
    response_model=APIResponse[HospitalVoiceConfigResponse],
)
async def upsert_voice_config(
    hospital_id: int,
    payload: HospitalVoiceConfigUpdate,
    db: DbSession,
    current_user: CurrentUser,
):
    _require_admin(current_user)
    hospital_id = _hospital_scope(current_user, hospital_id)
    data = await HospitalVoiceConfigService(db).upsert(hospital_id, payload)
    return APIResponse(message="Voice config saved", data=data)


@router.post(
    "/hospitals/{hospital_id}/voice-config",
    response_model=APIResponse[HospitalVoiceConfigResponse],
    status_code=201,
)
async def create_voice_config(
    hospital_id: int,
    payload: HospitalVoiceConfigCreate,
    db: DbSession,
    current_user: CurrentUser,
):
    _require_admin(current_user)
    hospital_id = _hospital_scope(current_user, hospital_id)
    payload.hospital_id = hospital_id
    data = await HospitalVoiceConfigService(db).create(payload)
    return APIResponse(message="Voice config created", data=data)


@router.get(
    "/hospitals/{hospital_id}/faqs",
    response_model=APIResponse[list[HospitalFaqResponse]],
)
async def list_faqs(
    hospital_id: int,
    db: DbSession,
    current_user: CurrentUser,
    language: Optional[str] = None,
):
    _require_admin(current_user)
    hospital_id = _hospital_scope(current_user, hospital_id)
    data = await HospitalKnowledgeService(db).list_faqs(hospital_id, language)
    return APIResponse(message="FAQs retrieved", data=data)


@router.post(
    "/hospitals/{hospital_id}/faqs",
    response_model=APIResponse[HospitalFaqResponse],
    status_code=201,
)
async def create_faq(
    hospital_id: int,
    payload: HospitalFaqCreate,
    db: DbSession,
    current_user: CurrentUser,
):
    _require_admin(current_user)
    hospital_id = _hospital_scope(current_user, hospital_id)
    payload.hospital_id = hospital_id
    data = await HospitalKnowledgeService(db).create_faq(payload)
    return APIResponse(message="FAQ created", data=data)


@router.put("/faqs/{faq_id}", response_model=APIResponse[HospitalFaqResponse])
async def update_faq(
    faq_id: int,
    payload: HospitalFaqUpdate,
    db: DbSession,
    current_user: CurrentUser,
):
    _require_admin(current_user)
    existing = await HospitalKnowledgeService(db).get_faq(faq_id)
    _hospital_scope(current_user, existing.hospital_id)
    data = await HospitalKnowledgeService(db).update_faq(faq_id, payload)
    return APIResponse(message="FAQ updated", data=data)


@router.post(
    "/hospitals/{hospital_id}/faqs/seed",
    response_model=APIResponse[dict],
)
async def seed_faqs(hospital_id: int, db: DbSession, current_user: CurrentUser):
    _require_admin(current_user)
    hospital_id = _hospital_scope(current_user, hospital_id)
    count = await HospitalKnowledgeService(db).seed_from_env(hospital_id)
    return APIResponse(message="FAQ seed complete", data={"created": count})


@router.get(
    "/hospitals/{hospital_id}/policies",
    response_model=APIResponse[list[HospitalPolicyResponse]],
)
async def list_policies(
    hospital_id: int,
    db: DbSession,
    current_user: CurrentUser,
    language: Optional[str] = None,
):
    _require_admin(current_user)
    hospital_id = _hospital_scope(current_user, hospital_id)
    data = await HospitalKnowledgeService(db).list_policies(hospital_id, language)
    return APIResponse(message="Policies retrieved", data=data)


@router.post(
    "/hospitals/{hospital_id}/policies",
    response_model=APIResponse[HospitalPolicyResponse],
    status_code=201,
)
async def create_policy(
    hospital_id: int,
    payload: HospitalPolicyCreate,
    db: DbSession,
    current_user: CurrentUser,
):
    _require_admin(current_user)
    hospital_id = _hospital_scope(current_user, hospital_id)
    payload.hospital_id = hospital_id
    data = await HospitalKnowledgeService(db).create_policy(payload)
    return APIResponse(message="Policy created", data=data)


@router.put("/policies/{policy_id}", response_model=APIResponse[HospitalPolicyResponse])
async def update_policy(
    policy_id: int,
    payload: HospitalPolicyUpdate,
    db: DbSession,
    current_user: CurrentUser,
):
    _require_admin(current_user)
    existing = await HospitalKnowledgeService(db).get_policy(policy_id)
    _hospital_scope(current_user, existing.hospital_id)
    data = await HospitalKnowledgeService(db).update_policy(policy_id, payload)
    return APIResponse(message="Policy updated", data=data)


@router.get(
    "/hospitals/{hospital_id}/documents",
    response_model=APIResponse[list[HospitalVoiceDocumentResponse]],
)
async def list_documents(
    hospital_id: int,
    db: DbSession,
    current_user: CurrentUser,
    language: Optional[str] = None,
):
    _require_admin(current_user)
    hospital_id = _hospital_scope(current_user, hospital_id)
    data = await HospitalKnowledgeService(db).list_documents(hospital_id, language)
    return APIResponse(message="Documents retrieved", data=data)


@router.post(
    "/hospitals/{hospital_id}/documents",
    response_model=APIResponse[HospitalVoiceDocumentResponse],
    status_code=201,
)
async def create_document(
    hospital_id: int,
    payload: HospitalVoiceDocumentCreate,
    db: DbSession,
    current_user: CurrentUser,
):
    _require_admin(current_user)
    hospital_id = _hospital_scope(current_user, hospital_id)
    payload.hospital_id = hospital_id
    data = await HospitalKnowledgeService(db).create_document(payload)
    return APIResponse(message="Document created", data=data)


@router.put(
    "/documents/{doc_id}",
    response_model=APIResponse[HospitalVoiceDocumentResponse],
)
async def update_document(
    doc_id: int,
    payload: HospitalVoiceDocumentUpdate,
    db: DbSession,
    current_user: CurrentUser,
):
    _require_admin(current_user)
    existing = await HospitalKnowledgeService(db).get_document(doc_id)
    _hospital_scope(current_user, existing.hospital_id)
    data = await HospitalKnowledgeService(db).update_document(doc_id, payload)
    return APIResponse(message="Document updated", data=data)


@router.get("/analytics/summary", response_model=APIResponse[VoiceAnalyticsSummary])
async def voice_analytics_summary(
    db: DbSession,
    current_user: CurrentUser,
    hospital_id: Optional[int] = None,
    start: Optional[datetime] = Query(default=None),
    end: Optional[datetime] = Query(default=None),
):
    _require_admin(current_user)
    if hospital_id is not None:
        hospital_id = _hospital_scope(current_user, hospital_id)
    elif current_user.role and current_user.role.name == UserRole.HOSPITAL_ADMIN:
        hospital_id = current_user.hospital_id
    data = await VoiceAnalyticsService(db).summary(hospital_id=hospital_id, start=start, end=end)
    return APIResponse(message="Voice analytics summary", data=data)


@router.get(
    "/callback-tickets",
    response_model=APIResponse[list[VoiceCallbackTicketResponse]],
)
async def list_callback_tickets(
    db: DbSession,
    current_user: CurrentUser,
    hospital_id: Optional[int] = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    _require_admin(current_user)
    if hospital_id is not None:
        hospital_id = _hospital_scope(current_user, hospital_id)
    elif current_user.role and current_user.role.name == UserRole.HOSPITAL_ADMIN:
        hospital_id = current_user.hospital_id
    tickets = await ReceptionTransferService(db).list_queued(limit=limit, hospital_id=hospital_id)
    data = [VoiceCallbackTicketResponse.model_validate(t) for t in tickets]
    return APIResponse(message="Callback tickets retrieved", data=data)
