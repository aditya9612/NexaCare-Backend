"""
app/agent/nodes/greeting.py
---------------------------
Node 2: Greeting — introduces NexaCare AI.
Node 3: Service menu — Press 1 Book, 2 Reschedule, 3 Cancel, 4 Hospital info.

No LLM calls here. Pure deterministic TwiML responses.
Uses Sarvam cloned voice via <Play> when VOICE_CLONE_ENABLED is on.
"""

import logging
from xml.sax.saxutils import escape

from app.services.sarvam_tts import speak

logger = logging.getLogger("nexacare.agent.nodes.greeting")

# ── Localised strings ─────────────────────────────────────────────────────────
GREETINGS = {
    "en": "Hello! This is NexaCare AI Appointment Assistant. I am here to help you.",
    "hi": "नमस्ते! यह NexaCare AI अपॉइंटमेंट असिस्टेंट है। मैं आपकी सहायता के लिए यहाँ हूँ।",
    "mr": "नमस्कार! हे NexaCare AI अपॉइंटमेंट असिस्टंट आहे. मी तुमच्या मदतीसाठी इथे आहे.",
}

SERVICE_MENUS = {
    "en": (
        "For appointment booking, press 1. "
        "To reschedule an existing appointment, press 2. "
        "To cancel an appointment, press 3. "
        "For hospital information, press 4."
    ),
    "hi": (
        "अपॉइंटमेंट बुकिंग के लिए 1 दबाएं। "
        "मौजूदा अपॉइंटमेंट बदलने के लिए 2 दबाएं। "
        "अपॉइंटमेंट रद्द करने के लिए 3 दबाएं। "
        "अस्पताल की जानकारी के लिए 4 दबाएं।"
    ),
    "mr": (
        "अपॉइंटमेंट बुकिंगसाठी 1 दाबा. "
        "विद्यमान अपॉइंटमेंट बदलण्यासाठी 2 दाबा. "
        "अपॉइंटमेंट रद्द करण्यासाठी 3 दाबा. "
        "रुग्णालयाची माहितीसाठी 4 दाबा."
    ),
}

NO_INPUT = {
    "en": "We did not receive your input. Please call again. Goodbye.",
    "hi": "हमें आपका इनपुट नहीं मिला। कृपया पुनः कॉल करें।",
    "mr": "आम्हाला तुमचे उत्तर मिळाले नाही. कृपया पुन्हा कॉल करा.",
}


def build_greeting_twiml(
    base_url: str,
    language: str,
    twilio_language: str,
    voice_profile: str | None = None,
) -> str:
    """
    Plays the greeting then immediately flows into the service menu.
    Combined into a single TwiML to avoid an extra round-trip.
    """
    action = escape(f"{base_url}/agent/v1/voice/menu")
    greeting = GREETINGS.get(language, GREETINGS["en"])
    menu = SERVICE_MENUS.get(language, SERVICE_MENUS["en"])
    no_input = NO_INPUT.get(language, NO_INPUT["en"])

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"{speak(greeting, twilio_language, base_url)}"
        f'<Gather numDigits="1" action="{action}" method="POST" timeout="10">'
        f"{speak(menu, twilio_language, base_url)}"
        "</Gather>"
        f"{speak(no_input, twilio_language, base_url)}"
        "<Hangup/>"
        "</Response>"
    )


def process_service_menu(digit: str) -> dict:
    """
    Map DTMF digit to service type.
    Returns state updates. TwiML is built by the booking/FAQ path.
    """
    service_map = {
        "1": "book",
        "2": "reschedule",
        "3": "cancel",
        "4": "faq",
    }
    service = service_map.get(digit)

    if not service:
        logger.warning(f"Invalid service digit: {digit!r}")
        return {"step": "service_menu", "retry_count_increment": True}

    logger.info(f"Service selected: {service} (digit={digit})")
    if service == "faq":
        return {
            "step": "faq_question",
            "service": "faq",
            "retry_count": 0,
        }
    return {
        "step": "collect_name",
        "service": service,
        "retry_count": 0,
    }



def build_ask_faq_twiml(state: BookingCallState) -> str:
    """Ask hospital FAQ question using Flow A prompt helper (no duplicated strings)."""
    from app.ai.voice_appointment_assistant.prompts import ask_faq_question
    from app.agent.nodes import booking as book_node

    lang = state["language"]
    twilio_lang = state["twilio_language"]
    action = f"{state['base_url']}/agent/v1/voice/turn"
    prompt = ask_faq_question(lang)
    voice_profile = state.get("voice_profile")
    return book_node._twiml(
        book_node._gather_speech(
            action,
            prompt,
            twilio_lang,
            lang_code=lang,
            timeout=book_node._speech_timeout_for(lang),
            voice_profile=voice_profile,
        )
    )


def build_faq_continue_twiml(state: BookingCallState, prefix: str = "") -> str:
    """Ask whether caller wants another FAQ question (Phase 6.1)."""
    from xml.sax.saxutils import escape

    from app.agent.conversation import faq_continue_prompt
    from app.utils.twiml_builder import gather_speech_or_dtmf, twiml_response

    lang = state["language"]
    twilio_lang = state["twilio_language"]
    voice_profile = state.get("voice_profile")
    action = f"{state['base_url']}/agent/v1/voice/turn"
    prompt = (f"{prefix} {faq_continue_prompt(lang)}").strip()
    hints = "yes no हो होय नाही हाँ नहीं sure continue thanks"
    gather = gather_speech_or_dtmf(
        action,
        prompt,
        language=twilio_lang,
        hints=hints,
        voice=voice_profile,
    )
    redirect = f'<Redirect method="POST">{escape(action)}</Redirect>'
    return twiml_response(gather + redirect)


def build_post_booking_continue_twiml(state: BookingCallState, booking_message: str) -> str:
    """After booking success, offer FAQ continuation without hanging up (Phase 6.4)."""
    from app.agent.conversation import post_booking_prompt
    from app.utils.twiml_builder import gather_speech_or_dtmf, twiml_response
    from xml.sax.saxutils import escape

    lang = state["language"]
    twilio_lang = state["twilio_language"]
    voice_profile = state.get("voice_profile")
    action = f"{state['base_url']}/agent/v1/voice/turn"
    prompt = f"{booking_message} {post_booking_prompt(lang)}"
    hints = "yes no parking hours hospital हो होय नाही"
    gather = gather_speech_or_dtmf(
        action,
        prompt,
        language=twilio_lang,
        hints=hints,
        voice=voice_profile,
    )
    redirect = f'<Redirect method="POST">{escape(action)}</Redirect>'
    return twiml_response(gather + redirect)


def build_goodbye_twiml(state: BookingCallState) -> str:
    """Localized goodbye then hangup (Phase 6.9)."""
    from app.agent.conversation import goodbye_message
    from app.agent.nodes import booking as book_node

    lang = state.get("language") or "en"
    return book_node._hangup_twiml(
        goodbye_message(lang),
        state["twilio_language"],
        voice_profile=state.get("voice_profile"),
    )
