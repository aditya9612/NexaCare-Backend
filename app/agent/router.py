"""
app/agent/router.py
-------------------
FastAPI router for NexaCare AI Voice Agent webhooks.
Mounted at: /agent/v1/voice

Full logging on every route + try/except on every handler
so errors never silently return "Application Error" to Twilio.
"""

import logging
import traceback

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import PlainTextResponse

from app.agent import session_store
from app.agent.nodes import language as lang_node
from app.agent.nodes import greeting as greet_node
from app.agent.nodes import booking as book_node
from app.core.constants import TelephonyProviderType
from app.core.dependencies import DbSession
from app.telephony.webhook_auth import require_voice_webhook_auth

logger = logging.getLogger("nexacare.agent.router")

router = APIRouter(tags=["AI Voice Agent"])


# ── Helpers ────────────────────────────────────────────────────────────────────

def xml(twiml: str) -> Response:
    return Response(content=twiml, media_type="application/xml; charset=utf-8")


async def _require_agent_webhook(request: Request) -> None:
    """Agent webhooks are Twilio-oriented by default (experimental path)."""
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
        # Try common attribute name variants
        for attr in ["PUBLIC_BASE_URL", "public_base_url", "BASE_URL", "base_url"]:
            val = getattr(settings, attr, None)
            if val:
                logger.debug(f"base_url from settings.{attr} = {val}")
                return val.rstrip("/")
    except Exception as e:
        logger.warning(f"Could not read settings: {e}")

    # Final fallback — read directly from env
    import os
    val = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
    logger.debug(f"base_url from os.getenv = {val}")
    return val.rstrip("/")


def _error_twiml(msg: str = None) -> str:
    text = msg or "We are sorry, something went wrong. Please call again. Goodbye."
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Response><Say language="en-IN">{text}</Say><Hangup/></Response>'
    )


def _log_request(route: str, call_sid: str, **kwargs):
    """Structured log for every incoming webhook."""
    extras = " | ".join(f"{k}={v!r}" for k, v in kwargs.items() if v)
    logger.info(f"▶ {route} | SID={call_sid}" + (f" | {extras}" if extras else ""))


def _log_state(call_sid: str, step: str, action: str = ""):
    logger.info(f"  ↳ [{call_sid}] step={step}" + (f" → {action}" if action else ""))


# ── Route 1: Incoming call ─────────────────────────────────────────────────────
@router.post("/incoming")
async def incoming_call(
    request: Request,
    CallSid: str = Form(default=""),
    From: str = Form(default=""),
    Caller: str = Form(default=""),
):
    logger.info(
        "TRACE incoming_call ROUTE ENTRY path=%s url=%s CallSid=%r From=%r Caller=%r",
        request.url.path,
        str(request.url),
        CallSid,
        From,
        Caller,
    )
    await _require_agent_webhook(request)
    logger.info("TRACE incoming_call AFTER auth CallSid=%r", CallSid)
    call_sid = CallSid or "unknown"
    from_number = From or Caller or ""
    _log_request("INCOMING", call_sid, From=from_number)

    try:
        base_url = _base_url()
        logger.info(f"  ↳ base_url={base_url}")

        session_store.create_session(call_sid, from_number, base_url)
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
    CallSid: str = Form(default=""),
    Digits: str = Form(default=""),
):
    await _require_agent_webhook(request)
    call_sid = CallSid or "unknown"
    digit = Digits.strip()
    _log_request("LANG", call_sid, Digits=digit)

    try:
        base_url = _base_url()

        state = session_store.get_session(call_sid)
        if state is None:
            logger.warning(f"  ↳ [{call_sid}] No session found — creating fresh")
            state = session_store.create_session(call_sid, "", base_url)

        result = lang_node.process_language_selection(digit, base_url)
        logger.info(f"  ↳ [{call_sid}] lang result keys: {list(result.keys())}")

        # Invalid digit — retry
        if result.get("retry_count_increment"):
            retry = state["retry_count"] + 1
            session_store.update_session(call_sid, {"retry_count": retry})
            if retry > 2:
                logger.warning(f"  ↳ [{call_sid}] Too many retries on language select")
                return xml(_error_twiml())
            logger.info(f"  ↳ [{call_sid}] Invalid digit, replaying language menu (retry={retry})")
            return xml(lang_node.build_language_select_twiml(base_url))

        # Valid — save language, build greeting
        updates = {k: v for k, v in result.items() if not k.startswith("_")}
        session_store.update_session(call_sid, updates)
        state = session_store.get_session(call_sid)

        lang = state["language"]
        twilio_lang = state["twilio_language"]
        logger.info(f"  ↳ [{call_sid}] Language set: {lang} ({twilio_lang})")

        twiml = greet_node.build_greeting_twiml(base_url, lang, twilio_lang)
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
    CallSid: str = Form(default=""),
    Digits: str = Form(default=""),
):
    await _require_agent_webhook(request)
    call_sid = CallSid or "unknown"
    digit = Digits.strip()
    _log_request("MENU", call_sid, Digits=digit)

    try:
        base_url = _base_url()
        state = session_store.get_session(call_sid)
        if state is None:
            logger.error(f"  ✗ [{call_sid}] No session found at /menu")
            return xml(_error_twiml("Your session has expired. Please call again."))

        result = greet_node.process_service_menu(digit)
        logger.info(f"  ↳ [{call_sid}] service result: {result}")

        # Invalid digit — replay menu
        if result.get("retry_count_increment"):
            retry = state["retry_count"] + 1
            session_store.update_session(call_sid, {"retry_count": retry})
            if retry > 2:
                return xml(_error_twiml())
            return xml(
                greet_node.build_greeting_twiml(base_url, state["language"], state["twilio_language"])
            )

        updates = {k: v for k, v in result.items() if not k.startswith("_")}
        session_store.update_session(call_sid, updates)
        state = session_store.get_session(call_sid)

        service = state["service"]
        logger.info(f"  ↳ [{call_sid}] Service selected: {service}")

        if service == "book":
            twiml = book_node.build_collect_name_twiml(state)
            logger.info(f"  ↳ [{call_sid}] Returning collect_name TwiML")
            return xml(twiml)

        # Phase 2 services
        lang = state["twilio_language"]
        logger.info(f"  ↳ [{call_sid}] Service '{service}' not yet implemented")
        return xml(
            f'<?xml version="1.0" encoding="UTF-8"?><Response>'
            f'<Say language="{lang}">This service will be available soon. '
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

    # Parse confidence — Twilio sends it as a string, sometimes empty
    try:
        confidence_float = float(Confidence) if Confidence.strip() else -1.0
    except ValueError:
        confidence_float = -1.0

    try:
        state = session_store.get_session(call_sid)
        if state is None:
            logger.error(f"  ✗ [{call_sid}] No session found at /turn")
            return xml(_error_twiml("Your session has expired. Please call again."))

        step = state["step"]
        logger.info(f"  ↳ [{call_sid}] Current step: {step}")

        # ── collect_name ──────────────────────────────────────────────────
        if step == "collect_name":
            logger.info(f"  ↳ [{call_sid}] Processing name: {speech!r}")
            result = book_node.process_collect_name(state, speech, confidence=confidence_float)
            _apply(call_sid, result)
            logger.info(f"  ↳ [{call_sid}] Name result step: {result.get('step')}")
            return xml(result["_twiml"])

        # ── collect_problem ───────────────────────────────────────────────
        if step == "collect_problem":
            logger.info(f"  ↳ [{call_sid}] Processing problem: {speech!r}")
            result = book_node.process_collect_problem(state, speech, confidence=confidence_float)
            _apply(call_sid, result)

            if result.get("_pending") == "suggest_doctors":
                state = session_store.get_session(call_sid)
                specialty = state["detected_specialty"]
                logger.info(f"  ↳ [{call_sid}] Fetching doctors for: {specialty}")
                doctors = await book_node.fetch_doctors_for_specialty(specialty, db)
                logger.info(f"  ↳ [{call_sid}] Found {len(doctors)} doctors")
                session_store.update_session(call_sid, {"suggested_doctors": doctors})
                state = session_store.get_session(call_sid)
                # Pass problem confirmation TTS so it plays before the doctor list
                confirm_tts = result.get("_confirm_problem_tts", "")
                return xml(book_node.build_suggest_doctors_twiml(state, doctors, confirm_tts))

            return xml(result["_twiml"])

        # ── suggest_doctors ───────────────────────────────────────────────
        if step == "suggest_doctors":
            logger.info(f"  ↳ [{call_sid}] Doctor selection digit: {digits!r}")
            result = book_node.process_select_doctor(state, digits)
            _apply(call_sid, result)

            if result.get("_pending") == "select_slot":
                state = session_store.get_session(call_sid)
                doctor_id = state["selected_doctor_id"]
                logger.info(f"  ↳ [{call_sid}] Fetching slots for doctor_id={doctor_id}")
                slots = await book_node.fetch_available_slots(doctor_id, db)
                logger.info(f"  ↳ [{call_sid}] Found {len(slots)} slots")
                session_store.update_session(call_sid, {"available_slots": slots})
                state = session_store.get_session(call_sid)
                return xml(book_node.build_select_slot_twiml(state, slots))

            return xml(result.get("_twiml", _error_twiml()))

        # ── select_slot ───────────────────────────────────────────────────
        if step == "select_slot":
            logger.info(f"  ↳ [{call_sid}] Slot selection digit: {digits!r}")
            result = book_node.process_select_slot(state, digits)
            _apply(call_sid, result)

            if result.get("_pending") == "confirm":
                state = session_store.get_session(call_sid)
                logger.info(f"  ↳ [{call_sid}] Confirming and booking appointment...")
                confirm_result = await book_node.confirm_and_book(state, db)
                _apply(call_sid, confirm_result)
                if confirm_result["step"] == "booked":
                    logger.info(f"  ↳ [{call_sid}] ✓ Appointment booked: {confirm_result.get('appointment_number')}")
                    session_store.delete_session(call_sid)
                return xml(confirm_result["_twiml"])

            return xml(result.get("_twiml", _error_twiml()))

        logger.warning(f"  ↳ [{call_sid}] Unhandled step: {step!r}")
        return xml(_error_twiml())

    except Exception as e:
        logger.error(f"  ✗ [{call_sid}] /turn crashed at step={state.get('step') if state else 'unknown'}: {e}")
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
        session_store.delete_session(call_sid)
        logger.info(f"  ↳ [{call_sid}] Session cleaned up")
    return PlainTextResponse("ok")


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
    doctor:  str = "",
    time:    str = "",
    lang:    str = "en",
    appt_no: str = "",
    phone:   str = "",
):
    """
    Served when Twilio connects a reminder call to the patient.
    Plays the appointment reminder in the patient's language then hangs up.
    """
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
    doctor:     str = "",
    time:       str = "",
    lang:       str = "en",
    appt_no:    str = "",
    phone:      str = "",
):
    """
    Twilio posts here when a reminder call ends.
    If patient did not answer, send SMS instead.
    """
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
def _apply(call_sid: str, result: dict) -> None:
    """Merge non-private keys from node result into session."""
    updates = {k: v for k, v in result.items() if not k.startswith("_")}
    if updates:
        session_store.update_session(call_sid, updates)