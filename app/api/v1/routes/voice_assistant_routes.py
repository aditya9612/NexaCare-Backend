from fastapi import APIRouter, Form, Request
from fastapi.responses import Response

from app.core.constants import TelephonyProviderType
from app.core.dependencies import DbSession
from app.services.voice_assistant_service import VoiceAssistantService
from app.telephony.webhook_auth import require_voice_webhook_auth
from app.telephony.webhook_normalizer import form_payload_from_request, normalize_webhook

router = APIRouter()


async def _inbound_xml(db, provider: str, request: Request) -> str:
    await require_voice_webhook_auth(request, provider)
    payload = await form_payload_from_request(request)
    normalized = normalize_webhook(provider, payload)
    return await VoiceAssistantService(db).build_start_twiml(
        call_sid=normalized.call_sid or "unknown",
        from_number=normalized.from_number,
        to_number=normalized.to_number,
        provider_name=provider,
    )


@router.post("/twiml/start")
async def twiml_start(request: Request, db: DbSession):
    await require_voice_webhook_auth(request, TelephonyProviderType.TWILIO)
    payload = await form_payload_from_request(request)
    normalized = normalize_webhook(TelephonyProviderType.TWILIO, payload)
    xml = await VoiceAssistantService(db).build_start_twiml(
        normalized.call_sid or "unknown",
        from_number=normalized.from_number,
        to_number=normalized.to_number,
        language=payload.get("language") or "en",
        provider_name=TelephonyProviderType.TWILIO,
    )
    return Response(content=xml, media_type="application/xml")


@router.post("/twiml/inbound")
async def twiml_inbound(request: Request, db: DbSession):
    xml = await _inbound_xml(db, TelephonyProviderType.TWILIO, request)
    return Response(content=xml, media_type="application/xml")


@router.post("/twiml/language")
async def twiml_language(request: Request, db: DbSession):
    await require_voice_webhook_auth(request, TelephonyProviderType.TWILIO)
    payload = await form_payload_from_request(request)
    normalized = normalize_webhook(TelephonyProviderType.TWILIO, payload)
    xml = await VoiceAssistantService(db).handle_language_dtmf(
        call_sid=normalized.call_sid or "unknown",
        digits=normalized.digits,
        from_number=normalized.from_number,
        speech_result=normalized.speech_result,
    )
    return Response(content=xml, media_type="application/xml")


@router.post("/twiml/turn")
async def twiml_turn(request: Request, db: DbSession):
    await require_voice_webhook_auth(request, TelephonyProviderType.TWILIO)
    payload = await form_payload_from_request(request)
    normalized = normalize_webhook(TelephonyProviderType.TWILIO, payload)
    xml = await VoiceAssistantService(db).handle_turn(
        call_sid=normalized.call_sid or "unknown",
        speech_result=normalized.speech_result,
        digits=normalized.digits,
        confidence=normalized.confidence,
        from_number=normalized.from_number,
    )
    return Response(content=xml, media_type="application/xml")


@router.post("/twiml/transfer-result")
async def twiml_transfer_result(request: Request, db: DbSession):
    await require_voice_webhook_auth(request, TelephonyProviderType.TWILIO)
    payload = await form_payload_from_request(request)
    normalized = normalize_webhook(TelephonyProviderType.TWILIO, payload)
    xml = await VoiceAssistantService(db).handle_transfer_result(
        call_sid=normalized.call_sid or "unknown",
        dial_status=payload.get("DialCallStatus") or normalized.call_status,
        from_number=normalized.from_number,
    )
    return Response(content=xml, media_type="application/xml")


@router.post("/exotel/inbound")
async def exotel_inbound(request: Request, db: DbSession):
    xml = await _inbound_xml(db, TelephonyProviderType.EXOTEL, request)
    return Response(content=xml, media_type="application/xml")


@router.post("/exotel/start")
async def exotel_start(request: Request, db: DbSession):
    """Outbound assistant entry for Exotel (mirrors /twiml/start)."""
    await require_voice_webhook_auth(request, TelephonyProviderType.EXOTEL)
    payload = await form_payload_from_request(request)
    normalized = normalize_webhook(TelephonyProviderType.EXOTEL, payload)
    xml = await VoiceAssistantService(db).build_start_twiml(
        normalized.call_sid or "unknown",
        from_number=normalized.from_number,
        to_number=normalized.to_number,
        provider_name=TelephonyProviderType.EXOTEL,
    )
    return Response(content=xml, media_type="application/xml")


@router.post("/exotel/language")
async def exotel_language(request: Request, db: DbSession):
    await require_voice_webhook_auth(request, TelephonyProviderType.EXOTEL)
    payload = await form_payload_from_request(request)
    normalized = normalize_webhook(TelephonyProviderType.EXOTEL, payload)
    xml = await VoiceAssistantService(db).handle_language_dtmf(
        call_sid=normalized.call_sid or "unknown",
        digits=normalized.digits,
        from_number=normalized.from_number,
        speech_result=normalized.speech_result,
    )
    return Response(content=xml, media_type="application/xml")


@router.post("/exotel/turn")
async def exotel_turn(request: Request, db: DbSession):
    await require_voice_webhook_auth(request, TelephonyProviderType.EXOTEL)
    payload = await form_payload_from_request(request)
    normalized = normalize_webhook(TelephonyProviderType.EXOTEL, payload)
    xml = await VoiceAssistantService(db).handle_turn(
        call_sid=normalized.call_sid or "unknown",
        speech_result=normalized.speech_result,
        digits=normalized.digits,
        confidence=normalized.confidence,
        from_number=normalized.from_number,
    )
    return Response(content=xml, media_type="application/xml")


@router.post("/exotel/transfer-result")
async def exotel_transfer_result(request: Request, db: DbSession):
    await require_voice_webhook_auth(request, TelephonyProviderType.EXOTEL)
    payload = await form_payload_from_request(request)
    normalized = normalize_webhook(TelephonyProviderType.EXOTEL, payload)
    xml = await VoiceAssistantService(db).handle_transfer_result(
        call_sid=normalized.call_sid or "unknown",
        dial_status=normalized.call_status,
        from_number=normalized.from_number,
    )
    return Response(content=xml, media_type="application/xml")
