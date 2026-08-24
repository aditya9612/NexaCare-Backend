"""
app/agent/router.py
-------------------
FastAPI router for NexaCare AI Voice Agent webhooks.
Mounted at: /agent/v1/voice

Wires Flow A production services (hospital config, language resolver,
FAQ, medical safety, reception transfer, Redis sessions) into Flow B
booking conversation — without changing booking business logic.
"""

import logging
import traceback
from datetime import datetime, timezone

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import PlainTextResponse

from app.agent import session_store
from app.agent.conversation import (
    ConversationIntent,
    add_faq_topic,
    booking_lock_redirect_message,
    bump_counter,
    booking_steps,
    check_conversation_limits,
    detect_yes_no,
    init_call_timestamps,
    is_booking_lock_active,
    is_phase6_enabled,
    limit_message,
    record_analytics_event,
    route_intent,
    should_allow_intent_switch,
    update_memory,
)
from app.agent.nodes import language as lang_node
from app.agent.nodes import greeting as greet_node
from app.agent.nodes import booking as book_node
from app.core.constants import TelephonyProviderType
from app.core.dependencies import DbSession
from app.services.faq_retrieval_service import TRANSFER_PHRASES, FaqRetrievalService
from app.services.hospital_voice_config_service import (
    HospitalVoiceConfigService,
    log_hospital_resolution,
    log_hospital_resolution_attempt,
    mask_inbound_did,
)
from app.utils.phone_utils import normalize_inbound_did
from app.utils.redis_service import redis_cooldown_active
from app.services.language_resolver_service import LanguageResolverService
from app.services.medical_safety_guard import MedicalSafetyGuard
from app.services.reception_transfer_service import ReceptionTransferService
from app.telephony.factory import ProviderFactory
from app.telephony.webhook_auth import require_voice_webhook_auth

logger = logging.getLogger("nexacare.agent.router")

router = APIRouter(tags=["AI Voice Agent"])

_TWILIO_LANG = {"en": "en-IN", "hi": "hi-IN", "mr": "mr-IN"}


# ── Helpers ────────────────────────────────────────────────────────────────────

def xml(twiml: str) -> Response:
    return Response(content=twiml, media_type="application/xml; charset=utf-8")


async def _require_agent_webhook(request: Request) -> None:
    """Agent webhooks are Twilio-oriented by default."""
    logger.info(
        "TRACE _require_agent_webhook ENTER path=%s method=%s",
        request.url.path,
        request.method,
    )
    await require_voice_webhook_auth(request, TelephonyProviderType.TWILIO)
    logger.info("TRACE _require_agent_webhook EXIT path=%s (auth passed/skipped)", request.url.path)


def _base_url() -> str:
    """Read PUBLIC_BASE_URL from settings, trying multiple attribute names."""
    try:
        from app.core.config import settings
        for attr in ["PUBLIC_BASE_URL", "public_base_url", "BASE_URL", "base_url"]:
            val = getattr(settings, attr, None)
            if val:
                logger.debug(f"base_url from settings.{attr} = {val}")
                return val.rstrip("/")
    except Exception as e:
        logger.warning(f"Could not read settings: {e}")

    import os
    val = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
    logger.debug(f"base_url from os.getenv = {val}")
    return val.rstrip("/")


def _hospital_session_updates(state: dict, result) -> dict:
    """Merge resolved hospital config into session fields without overwriting caller data."""
    config = result.config
    updates: dict = {
        "hospital_id": result.hospital_id,
        "hospital_resolution_source": result.source.value,
    }
    if config:
        if not state.get("reception_number"):
            updates["reception_number"] = config.reception_number
        if not state.get("voice_profile"):
            updates["voice_profile"] = config.voice_profile
        if not state.get("voice_gender"):
            updates["voice_gender"] = config.voice_gender
    return updates


async def _ensure_session_hospital(
    db,
    call_sid: str,
    state: dict,
    *,
    step: str = "",
    service: str = "",
) -> int | None:
    """Return validated hospital_id from session or safe inbound resolution."""
    if state.get("hospital_id"):
        return state["hospital_id"]

    to_number = state.get("to_number") or ""
    log_hospital_resolution_attempt(
        call_sid=call_sid,
        masked_did=mask_inbound_did(to_number),
        normalized_did=normalize_inbound_did(to_number),
        step=step or state.get("step") or "",
        service=service or state.get("service") or "",
    )

    svc = HospitalVoiceConfigService(db)
    result = await svc.resolve_inbound_hospital(to_number=state.get("to_number") or "")
    log_hospital_resolution(
        result,
        call_sid=call_sid,
        masked_did=mask_inbound_did(state.get("to_number") or ""),
        step=step or state.get("step") or "",
        service=service or state.get("service") or "",
    )
    if not result.hospital_id:
        return None

    updates = _hospital_session_updates(state, result)
    await session_store.update_session(call_sid, updates)
    state.update(updates)
    return result.hospital_id


async def _transfer_no_hospital(
    db,
    call_sid: str,
    state: dict,
    *,
    reason: str,
    service: str = "",
) -> str:
    lang = state.get("language") or "en"
    phrase = TRANSFER_PHRASES.get(lang, TRANSFER_PHRASES["en"])
    bump_counter(state, "transfer_count")
    record_analytics_event(state, "transfer", reason=reason)
    logger.warning(
        "voice_transfer_no_hospital call_sid=%s reason=%s service=%s step=%s masked_did=%s",
        call_sid,
        reason,
        service or state.get("service"),
        state.get("step"),
        mask_inbound_did(state.get("to_number") or ""),
    )
    twiml = await _do_reception_transfer(db, state, reason=reason, preface=phrase)
    await session_store.delete_session(call_sid)
    return twiml


def _error_twiml(msg: str = None) -> str:
    text = msg or "We are sorry, something went wrong. Please call again. Goodbye."
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Response><Say language="en-IN">{text}</Say><Hangup/></Response>'
    )


def _log_request(route: str, call_sid: str, **kwargs):
    extras = " | ".join(f"{k}={v!r}" for k, v in kwargs.items() if v)
    logger.info(f"▶ {route} | SID={call_sid}" + (f" | {extras}" if extras else ""))


def _greeting_twiml(state) -> str:
    return greet_node.build_greeting_twiml(
        state["base_url"],
        state["language"],
        state["twilio_language"],
        voice_profile=state.get("voice_profile"),
    )


async def _goodbye_twiml_and_cleanup(call_sid: str, state: dict) -> str:
    """Speak localized goodbye and remove session (Phase 6.9)."""
    record_analytics_event(state, "goodbye")
    twiml = greet_node.build_goodbye_twiml(state)
    await session_store.delete_session(call_sid)
    return twiml


async def _limit_twiml_and_cleanup(call_sid: str, state: dict) -> str:
    """End call when conversation limits are exceeded (Phase 6.8)."""
    lang = state.get("language") or "en"
    vp = state.get("voice_profile")
    record_analytics_event(state, "limit_exceeded")
    twiml = book_node._hangup_twiml(
        limit_message(lang),
        state["twilio_language"],
        base_url=state.get("base_url", ""),
        voice_profile=vp,
    )
    await session_store.delete_session(call_sid)
    return twiml


def _prepend_say_to_twiml(twiml: str, say_xml: str) -> str:
    """Inject a Say element immediately inside <Response> without changing builders."""
    marker = "<Response>"
    idx = twiml.find(marker)
    if idx < 0:
        return twiml
    insert_at = idx + len(marker)
    return twiml[:insert_at] + say_xml + twiml[insert_at:]


def _booking_lock_redirect_twiml(state: dict) -> str:
    """
    Speak booking-lock redirect, then re-prompt the current booking step.
    Does not mutate step/service or set return_step.
    """
    lang = state.get("language") or "en"
    twilio_lang = state.get("twilio_language") or "en-IN"
    vp = state.get("voice_profile")
    base_url = state.get("base_url", "")
    redirect = booking_lock_redirect_message(lang)
    say_xml = book_node._say(redirect, twilio_lang, base_url=base_url, voice_profile=vp)
    step = state.get("step") or ""
    action = f"{state['base_url']}/agent/v1/voice/turn"

    if step == "collect_name":
        return _prepend_say_to_twiml(book_node.build_collect_name_twiml(state), say_xml)

    if step == "collect_problem":
        prompt = book_node._s("ask_problem", lang)
        gather = book_node._gather_speech(
            action,
            prompt,
            twilio_lang,
            lang_code=lang,
            timeout=book_node._speech_timeout_for(lang, base=10),
            base_url=base_url,
            voice_profile=vp,
        )
        return book_node._twiml(say_xml, gather)

    if step == "suggest_doctors":
        doctors = state.get("suggested_doctors") or []
        return _prepend_say_to_twiml(
            book_node.build_suggest_doctors_twiml(state, doctors),
            say_xml,
        )

    if step == "select_slot":
        slots = state.get("available_slots") or []
        return _prepend_say_to_twiml(
            book_node.build_select_slot_twiml(state, slots),
            say_xml,
        )

    # confirm or unknown booking step: say redirect and re-enter /turn
    from xml.sax.saxutils import escape

    return book_node._twiml(
        say_xml,
        f'<Redirect method="POST">{escape(action)}</Redirect>',
    )


async def _enter_booking_flow(
    db,
    call_sid: str,
    state: dict,
    resume: bool = False,
) -> str:
    """Start or resume booking without restarting call/session (Phase 6.3)."""
    hospital_id = await _ensure_session_hospital(
        db, call_sid, state, step=state.get("step") or "", service="book"
    )
    if not hospital_id:
        return await _transfer_no_hospital(
            db, call_sid, state, reason="booking_no_hospital", service="book"
        )

    updates = {
        "service": "book",
        "retry_count": 0,
        "current_intent": ConversationIntent.BOOKING.value,
    }
    if resume and state.get("return_step") in booking_steps():
        updates["step"] = state["return_step"]
        updates["return_step"] = None
        updates["return_service"] = None
    else:
        updates["step"] = "collect_name"
    bump_counter(state, "booking_count")
    record_analytics_event(state, "booking_start", resume=resume)
    updates["booking_count"] = state.get("booking_count", 0)
    await session_store.update_session(call_sid, updates)
    state = await session_store.get_session(call_sid)
    return book_node.build_collect_name_twiml(state)


def _is_unclear_stt(transcript: str, confidence: float) -> bool:
    """
    Match Flow A VoiceAppointmentAssistant.process_turn STT gate.
    Unknown Twilio confidence (-1.0) does not alone trigger retry.
    """
    if not (transcript or "").strip():
        return True
    if confidence >= 0.0 and confidence < 0.4:
        return True
    return False


async def _handle_faq_stt_retry(
    db,
    call_sid: str,
    state: dict,
) -> str:
    """Retry FAQ prompt on empty/low-confidence STT; transfer after existing limit."""
    from app.ai.voice_appointment_assistant.prompts import could_not_hear

    lang = state.get("language") or "en"
    retry = state.get("retry_count", 0) + 1
    logger.info(
        "  ↳ [%s] FAQ STT unclear (retry %s/%s)",
        call_sid,
        retry,
        book_node.MAX_RETRIES,
    )

    if retry > book_node.MAX_RETRIES:
        bump_counter(state, "transfer_count")
        record_analytics_event(state, "transfer", reason="stt_unclear")
        twiml = await _do_reception_transfer(
            db,
            state,
            reason="stt_unclear",
            preface=could_not_hear(lang),
        )
        await session_store.delete_session(call_sid)
        return twiml

    await session_store.update_session(
        call_sid,
        {"retry_count": retry, "step": "faq_question"},
    )
    state = await session_store.get_session(call_sid)
    twilio_lang = state.get("twilio_language") or "en-IN"
    vp = state.get("voice_profile")
    base_url = state.get("base_url", "")
    say_xml = book_node._say(
        could_not_hear(lang),
        twilio_lang,
        base_url=base_url,
        voice_profile=vp,
    )
    return _prepend_say_to_twiml(greet_node.build_ask_faq_twiml(state), say_xml)


async def _process_faq_transcript(
    db,
    call_sid: str,
    state: dict,
    transcript: str,
    *,
    phase6: bool,
    confidence: float = -1.0,
) -> str:
    """Run FAQ retrieval pipeline; terminal or continue based on phase flag."""
    lang = state.get("language") or "en"
    vp = state.get("voice_profile")
    transcript = (transcript or "").strip()

    if _is_unclear_stt(transcript, confidence):
        return await _handle_faq_stt_retry(db, call_sid, state)

    safety = MedicalSafetyGuard.check(transcript, lang)
    if safety.is_medical_advice:
        bump_counter(state, "transfer_count")
        record_analytics_event(state, "transfer", reason="medical_advice_refused")
        await session_store.update_session(call_sid, {"step": "transfer"})
        twiml = await _do_reception_transfer(
            db,
            state,
            reason="medical_advice_refused",
            preface=safety.refusal_message,
        )
        await session_store.delete_session(call_sid)
        return twiml

    hospital_id = await _ensure_session_hospital(
        db, call_sid, state, step="faq_question", service="faq"
    )
    if not hospital_id:
        return await _transfer_no_hospital(
            db, call_sid, state, reason="faq_no_hospital", service="faq"
        )

    faq = await FaqRetrievalService(db).answer(
        hospital_id, transcript, lang, session_id=call_sid
    )
    update_memory(
        state,
        question=transcript,
        answer=faq.answer,
        topic=transcript,
        intent=ConversationIntent.FAQ.value,
        increment_question=True,
    )
    bump_counter(state, "faq_count")
    add_faq_topic(state, transcript)
    record_analytics_event(
        state,
        "faq_answer",
        source=faq.source,
        confidence=faq.confidence,
    )

    if faq.should_transfer:
        bump_counter(state, "transfer_count")
        transfer_reason = faq.transfer_reason or "faq_low_confidence"
        record_analytics_event(state, "transfer", reason=transfer_reason)
        twiml = await _do_reception_transfer(
            db,
            state,
            reason=transfer_reason,
            preface=faq.answer or TRANSFER_PHRASES.get(lang, TRANSFER_PHRASES["en"]),
        )
        await session_store.delete_session(call_sid)
        return twiml

    if not phase6:
        await session_store.delete_session(call_sid)
        return book_node._hangup_twiml(
            faq.answer,
            state["twilio_language"],
            base_url=state.get("base_url", ""),
            voice_profile=vp,
        )

    await session_store.update_session(
        call_sid,
        {
            "step": "faq_continue",
            "last_question": state.get("last_question"),
            "last_answer": state.get("last_answer"),
            "current_topic": state.get("current_topic"),
            "current_intent": state.get("current_intent"),
            "question_count": state.get("question_count"),
            "faq_count": state.get("faq_count"),
            "faq_topics": state.get("faq_topics"),
            "conversation_analytics": state.get("conversation_analytics"),
        },
    )
    state = await session_store.get_session(call_sid)
    return greet_node.build_faq_continue_twiml(state, prefix=faq.answer or "")


async def _handle_pre_intent_route(
    db,
    call_sid: str,
    state: dict,
    transcript: str,
    step: str,
) -> str | None:
    """
    Pre-state intent routing (Phase 6.5). Returns TwiML when routed, else None.
    Router classifies only — booking execution stays in existing handlers.
    """
    if not transcript:
        return None

    intent = route_intent(transcript, state)
    update_memory(state, intent=intent.value)
    if intent == ConversationIntent.UNKNOWN:
        bump_counter(state, "unknown_count")
        record_analytics_event(state, "unknown_intent", transcript=transcript[:200])
        return None

    record_analytics_event(state, "intent_route", intent=intent.value)

    if intent == ConversationIntent.GOODBYE:
        return await _goodbye_twiml_and_cleanup(call_sid, state)

    if intent == ConversationIntent.TRANSFER:
        bump_counter(state, "transfer_count")
        await session_store.update_session(call_sid, {"step": "transfer"})
        twiml = await _do_reception_transfer(db, state, reason="caller_requested_reception")
        await session_store.delete_session(call_sid)
        return twiml

    if intent == ConversationIntent.BOOKING and step in {
        "faq_continue",
        "post_booking_continue",
        "greeting",
    }:
        return await _enter_booking_flow(db, call_sid, state, resume=False)

    # Booking lock: FAQ must not leave an active booking transaction.
    if intent == ConversationIntent.FAQ and is_booking_lock_active(state):
        if not should_allow_intent_switch(state, intent):
            record_analytics_event(state, "booking_lock_redirect", intent=intent.value)
            await session_store.update_session(
                call_sid,
                {"conversation_analytics": state.get("conversation_analytics")},
            )
            return _booking_lock_redirect_twiml(state)
        return None

    return None


async def _do_reception_transfer(
    db,
    state,
    *,
    reason: str,
    preface: str | None = None,
) -> str:
    """Call existing ReceptionTransferService — no second transfer implementation."""
    config = None
    hospital_id = state.get("hospital_id")
    if hospital_id:
        config = await HospitalVoiceConfigService(db).get_entity(hospital_id)
    provider = ProviderFactory.from_hospital_config(config)
    reception = (
        state.get("reception_number")
        or (getattr(config, "reception_number", None) if config else None)
    )
    action_url = f"{state['base_url']}/agent/v1/voice/transfer-result"
    result = await ReceptionTransferService(db).transfer(
        reception_number=reception,
        from_number=state.get("from_number") or "",
        language=state.get("language") or "en",
        hospital_id=hospital_id,
        patient_id=state.get("patient_id"),
        call_id=None,
        reason=reason,
        provider=provider,
        action_url=action_url,
    )
    try:
        from app.tasks.voice_tasks import process_reception_callback_tickets

        if result.ticket_id:
            if redis_cooldown_active():
                logger.info(
                    "callback_enqueue_skipped call_sid=%s reason=redis_unavailable ticket_id=%s",
                    state.get("call_sid"),
                    result.ticket_id,
                )
            else:
                process_reception_callback_tickets.delay()
                logger.info(
                    "callback_enqueue_success call_sid=%s ticket_id=%s",
                    state.get("call_sid"),
                    result.ticket_id,
                )
    except Exception as exc:
        logger.warning(
            "callback_enqueue_failed call_sid=%s ticket_id=%s error=%s",
            state.get("call_sid"),
            getattr(result, "ticket_id", None),
            exc,
        )

    twiml = result.xml
    if preface and "<Response>" in twiml:
        from xml.sax.saxutils import escape
        from app.utils.twiml_builder import twilio_say_language

        lang = twilio_say_language(state.get("language") or "en")
        vp = state.get("voice_profile")
        voice_attr = f' voice="{escape(vp)}"' if vp else ""
        say_preface = (
            f'<Say language="{escape(lang)}"{voice_attr}>{escape(preface)}</Say>'
        )
        twiml = twiml.replace("<Response>", f"<Response>{say_preface}", 1)
    return twiml


# ── Route 1: Incoming call ─────────────────────────────────────────────────────
@router.post("/incoming")
async def incoming_call(
    request: Request,
    db: DbSession,
    CallSid: str = Form(default=""),
    From: str = Form(default=""),
    Caller: str = Form(default=""),
    To: str = Form(default=""),
):
    logger.info(
        "TRACE incoming_call ROUTE ENTRY path=%s url=%s CallSid=%r From=%r Caller=%r To=%r",
        request.url.path,
        str(request.url),
        CallSid,
        From,
        Caller,
        To,
    )
    await _require_agent_webhook(request)
    logger.info("TRACE incoming_call AFTER auth CallSid=%r", CallSid)
    call_sid = CallSid or "unknown"
    from_number = From or Caller or ""
    to_number = To or ""
    _log_request("INCOMING", call_sid, From=from_number, To=to_number)

    try:
        base_url = _base_url()
        logger.info(f"  ↳ base_url={base_url}")

        # Phase 1: hospital config (reuse Flow A service)
        voice_svc = HospitalVoiceConfigService(db)
        log_hospital_resolution_attempt(
            call_sid=call_sid,
            masked_did=mask_inbound_did(to_number),
            normalized_did=normalize_inbound_did(to_number),
            step="incoming",
        )
        resolution_result = await voice_svc.resolve_inbound_hospital(to_number=to_number)
        active_configs = await voice_svc.repo.list_active()
        log_hospital_resolution(
            resolution_result,
            call_sid=call_sid,
            masked_did=mask_inbound_did(to_number),
            step="incoming",
            active_config_count=len(active_configs),
        )
        if resolution_result.source.value == "unresolved" and to_number:
            await voice_svc.validate_twilio_did_configuration(to_number)
        config = resolution_result.config
        hospital_id = resolution_result.hospital_id
        voice_profile = (config.voice_profile if config else None) or None
        voice_gender = (config.voice_gender if config else None) or None
        reception_number = (config.reception_number if config else None) or None
        hospital_default = (
            (config.default_language if config else None) or "en"
        )

        # Phase 2: language resolver (reuse Flow A service)
        resolution = await LanguageResolverService(db).resolve_for_inbound(
            from_number=from_number,
            hospital_default=hospital_default,
        )

        session_extra = {
            "hospital_id": hospital_id,
            "hospital_resolution_source": resolution_result.source.value,
            "to_number": to_number,
            "voice_profile": voice_profile,
            "voice_gender": voice_gender,
            "reception_number": reception_number,
            "patient_id": resolution.patient_id,
            "language_source": resolution.source,
        }

        if is_phase6_enabled():
            session_extra["call_started_at"] = datetime.now(timezone.utc).isoformat()

        if not resolution.needs_dtmf_menu:
            lang = resolution.language
            session_extra.update(
                {
                    "language": lang,
                    "twilio_language": _TWILIO_LANG.get(lang, "en-IN"),
                    "language_locked": True,
                    "step": "greeting",
                }
            )
            state = await session_store.create_session(
                call_sid, from_number, base_url, **session_extra
            )
            logger.info(
                f"  ↳ [{call_sid}] Language resolved source={resolution.source} "
                f"lang={lang} — skipping DTMF"
            )
            return xml(_greeting_twiml(state))

        session_extra.update(
            {
                "language": hospital_default if hospital_default in _TWILIO_LANG else "en",
                "twilio_language": _TWILIO_LANG.get(hospital_default, "en-IN"),
                "language_locked": False,
                "step": "language_select",
            }
        )
        await session_store.create_session(
            call_sid, from_number, base_url, **session_extra
        )
        twiml = lang_node.build_language_select_twiml(base_url)

        logger.info(
            "TRACE incoming_call BEFORE returning TwiML call_sid=%s twiml_len=%s",
            call_sid,
            len(twiml or ""),
        )
        logger.info(f"  ↳ [{call_sid}] Returning language select TwiML")
        return xml(twiml)

    except Exception as e:
        logger.error(f"  ✗ [{call_sid}] /incoming crashed: {e}")
        logger.error(traceback.format_exc())
        logger.info("TRACE incoming_call BEFORE returning error TwiML call_sid=%s", call_sid)
        return xml(_error_twiml())


# ── Route 2: Language selection ────────────────────────────────────────────────
@router.post("/lang")
async def language_select(
    request: Request,
    db: DbSession,
    CallSid: str = Form(default=""),
    Digits: str = Form(default=""),
    SpeechResult: str = Form(default=""),
):
    await _require_agent_webhook(request)
    call_sid = CallSid or "unknown"
    digit = Digits.strip()
    speech = SpeechResult.strip()
    _log_request("LANG", call_sid, Digits=digit, Speech=speech)

    try:
        base_url = _base_url()

        state = await session_store.get_session(call_sid)
        if state is None:
            logger.warning(f"  ↳ [{call_sid}] No session found — creating fresh")
            state = await session_store.create_session(call_sid, "", base_url)

        resolver = LanguageResolverService(db)
        from_number = state.get("from_number") or ""

        # Empty digit + speech → AI fallback via existing resolver
        if not digit and speech:
            resolution = await resolver.resolve_for_inbound(
                from_number=from_number,
                hospital_default=state.get("language") or "en",
                speech_for_fallback=speech,
                allow_ai_fallback=True,
            )
            lang = resolution.language
            await session_store.update_session(
                call_sid,
                {
                    "language": lang,
                    "twilio_language": _TWILIO_LANG.get(lang, "en-IN"),
                    "language_locked": True,
                    "language_source": resolution.source,
                    "patient_id": resolution.patient_id or state.get("patient_id"),
                    "step": "greeting",
                    "retry_count": 0,
                },
            )
            state = await session_store.get_session(call_sid)
            return xml(_greeting_twiml(state))

        result = lang_node.process_language_selection(digit, base_url)
        logger.info(f"  ↳ [{call_sid}] lang result keys: {list(result.keys())}")

        if result.get("retry_count_increment"):
            retry = state["retry_count"] + 1
            await session_store.update_session(call_sid, {"retry_count": retry})
            if retry > 2:
                logger.warning(f"  ↳ [{call_sid}] Too many retries on language select")
                return xml(_error_twiml())
            logger.info(f"  ↳ [{call_sid}] Invalid digit, replaying language menu (retry={retry})")
            return xml(lang_node.build_language_select_twiml(base_url))

        updates = {k: v for k, v in result.items() if not k.startswith("_")}
        updates["language_locked"] = True
        updates["language_source"] = "dtmf"
        await session_store.update_session(call_sid, updates)
        state = await session_store.get_session(call_sid)

        lang = state["language"]
        await resolver.persist_language(
            from_number,
            lang,
            patient_id=state.get("patient_id"),
        )

        twilio_lang = state["twilio_language"]
        logger.info(f"  ↳ [{call_sid}] Language set: {lang} ({twilio_lang})")

        twiml = _greeting_twiml(state)
        logger.info(f"  ↳ [{call_sid}] Returning greeting + service menu TwiML")
        return xml(twiml)

    except Exception as e:
        logger.error(f"  ✗ [{call_sid}] /lang crashed: {e}")
        logger.error(traceback.format_exc())
        return xml(_error_twiml())


# ── Route 3: Service menu ──────────────────────────────────────────────────────
@router.post("/menu")
async def service_menu(
    request: Request,
    db: DbSession,
    CallSid: str = Form(default=""),
    Digits: str = Form(default=""),
):
    await _require_agent_webhook(request)
    call_sid = CallSid or "unknown"
    digit = Digits.strip()
    _log_request("MENU", call_sid, Digits=digit)

    try:
        base_url = _base_url()
        state = await session_store.get_session(call_sid)
        if state is None:
            logger.error(f"  ✗ [{call_sid}] No session found at /menu")
            return xml(_error_twiml("Your session has expired. Please call again."))

        result = greet_node.process_service_menu(digit)
        logger.info(f"  ↳ [{call_sid}] service result: {result}")

        if result.get("retry_count_increment"):
            retry = state["retry_count"] + 1
            await session_store.update_session(call_sid, {"retry_count": retry})
            if retry > 2:
                return xml(_error_twiml())
            return xml(_greeting_twiml(state))

        updates = {k: v for k, v in result.items() if not k.startswith("_")}
        await session_store.update_session(call_sid, updates)
        state = await session_store.get_session(call_sid)

        service = state["service"]
        logger.info(f"  ↳ [{call_sid}] Service selected: {service}")

        if service == "book":
            twiml = await _enter_booking_flow(db, call_sid, state, resume=False)
            logger.info(f"  ↳ [{call_sid}] Returning collect_name TwiML")
            return xml(twiml)

        # Phase 3: FAQ via existing FaqRetrievalService (ask question first)
        if service == "faq":
            twiml = greet_node.build_ask_faq_twiml(state)
            logger.info(f"  ↳ [{call_sid}] Returning FAQ question TwiML")
            return xml(twiml)

        # Reschedule / cancel remain stubs (Phase 5 deferred) — Flow A owns these
        lang = state["twilio_language"]
        vp = state.get("voice_profile")
        logger.info(f"  ↳ [{call_sid}] Service '{service}' not yet implemented")
        from xml.sax.saxutils import escape

        voice_attr = f' voice="{escape(vp)}"' if vp else ""
        return xml(
            f'<?xml version="1.0" encoding="UTF-8"?><Response>'
            f'<Say language="{escape(lang)}"{voice_attr}>This service will be available soon. '
            f'Please visit the hospital or call during working hours.</Say><Hangup/></Response>'
        )

    except Exception as e:
        logger.error(f"  ✗ [{call_sid}] /menu crashed: {e}")
        logger.error(traceback.format_exc())
        return xml(_error_twiml())


# ── Route 4: Conversational turns ─────────────────────────────────────────────
@router.post("/turn")
async def conversation_turn(
    request: Request,
    db: DbSession,
    CallSid: str = Form(default=""),
    SpeechResult: str = Form(default=""),
    Digits: str = Form(default=""),
    Confidence: str = Form(default=""),
):
    await _require_agent_webhook(request)
    call_sid = CallSid or "unknown"
    speech = SpeechResult.strip()
    digits = Digits.strip()
    _log_request("TURN", call_sid, Speech=speech, Digits=digits, Confidence=Confidence)

    try:
        confidence_float = float(Confidence) if Confidence.strip() else -1.0
    except ValueError:
        confidence_float = -1.0

    state = None
    try:
        state = await session_store.get_session(call_sid)
        if state is None:
            logger.error(f"  ✗ [{call_sid}] No session found at /turn")
            return xml(_error_twiml("Your session has expired. Please call again."))

        step = state["step"]
        logger.info(f"  ↳ [{call_sid}] Current step: {step}")

        phase6 = is_phase6_enabled()
        transcript = speech or digits

        if phase6:
            init_call_timestamps(state)
            state["current_language"] = state.get("language")
            if check_conversation_limits(state):
                return xml(await _limit_twiml_and_cleanup(call_sid, state))

            skip_pre_route = step in {
                "faq_continue",
                "post_booking_continue",
                "faq_question",
            }
            if transcript and not skip_pre_route:
                routed = await _handle_pre_intent_route(db, call_sid, state, transcript, step)
                if routed:
                    return xml(routed)

        # ── FAQ continue (Phase 6.1) ──────────────────────────────────────
        if step == "faq_continue":
            yn = detect_yes_no(transcript, state.get("language") or "en")
            routed_intent = route_intent(transcript, state) if transcript else ConversationIntent.UNKNOWN

            if routed_intent == ConversationIntent.BOOKING:
                return xml(await _enter_booking_flow(db, call_sid, state, resume=bool(state.get("return_step"))))
            if routed_intent == ConversationIntent.TRANSFER:
                bump_counter(state, "transfer_count")
                await session_store.update_session(call_sid, {"step": "transfer"})
                twiml = await _do_reception_transfer(db, state, reason="caller_requested_reception")
                await session_store.delete_session(call_sid)
                return xml(twiml)
            if routed_intent == ConversationIntent.GOODBYE:
                return xml(await _goodbye_twiml_and_cleanup(call_sid, state))

            if yn == "yes":
                await session_store.update_session(call_sid, {"step": "faq_question", "retry_count": 0})
                state = await session_store.get_session(call_sid)
                return xml(greet_node.build_ask_faq_twiml(state))

            if yn == "no":
                if state.get("return_step") in booking_steps():
                    return xml(await _enter_booking_flow(db, call_sid, state, resume=True))
                return xml(await _goodbye_twiml_and_cleanup(call_sid, state))

            if routed_intent == ConversationIntent.FAQ and transcript:
                await session_store.update_session(call_sid, {"step": "faq_question"})
                state = await session_store.get_session(call_sid)
                return xml(
                    await _process_faq_transcript(
                        db,
                        call_sid,
                        state,
                        transcript,
                        phase6=True,
                        confidence=confidence_float,
                    )
                )

            state = await session_store.get_session(call_sid)
            return xml(greet_node.build_faq_continue_twiml(state))

        # ── Post-booking continue (Phase 6.4) ─────────────────────────────
        if step == "post_booking_continue":
            routed_intent = route_intent(transcript, state) if transcript else ConversationIntent.UNKNOWN
            yn = detect_yes_no(transcript, state.get("language") or "en")

            if routed_intent == ConversationIntent.GOODBYE or yn == "no":
                return xml(await _goodbye_twiml_and_cleanup(call_sid, state))
            if routed_intent == ConversationIntent.TRANSFER:
                bump_counter(state, "transfer_count")
                await session_store.update_session(call_sid, {"step": "transfer"})
                twiml = await _do_reception_transfer(db, state, reason="caller_requested_reception")
                await session_store.delete_session(call_sid)
                return xml(twiml)
            if routed_intent == ConversationIntent.BOOKING:
                return xml(await _enter_booking_flow(db, call_sid, state, resume=False))
            if routed_intent == ConversationIntent.FAQ or yn == "yes" or transcript:
                await session_store.update_session(call_sid, {"step": "faq_question", "service": "faq"})
                state = await session_store.get_session(call_sid)
                if transcript and routed_intent != ConversationIntent.BOOKING:
                    return xml(
                        await _process_faq_transcript(
                            db,
                            call_sid,
                            state,
                            transcript,
                            phase6=True,
                            confidence=confidence_float,
                        )
                    )
                return xml(greet_node.build_ask_faq_twiml(state))

            state = await session_store.get_session(call_sid)
            return xml(greet_node.build_faq_continue_twiml(state))

        # ── FAQ question (Phase 3 + transfer Phase 4) ───────────────────────
        if step == "faq_question":
            return xml(
                await _process_faq_transcript(
                    db,
                    call_sid,
                    state,
                    transcript,
                    phase6=phase6,
                    confidence=confidence_float,
                )
            )

        # ── collect_name ──────────────────────────────────────────────────
        if step == "collect_name":
            if phase6 and transcript:
                routed = await _handle_pre_intent_route(db, call_sid, state, transcript, step)
                if routed:
                    return xml(routed)
            logger.info(f"  ↳ [{call_sid}] Processing name: {speech!r}")
            result = book_node.process_collect_name(state, speech, confidence=confidence_float)
            await _apply(call_sid, result)
            logger.info(f"  ↳ [{call_sid}] Name result step: {result.get('step')}")
            return xml(result["_twiml"])

        # ── collect_problem ───────────────────────────────────────────────
        if step == "collect_problem":
            if phase6 and transcript:
                routed = await _handle_pre_intent_route(db, call_sid, state, transcript, step)
                if routed:
                    return xml(routed)
            logger.info(f"  ↳ [{call_sid}] Processing problem: {speech!r}")
            result = book_node.process_collect_problem(state, speech, confidence=confidence_float)
            await _apply(call_sid, result)

            if result.get("_pending") == "suggest_doctors":
                state = await session_store.get_session(call_sid)
                hospital_id = await _ensure_session_hospital(
                    db, call_sid, state, step="collect_problem", service="book"
                )
                if not hospital_id:
                    return xml(
                        await _transfer_no_hospital(
                            db, call_sid, state, reason="booking_no_hospital", service="book"
                        )
                    )
                specialty = state["detected_specialty"]
                logger.info(f"  ↳ [{call_sid}] Fetching doctors for: {specialty}")
                doctors = await book_node.fetch_doctors_for_specialty(
                    specialty, db, hospital_id=hospital_id
                )
                logger.info(f"  ↳ [{call_sid}] Found {len(doctors)} doctors")
                await session_store.update_session(call_sid, {"suggested_doctors": doctors})
                state = await session_store.get_session(call_sid)
                confirm_tts = result.get("_confirm_problem_tts", "")
                return xml(book_node.build_suggest_doctors_twiml(state, doctors, confirm_tts))

            return xml(result["_twiml"])

        # ── suggest_doctors ───────────────────────────────────────────────
        if step == "suggest_doctors":
            if phase6 and transcript and not digits:
                routed = await _handle_pre_intent_route(db, call_sid, state, transcript, step)
                if routed:
                    return xml(routed)
            logger.info(f"  ↳ [{call_sid}] Doctor selection digit: {digits!r}")
            result = book_node.process_select_doctor(state, digits)
            await _apply(call_sid, result)

            if result.get("_pending") == "select_slot":
                state = await session_store.get_session(call_sid)
                hospital_id = state.get("hospital_id")
                doctor_id = state["selected_doctor_id"]
                logger.info(f"  ↳ [{call_sid}] Fetching slots for doctor_id={doctor_id}")
                slots = await book_node.fetch_available_slots(
                    doctor_id, db, hospital_id=hospital_id
                )
                logger.info(f"  ↳ [{call_sid}] Found {len(slots)} slots")
                await session_store.update_session(call_sid, {"available_slots": slots})
                state = await session_store.get_session(call_sid)
                return xml(book_node.build_select_slot_twiml(state, slots))

            return xml(result.get("_twiml", _error_twiml()))

        # ── select_slot ───────────────────────────────────────────────────
        if step == "select_slot":
            if phase6 and transcript and not digits:
                routed = await _handle_pre_intent_route(db, call_sid, state, transcript, step)
                if routed:
                    return xml(routed)
            logger.info(f"  ↳ [{call_sid}] Slot selection digit: {digits!r}")
            result = book_node.process_select_slot(state, digits)
            await _apply(call_sid, result)

            if result.get("_pending") == "confirm":
                state = await session_store.get_session(call_sid)
                if state.get("appointment_id"):
                    logger.info(
                        "BOOKING_ALREADY_PROCESSED call_sid=%s appointment_id=%s step=%s",
                        call_sid,
                        state.get("appointment_id"),
                        step,
                    )
                    confirm_result = {
                        "step": "booked",
                        "appointment_id": state["appointment_id"],
                        "appointment_number": state.get("appointment_number"),
                        "_twiml": book_node._hangup_twiml(
                            book_node._s(
                                "confirm_booking",
                                state.get("language") or "en",
                                doctor=state.get("selected_doctor_name", "the doctor"),
                                date=(state.get("selected_slot") or {}).get("date", ""),
                                time=book_node._format_time_for_tts(
                                    (state.get("selected_slot") or {}).get("time", "")
                                ),
                                appt_no=state.get("appointment_number", ""),
                            ),
                            state["twilio_language"],
                            base_url=state.get("base_url", ""),
                        ),
                    }
                else:
                    logger.info(f"  ↳ [{call_sid}] Confirming and booking appointment...")
                    confirm_result = await book_node.confirm_and_book(state, db)
                await _apply(call_sid, confirm_result)
                if confirm_result["step"] == "booked":
                    logger.info(
                        f"  ↳ [{call_sid}] ✓ Appointment booked: "
                        f"{confirm_result.get('appointment_number')}"
                    )
                    if phase6:
                        state = await session_store.get_session(call_sid)
                        bump_counter(state, "booking_count")
                        record_analytics_event(
                            state,
                            "booking_complete",
                            appointment_number=confirm_result.get("appointment_number"),
                        )
                        slot = state.get("selected_slot") or {}
                        lang = state.get("language") or "en"
                        doctor_name = state.get("selected_doctor_name", "the doctor")
                        time_display = book_node._format_time_for_tts(slot.get("time", ""))
                        booking_text = book_node._s(
                            "confirm_booking",
                            lang,
                            doctor=doctor_name,
                            date=slot.get("date", ""),
                            time=time_display,
                            appt_no=confirm_result.get("appointment_number", ""),
                        )
                        await session_store.update_session(
                            call_sid,
                            {
                                "step": "post_booking_continue",
                                "booking_count": state.get("booking_count", 0),
                                "conversation_analytics": state.get("conversation_analytics"),
                            },
                        )
                        state = await session_store.get_session(call_sid)
                        return xml(
                            greet_node.build_post_booking_continue_twiml(state, booking_text)
                        )
                    await session_store.delete_session(call_sid)
                return xml(confirm_result["_twiml"])

            return xml(result.get("_twiml", _error_twiml()))

        logger.warning(f"  ↳ [{call_sid}] Unhandled step: {step!r}")
        return xml(_error_twiml())

    except Exception as e:
        step_name = state.get("step") if state else "unknown"
        logger.error(f"  ✗ [{call_sid}] /turn crashed at step={step_name}: {e}")
        logger.error(traceback.format_exc())
        return xml(_error_twiml())


# ── Route 5: Call status ───────────────────────────────────────────────────────
@router.post("/status")
async def call_status(
    request: Request,
    CallSid: str = Form(default=""),
    CallStatus: str = Form(default=""),
):
    await _require_agent_webhook(request)
    call_sid = CallSid or "unknown"
    logger.info(f"▶ STATUS | SID={call_sid} | Status={CallStatus}")
    if CallStatus in {"completed", "failed", "busy", "no-answer", "canceled"}:
        await session_store.delete_session(call_sid)
        logger.info(f"  ↳ [{call_sid}] Session cleaned up")
    return PlainTextResponse("ok")


# ── Route 5b: Reception dial result (Phase 4) ──────────────────────────────────
@router.post("/transfer-result")
async def transfer_result(
    request: Request,
    db: DbSession,
    CallSid: str = Form(default=""),
    DialCallStatus: str = Form(default=""),
    CallStatus: str = Form(default=""),
    From: str = Form(default=""),
    Caller: str = Form(default=""),
):
    """Thin wrapper — delegates only to ReceptionTransferService.handle_dial_status."""
    await _require_agent_webhook(request)
    call_sid = CallSid or "unknown"
    dial_status = DialCallStatus or CallStatus or ""
    from_number = From or Caller or ""
    _log_request("TRANSFER-RESULT", call_sid, DialStatus=dial_status, From=from_number)

    try:
        state = await session_store.get_session(call_sid)
        language = (state or {}).get("language") or "en"
        hospital_id = (state or {}).get("hospital_id")
        patient_id = (state or {}).get("patient_id")
        if not from_number and state:
            from_number = state.get("from_number") or ""

        config = None
        if hospital_id:
            config = await HospitalVoiceConfigService(db).get_entity(hospital_id)
        provider = ProviderFactory.from_hospital_config(config)

        result = await ReceptionTransferService(db).handle_dial_status(
            dial_status=dial_status,
            from_number=from_number,
            language=language,
            hospital_id=hospital_id,
            patient_id=patient_id,
            call_id=None,
            provider=provider,
        )
        await session_store.delete_session(call_sid)
        return xml(result.xml)
    except Exception as e:
        logger.error(f"  ✗ [{call_sid}] /transfer-result crashed: {e}")
        logger.error(traceback.format_exc())
        return xml(_error_twiml())


# ── Route 6: Health check ──────────────────────────────────────────────────────
@router.get("/health")
async def agent_health():
    from app.services.sarvam_tts import voice_clone_ready

    base_url = _base_url()
    logger.info(f"▶ HEALTH | base_url={base_url} | active_calls={session_store.active_session_count()}")
    return {
        "status": "ok",
        "agent": "NexaCare AI Voice Agent",
        "active_calls": session_store.active_session_count(),
        "base_url": base_url,
        "voice_clone_enabled": voice_clone_ready(),
        "phase6_enabled": is_phase6_enabled(),
        "twilio_incoming_webhook": f"{base_url}/agent/v1/voice/incoming",
        "twilio_status_webhook": f"{base_url}/agent/v1/voice/status",
    }


# ── Route 6b: Public audio for Twilio <Play> (Sarvam clone cache) ─────────────
@router.get("/audio/{filename}")
async def voice_audio(filename: str):
    """
    Served to Twilio when TwiML contains <Play>.
    No webhook signature — Twilio Media fetches this as a plain GET.
    """
    from app.services.sarvam_tts import read_cached_audio

    try:
        data, content_type = read_cached_audio(filename)
    except ValueError:
        return PlainTextResponse("invalid filename", status_code=400)
    except FileNotFoundError:
        return PlainTextResponse("not found", status_code=404)

    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )


# ── Route 7: Reminder call TwiML ───────────────────────────────────────────────
@router.get("/reminder-twiml")
async def reminder_twiml(
    doctor: str = "",
    time: str = "",
    lang: str = "en",
    appt_no: str = "",
    phone: str = "",
):
    from app.agent.reminder import build_reminder_twiml
    logger.info(f"▶ REMINDER-TWIML | phone={phone} | appt={appt_no} | lang={lang}")
    twiml = build_reminder_twiml(
        lang=lang,
        doctor=doctor,
        time_str=time,
        appt_no=appt_no,
    )
    return xml(twiml)


# ── Route 8: Reminder call status callback ─────────────────────────────────────
@router.post("/reminder-status")
async def reminder_status(
    request: Request,
    CallStatus: str = Form(default=""),
    doctor: str = "",
    time: str = "",
    lang: str = "en",
    appt_no: str = "",
    phone: str = "",
):
    await _require_agent_webhook(request)
    from app.agent.reminder import send_reminder_sms
    logger.info(
        f"▶ REMINDER-STATUS | status={CallStatus} | "
        f"phone={phone} | appt={appt_no}"
    )

    no_answer_statuses = {"no-answer", "busy", "failed"}
    if CallStatus.lower() in no_answer_statuses:
        logger.warning(
            f"  ↳ Call {CallStatus} for {appt_no} — sending SMS to {phone}"
        )
        await send_reminder_sms(
            phone=phone,
            lang=lang,
            doctor=doctor,
            time_str=time,
            appt_no=appt_no,
        )
    else:
        logger.info(f"  ↳ Reminder call {CallStatus} for {appt_no}")

    return PlainTextResponse("ok")


# ── Internal helper ────────────────────────────────────────────────────────────
async def _apply(call_sid: str, result: dict) -> None:
    """Merge non-private keys from node result into session."""
    updates = {k: v for k, v in result.items() if not k.startswith("_")}
    if updates:
        await session_store.update_session(call_sid, updates)
