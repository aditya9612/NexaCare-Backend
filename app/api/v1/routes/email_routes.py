from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.constants import EmailDeliveryStatus, EmailSourceType
from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.common_schema import APIResponse
from app.schemas.email_schema import (
    BroadcastEmailRequest,
    BroadcastResponse,
    EmailBatchResponse,
    EmailMessageResponse,
    SendDirectEmailRequest,
    SendEmailReminderRequest,
    SendMediaEmailRequest,
    SendTemplateEmailRequest,
)
from app.services.email_service import EmailService
from app.utils.pagination import PaginatedResult, PaginationParams, build_paginated_result

router = APIRouter()


@router.post("/send-reminder", response_model=APIResponse[EmailBatchResponse], status_code=status.HTTP_200_OK)
async def send_email_reminders(
    data: SendEmailReminderRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("email", "create")),
):
    """
    Send appointment / follow-up reminders to multiple patients.
    Validates upcoming follow-up dates (Appointments prioritized, Discharge fallback).
    Skips missing, past, or duplicate follow-up records.
    Processes <= 5 patients synchronously, > 5 asynchronously via Celery.
    """
    hospital_id = current_user.hospital_id
    service = EmailService(db)
    batch_response = await service.send_reminders(hospital_id=hospital_id, request=data)
    return APIResponse(message=batch_response.message, data=batch_response)


@router.post("/send-template", response_model=APIResponse[EmailBatchResponse], status_code=status.HTTP_200_OK)
async def send_template_email(
    data: SendTemplateEmailRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("email", "create")),
):
    """
    Send templated emails to multiple patients with patient-specific variable rendering.
    Enforces tenant isolation and independent delivery tracking.
    """
    hospital_id = current_user.hospital_id
    service = EmailService(db)
    batch_response = await service.send_template(hospital_id=hospital_id, request=data)
    return APIResponse(message=batch_response.message, data=batch_response)


@router.post("/send-media", response_model=APIResponse[EmailBatchResponse], status_code=status.HTTP_200_OK)
async def send_media_email(
    data: SendMediaEmailRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("email", "create")),
):
    """
    Send media/document attachments or download links to multiple patients.
    """
    hospital_id = current_user.hospital_id
    service = EmailService(db)
    batch_response = await service.send_media(hospital_id=hospital_id, request=data)
    return APIResponse(message=batch_response.message, data=batch_response)


@router.post("/send-message", response_model=APIResponse[EmailMessageResponse], status_code=status.HTTP_201_CREATED)
async def send_direct_message(
    data: SendDirectEmailRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("email", "create")),
):
    """
    Send a direct single transactional email message.
    """
    hospital_id = current_user.hospital_id
    service = EmailService(db)
    message = await service.send_direct_message(hospital_id=hospital_id, request=data)
    return APIResponse(message="Email dispatched successfully", data=EmailMessageResponse.model_validate(message))


@router.post("/broadcast", response_model=APIResponse[BroadcastResponse], status_code=status.HTTP_200_OK)
async def broadcast_email(
    data: BroadcastEmailRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("email", "create")),
):
    """
    Create a broadcast campaign for multiple email addresses, with optional scheduling.
    """
    hospital_id = current_user.hospital_id
    service = EmailService(db)
    response = await service.create_broadcast_campaign(
        hospital_id=hospital_id,
        request=data,
        created_by=current_user.id,
    )
    return APIResponse(message=response.message, data=response)


@router.get("/batch/{batch_id}", response_model=APIResponse[EmailBatchResponse], status_code=status.HTTP_200_OK)
async def get_batch_status(
    batch_id: str,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("email", "read")),
):
    """
    Retrieve real-time processing status and per-patient results for a batch.
    """
    hospital_id = current_user.hospital_id
    service = EmailService(db)
    batch_res = await service.get_batch_status(batch_id=batch_id, hospital_id=hospital_id)
    if not batch_res:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Email batch '{batch_id}' not found",
        )
    return APIResponse(message="Batch details retrieved", data=batch_res)


@router.get("/messages", response_model=APIResponse[PaginatedResult[EmailMessageResponse]], status_code=status.HTTP_200_OK)
async def list_email_messages(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    email_status: EmailDeliveryStatus | None = Query(None, alias="status"),
    patient_id: int | None = Query(None),
    source_type: EmailSourceType | None = Query(None),
    search: str | None = Query(None),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    _: User = Depends(require_permission("email", "read")),
):
    """
    Paginated list of email message logs with filtering.
    """
    hospital_id = current_user.hospital_id
    service = EmailService(db)
    pagination = PaginationParams(page=page, size=size)
    items, total = await service.repo.list_messages(
        hospital_id=hospital_id,
        pagination=pagination,
        status=email_status.value if email_status else None,
        patient_id=patient_id,
        source_type=source_type.value if source_type else None,
        search=search,
        start_date=start_date,
        end_date=end_date,
    )
    pydantic_items = [EmailMessageResponse.model_validate(item) for item in items]
    result = build_paginated_result(pydantic_items, total, pagination.page, pagination.size)
    return APIResponse(message="Email messages retrieved", data=result)


@router.get("/messages/{message_id}", response_model=APIResponse[EmailMessageResponse], status_code=status.HTTP_200_OK)
async def get_email_message(
    message_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("email", "read")),
):
    """
    Get detailed email message audit trail and delivery events.
    """
    hospital_id = current_user.hospital_id
    service = EmailService(db)
    msg = await service.repo.get_message_details(message_id=message_id, hospital_id=hospital_id)
    if not msg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Email message {message_id} not found",
        )
    return APIResponse(message="Email message details retrieved", data=EmailMessageResponse.model_validate(msg))
