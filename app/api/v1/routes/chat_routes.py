from fastapi import APIRouter, Depends

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.chat_schema import (
    BookingStateResponse,
    ChatAnalyticsResponse,
    ChatBookAppointmentRequest,
    ChatHistoryResponse,
    ChatIntentResponse,
    ChatSessionCreate,
    ChatSessionResponse,
    EscalateHumanRequest,
    SendMessageRequest,
    SendMessageResponse,
    SymptomAnalysisRequest,
    SymptomAnalysisResponse,
)
from app.schemas.common_schema import APIResponse
from app.services.chat_service import ChatService

router = APIRouter()


@router.post("/start-session", response_model=APIResponse[ChatSessionResponse], status_code=201)
async def start_session(
    data: ChatSessionCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("ai_chat", "create")),
):
    session = await ChatService(db).start_session(data)
    return APIResponse(message="Chat session started", data=session)


@router.post("/send-message", response_model=APIResponse[SendMessageResponse])
async def send_message(
    data: SendMessageRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("ai_chat", "create")),
):
    result = await ChatService(db).send_message(data, user_id=current_user.id)
    return APIResponse(message="Message processed", data=result)


@router.get("/booking-state/{session_id}", response_model=APIResponse[BookingStateResponse])
async def get_booking_state(
    session_id: str,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("ai_chat", "read")),
):
    state = await ChatService(db).get_booking_state(session_id)
    return APIResponse(message="Booking state retrieved", data=state)


@router.get("/history/{session_id}", response_model=APIResponse[ChatHistoryResponse])
async def get_history(
    session_id: str,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("ai_chat", "read")),
):
    history = await ChatService(db).get_history(session_id)
    return APIResponse(message="Chat history retrieved", data=history)


@router.post("/end-session", response_model=APIResponse[ChatSessionResponse])
async def end_session(
    session_id: str,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("ai_chat", "update")),
):
    session = await ChatService(db).end_session(session_id)
    return APIResponse(message="Chat session ended", data=session)


@router.post("/symptom-analysis", response_model=APIResponse[SymptomAnalysisResponse])
async def symptom_analysis(
    data: SymptomAnalysisRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("ai_chat", "read")),
):
    result = await ChatService(db).symptom_analysis(data)
    return APIResponse(message="Symptom analysis complete", data=result)


@router.post("/book-appointment", response_model=APIResponse)
async def book_appointment(
    data: ChatBookAppointmentRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("ai_chat", "create")),
):
    appointment = await ChatService(db).book_appointment_via_chat(data, current_user.id)
    return APIResponse(message="Appointment booked via chatbot", data=appointment)


@router.post("/escalate-human", response_model=APIResponse[ChatSessionResponse])
async def escalate_human(
    data: EscalateHumanRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("ai_chat", "update")),
):
    session = await ChatService(db).escalate_human(data)
    return APIResponse(message="Escalated to human agent", data=session)


@router.get("/intents", response_model=APIResponse[list[ChatIntentResponse]])
async def list_intents(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    _: User = Depends(require_permission("ai_chat", "read")),
):
    intents = await ChatService(db).list_intents(page=page, size=size)
    return APIResponse(message="Intents retrieved", data=intents)


@router.get("/analytics", response_model=APIResponse[ChatAnalyticsResponse])
async def chat_analytics(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("ai_chat", "read")),
):
    analytics = await ChatService(db).get_analytics()
    return APIResponse(message="Chat analytics retrieved", data=analytics)
