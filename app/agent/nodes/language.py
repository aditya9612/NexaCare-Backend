"""
app/agent/nodes/language.py
---------------------------
Node 1: Language selection.
Plays a DTMF prompt: Press 1 for English, 2 for Hindi, 3 for Marathi.
Stores the choice in state and advances to the greeting node.
"""

import logging
from xml.sax.saxutils import escape

from app.services.sarvam_tts import speak

logger = logging.getLogger("nexacare.agent.nodes.language")

# Language config — extend here when adding more languages
LANGUAGE_MAP = {
    "1": {"code": "en", "twilio": "en-IN", "label": "English"},
    "2": {"code": "hi", "twilio": "hi-IN", "label": "Hindi"},
    "3": {"code": "mr", "twilio": "mr-IN", "label": "Marathi"},
}

# Greeting text in each language for the language-select prompt itself
# (must be in the language it represents, so the patient can understand it)
LANGUAGE_PROMPT = (
    "Welcome to NexaCare. "
    "For English, press 1. "
    "हिंदी के लिए, दो दबाइए। "
    "मराठीसाठी, तीन दाबा."
)


def build_language_select_twiml(base_url: str) -> str:
    """
    Returns TwiML that plays the language selection prompt
    and waits for a single DTMF digit.
    Uses raw XML (not twilio SDK) to keep it dependency-light.
    """
    action = escape(f"{base_url}/agent/v1/voice/lang")
    timeout_msg = "We did not receive your selection. Please call again."

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Gather numDigits="1" action="{action}" method="POST" timeout="10">'
        f'{speak(LANGUAGE_PROMPT, "en-IN", base_url)}'
        "</Gather>"
        f'{speak(timeout_msg, "en-IN", base_url)}'
        "<Hangup/>"
        "</Response>"
    )


def process_language_selection(digit: str, base_url: str) -> dict:
    """
    Process the digit pressed and return state updates + next TwiML.
    Called from the /lang webhook.

    Returns dict of state updates to merge.
    """
    lang = LANGUAGE_MAP.get(digit)

    if not lang:
        # Invalid digit — replay prompt
        logger.warning(f"Invalid language digit: {digit!r}")
        return {
            "step": "language_select",
            "retry_count_increment": True,
            "_twiml": build_language_select_twiml(base_url),
        }

    logger.info(f"Language selected: {lang['label']} (digit={digit})")
    return {
        "step": "greeting",
        "language": lang["code"],
        "twilio_language": lang["twilio"],
        "retry_count": 0,
    }