from fastapi import APIRouter, Depends, Request

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.common_schema import APIResponse
from app.schemas.whatsapp_schema import (
    BroadcastRequest,
    DeliveryStatusResponse,
    SendMediaRequest,
    SendMessageRequest,
    SendReminderRequest,
    SendTemplateRequest,
    WebhookPayload,
    WhatsAppAnalyticsResponse,
    WhatsAppMessageResponse,
)
from app.services.whatsapp_service import WhatsAppService
from app.utils.pagination import PaginatedResult

router = APIRouter()


@router.post("/send-message", response_model=APIResponse[WhatsAppMessageResponse], status_code=201)
async def send_message(
    data: SendMessageRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("whatsapp", "create")),
):
    message = await WhatsAppService(db).send_message(data)
    return APIResponse(message="WhatsApp message queued", data=message)


@router.post("/send-template", response_model=APIResponse[WhatsAppMessageResponse], status_code=201)
async def send_template(
    data: SendTemplateRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("whatsapp", "create")),
):
    message = await WhatsAppService(db).send_template(data)
    return APIResponse(message="Template message queued", data=message)


@router.post("/send-media", response_model=APIResponse[WhatsAppMessageResponse], status_code=201)
async def send_media(
    data: SendMediaRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("whatsapp", "create")),
):
    message = await WhatsAppService(db).send_media(data)
    return APIResponse(message="Media message queued", data=message)


@router.post("/send-reminder", response_model=APIResponse[WhatsAppMessageResponse], status_code=201)
async def send_reminder(
    data: SendReminderRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("whatsapp", "create")),
):
    message = await WhatsAppService(db).send_reminder(data)
    return APIResponse(message="Appointment reminder sent", data=message)


@router.post("/broadcast", response_model=APIResponse)
async def broadcast(
    data: BroadcastRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("whatsapp", "create")),
):
    result = await WhatsAppService(db).broadcast(data, current_user.id)
    return APIResponse(message="Broadcast campaign started", data=result)


@router.get("/messages", response_model=APIResponse[PaginatedResult[WhatsAppMessageResponse]])
async def list_messages(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    patient_id: int | None = None,
    delivery_status: str | None = None,
    _: User = Depends(require_permission("whatsapp", "read")),
):
    result = await WhatsAppService(db).list_messages(page, size, patient_id, delivery_status)
    return APIResponse(message="Messages retrieved", data=result)


@router.get("/delivery-status/{message_id}", response_model=APIResponse[DeliveryStatusResponse])
async def delivery_status(
    message_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("whatsapp", "read")),
):
    status = await WhatsAppService(db).get_delivery_status(message_id)
    return APIResponse(message="Delivery status retrieved", data=status)


@router.get("/analytics", response_model=APIResponse[WhatsAppAnalyticsResponse])
async def whatsapp_analytics(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("whatsapp", "read")),
):
    analytics = await WhatsAppService(db).get_analytics()
    return APIResponse(message="WhatsApp analytics retrieved", data=analytics)


@router.post("/webhook")
async def webhook(request: Request, db: DbSession):
    body = await request.json()
    payload = WebhookPayload(
        provider_message_id=body.get("MessageSid") or body.get("provider_message_id"),
        phone_number=body.get("From", "").replace("whatsapp:", ""),
        status=body.get("MessageStatus") or body.get("status"),
        raw=body,
    )
    result = await WhatsAppService(db).handle_webhook(payload)
    return result
