from fastapi import APIRouter, Form, Request
from fastapi.responses import Response

from app.core.dependencies import DbSession
from app.services.voice_assistant_service import VoiceAssistantService

router = APIRouter()


@router.post("/twiml/start")
async def twiml_start(
    request: Request,
    db: DbSession,
    CallSid: str = Form(default=""),
    From: str = Form(default=""),
    Caller: str = Form(default=""),
    language: str = Form(default="en"),
):
    """Inbound or outbound call entry — greeting and first gather."""
    call_sid = CallSid or "unknown"
    from_number = From or Caller or ""
    xml = await VoiceAssistantService(db).build_start_twiml(
        call_sid, from_number=from_number, language=language
    )
    return Response(content=xml, media_type="application/xml")


@router.post("/twiml/turn")
async def twiml_turn(
    db: DbSession,
    CallSid: str = Form(default=""),
    From: str = Form(default=""),
    SpeechResult: str = Form(default=""),
    Confidence: str = Form(default=""),
    Digits: str = Form(default=""),
):
    """Process one conversational turn from speech or DTMF."""
    xml = await VoiceAssistantService(db).handle_turn(
        call_sid=CallSid or "unknown",
        speech_result=SpeechResult,
        digits=Digits,
        confidence=Confidence or None,
        from_number=From,
    )
    return Response(content=xml, media_type="application/xml")


@router.post("/twiml/inbound")
async def twiml_inbound(
    request: Request,
    db: DbSession,
    CallSid: str = Form(default=""),
    From: str = Form(default=""),
):
    """Alias for Twilio incoming-call webhook."""
    xml = await VoiceAssistantService(db).build_start_twiml(
        CallSid or "unknown", from_number=From or ""
    )
    return Response(content=xml, media_type="application/xml")
