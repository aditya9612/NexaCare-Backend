from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import Response

from app.core.constants import TelephonyProviderType
from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.common_schema import APIResponse
from app.schemas.voice_schema import (
    CallActionRequest,
    CallAnalyticsResponse,
    RescheduleViaVoiceRequest,
    RetryCallRequest,
    ScheduleCallRequest,
    StartCallRequest,
    VoiceCallResponse,
)
from app.services.voice_service import VoiceService
from app.telephony.webhook_auth import require_voice_webhook_auth
from app.telephony.webhook_normalizer import form_payload_from_request
from app.utils.pagination import PaginatedResult

router = APIRouter()


@router.post("/schedule", response_model=APIResponse[VoiceCallResponse], status_code=201)
async def schedule_call(
    data: ScheduleCallRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("voice_reminder", "create")),
):
    call = await VoiceService(db).schedule_call(data)
    return APIResponse(message="Voice call scheduled", data=call)


@router.post("/start-call", response_model=APIResponse[VoiceCallResponse])
async def start_call(
    data: StartCallRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("voice_reminder", "create")),
):
    call = await VoiceService(db).start_call(data)
    return APIResponse(message="Voice call started", data=call)


@router.post("/retry-call", response_model=APIResponse[VoiceCallResponse])
async def retry_call(
    data: RetryCallRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("voice_reminder", "update")),
):
    call = await VoiceService(db).retry_call(data)
    return APIResponse(message="Voice call retry initiated", data=call)


@router.get("/call-history", response_model=APIResponse[PaginatedResult[VoiceCallResponse]])
async def call_history(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    patient_id: int | None = None,
    call_status: str | None = None,
    _: User = Depends(require_permission("voice_reminder", "read")),
):
    result = await VoiceService(db).get_call_history(page, size, patient_id, call_status)
    return APIResponse(message="Call history retrieved", data=result)


@router.get("/call-analytics", response_model=APIResponse[CallAnalyticsResponse])
async def call_analytics(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("voice_reminder", "read")),
):
    analytics = await VoiceService(db).get_analytics()
    return APIResponse(message="Call analytics retrieved", data=analytics)


@router.get("/pending-calls", response_model=APIResponse[list[VoiceCallResponse]])
async def pending_calls(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("voice_reminder", "read")),
):
    calls = await VoiceService(db).get_pending_calls()
    return APIResponse(message="Pending calls retrieved", data=calls)


@router.post("/confirm-appointment", response_model=APIResponse[VoiceCallResponse])
async def confirm_appointment(
    data: CallActionRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("voice_reminder", "update")),
):
    call = await VoiceService(db).confirm_appointment(data)
    return APIResponse(message="Appointment confirmed via voice", data=call)


@router.post("/cancel-appointment", response_model=APIResponse[VoiceCallResponse])
async def cancel_appointment(
    data: CallActionRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("voice_reminder", "update")),
):
    call = await VoiceService(db).cancel_appointment(data)
    return APIResponse(message="Appointment cancelled via voice", data=call)


@router.post("/reschedule-appointment", response_model=APIResponse[VoiceCallResponse])
async def reschedule_appointment(
    data: RescheduleViaVoiceRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("voice_reminder", "update")),
):
    call = await VoiceService(db).reschedule_appointment(data)
    return APIResponse(message="Appointment rescheduled via voice", data=call)


@router.post("/twiml/{call_id}")
async def twiml_initial(call_id: int, request: Request, db: DbSession):
    await require_voice_webhook_auth(request, TelephonyProviderType.TWILIO)
    xml = await VoiceService(db).build_initial_twiml(call_id)
    return Response(content=xml, media_type="application/xml")


@router.post("/twiml/{call_id}/gather")
async def twiml_gather(
    call_id: int,
    request: Request,
    db: DbSession,
    Digits: str = Form(default=""),
):
    await require_voice_webhook_auth(request, TelephonyProviderType.TWILIO)
    xml = await VoiceService(db).handle_dtmf_gather(call_id, Digits)
    return Response(content=xml, media_type="application/xml")


@router.post("/status-callback")
async def status_callback(request: Request, db: DbSession):
    await require_voice_webhook_auth(request, TelephonyProviderType.TWILIO)
    payload = await form_payload_from_request(request)
    payload["_provider"] = "twilio"
    await VoiceService(db).handle_status_callback(payload)
    return Response(content="", status_code=204)


@router.post("/exotel/twiml/{call_id}")
async def exotel_twiml_initial(call_id: int, request: Request, db: DbSession):
    await require_voice_webhook_auth(request, TelephonyProviderType.EXOTEL)
    xml = await VoiceService(db).build_initial_twiml(call_id)
    return Response(content=xml, media_type="application/xml")


@router.post("/exotel/twiml/{call_id}/gather")
async def exotel_twiml_gather(call_id: int, request: Request, db: DbSession):
    await require_voice_webhook_auth(request, TelephonyProviderType.EXOTEL)
    payload = await form_payload_from_request(request)
    digits = str(payload.get("digits") or payload.get("Digits") or "")
    xml = await VoiceService(db).handle_dtmf_gather(call_id, digits)
    return Response(content=xml, media_type="application/xml")


@router.post("/exotel/status-callback")
async def exotel_status_callback(request: Request, db: DbSession):
    await require_voice_webhook_auth(request, TelephonyProviderType.EXOTEL)
    payload = await form_payload_from_request(request)
    payload["_provider"] = "exotel"
    await VoiceService(db).handle_status_callback(payload)
    return Response(content="", status_code=204)
