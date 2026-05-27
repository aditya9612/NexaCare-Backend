import re

MARATHI_MARKERS = {"आहे", "करू", "शकते", "नमस्कार", "अपॉइंटमेंट", "रुग्णालय", "मदत"}
HINDI_MARKERS = {"है", "कर", "सकती", "नमस्ते", "अपॉइंटमेंट", "अस्पताल", "मदद", "कृपया"}


def detect_language(text: str, current: str = "en") -> str:
    if not text or not text.strip():
        return current

    if re.search(r"[\u0900-\u097F]", text):
        marathi_score = sum(1 for m in MARATHI_MARKERS if m in text)
        hindi_score = sum(1 for m in HINDI_MARKERS if m in text)
        if marathi_score > hindi_score:
            return "mr"
        if hindi_score > marathi_score:
            return "hi"
        return current if current in ("hi", "mr") else "hi"

    lowered = text.lower()
    if any(w in lowered for w in ("namaskar", "mala", "karu", "shakte", "ahe")):
        return "mr"
    if any(w in lowered for w in ("namaste", "kripya", "sahayata", "hai", "hoon")):
        return "hi"
    return "en"
