import re

from app.core.constants import VoiceLanguage

MARATHI_MARKERS = {"आहे", "करू", "शकते", "नमस्कार", "अपॉइंटमेंट", "रुग्णालय", "मदत"}
HINDI_MARKERS = {"है", "कर", "सकती", "नमस्ते", "अपॉइंटमेंट", "अस्पताल", "मदद", "कृपया"}


def detect_language(text: str, current: str = "en") -> str:
    """
    AI / heuristic language detection.

    Secondary fallback ONLY — production flow must use:
    patient.preferred_language → DTMF menu → then this helper if DTMF unavailable.
    Do NOT call this on every conversational turn to switch languages mid-call.
    """
    if not text or not text.strip():
        return current if current in VoiceLanguage.ALL else VoiceLanguage.EN

    if re.search(r"[\u0900-\u097F]", text):
        marathi_score = sum(1 for m in MARATHI_MARKERS if m in text)
        hindi_score = sum(1 for m in HINDI_MARKERS if m in text)
        if marathi_score > hindi_score:
            return VoiceLanguage.MR
        if hindi_score > marathi_score:
            return VoiceLanguage.HI
        return current if current in (VoiceLanguage.HI, VoiceLanguage.MR) else VoiceLanguage.HI

    lowered = text.lower()
    if any(w in lowered for w in ("namaskar", "mala", "karu", "shakte", "ahe")):
        return VoiceLanguage.MR
    if any(w in lowered for w in ("namaste", "kripya", "sahayata", "hai", "hoon")):
        return VoiceLanguage.HI
    return VoiceLanguage.EN


def language_select_prompt(default_language: str = "en") -> str:
    """DTMF language menu — primary selection mechanism for new patients."""
    return {
        "en": "Press 1 for English. Press 2 for Hindi. Press 3 for Marathi.",
        "hi": "अंग्रेज़ी के लिए 1 दबाएँ। हिंदी के लिए 2 दबाएँ। मराठी के लिए 3 दबाएँ।",
        "mr": "इंग्रजीसाठी 1 दाबा. हिंदीसाठी 2 दाबा. मराठीसाठी 3 दाबा.",
    }.get(default_language, "Press 1 for English. Press 2 for Hindi. Press 3 for Marathi.")
