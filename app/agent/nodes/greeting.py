"""
app/agent/nodes/greeting.py
---------------------------
Node 2: Greeting — introduces NexaCare AI.
Node 3: Service menu — Press 1 Book, 2 Reschedule, 3 Cancel.

No LLM calls here. Pure deterministic TwiML responses.
"""

import logging
from xml.sax.saxutils import escape

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
        "To cancel an appointment, press 3."
    ),
    "hi": (
        "अपॉइंटमेंट बुकिंग के लिए 1 दबाएं। "
        "मौजूदा अपॉइंटमेंट बदलने के लिए 2 दबाएं। "
        "अपॉइंटमेंट रद्द करने के लिए 3 दबाएं।"
    ),
    "mr": (
        "अपॉइंटमेंट बुकिंगसाठी 1 दाबा. "
        "विद्यमान अपॉइंटमेंट बदलण्यासाठी 2 दाबा. "
        "अपॉइंटमेंट रद्द करण्यासाठी 3 दाबा."
    ),
}

NO_INPUT = {
    "en": "We did not receive your input. Please call again. Goodbye.",
    "hi": "हमें आपका इनपुट नहीं मिला। कृपया पुनः कॉल करें।",
    "mr": "आम्हाला तुमचे उत्तर मिळाले नाही. कृपया पुन्हा कॉल करा.",
}

# Marathi's only available Twilio TTS voices are Generative-tier (Google
# Chirp3 voices) — there's no Standard/Neural fallback for mr-IN. Twilio
# does not appear to auto-select a Generative voice the way it does for
# older voice tiers, so language="mr-IN" alone silently fails to render.
# Pin the voice explicitly to remove that ambiguity.
VOICE_BY_LANG = {
    "mr-IN": "Google.mr-IN-Chirp3-HD-Aoede",
}


def _voice_attr(twilio_lang: str) -> str:
    voice = VOICE_BY_LANG.get(twilio_lang)
    return f' voice="{escape(voice)}"' if voice else ""


def build_greeting_twiml(base_url: str, language: str, twilio_language: str) -> str:
    """
    Plays the greeting then immediately flows into the service menu.
    Combined into a single TwiML to avoid an extra round-trip.
    """
    action = escape(f"{base_url}/agent/v1/voice/menu")
    greeting = escape(GREETINGS.get(language, GREETINGS["en"]))
    menu = escape(SERVICE_MENUS.get(language, SERVICE_MENUS["en"]))
    no_input = escape(NO_INPUT.get(language, NO_INPUT["en"]))
    lang = escape(twilio_language)
    voice = _voice_attr(twilio_language)

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Say language="{lang}"{voice}>{greeting}</Say>'
        f'<Gather numDigits="1" action="{action}" method="POST" timeout="10">'
        f'<Say language="{lang}"{voice}>{menu}</Say>'
        "</Gather>"
        f'<Say language="{lang}"{voice}>{no_input}</Say>'
        "<Hangup/>"
        "</Response>"
    )


def process_service_menu(digit: str) -> dict:
    """
    Map DTMF digit to service type.
    Returns state updates. TwiML is built by the booking node.
    """
    service_map = {
        "1": "book",
        "2": "reschedule",
        "3": "cancel",
    }
    service = service_map.get(digit)

    if not service:
        logger.warning(f"Invalid service digit: {digit!r}")
        return {"step": "service_menu", "retry_count_increment": True}

    logger.info(f"Service selected: {service} (digit={digit})")
    return {
        "step": f"collect_name",
        "service": service,
        "retry_count": 0,
    }