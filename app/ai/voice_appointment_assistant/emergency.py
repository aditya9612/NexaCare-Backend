EMERGENCY_KEYWORDS = {
    "en": [
        "chest pain",
        "severe bleeding",
        "unconscious",
        "emergency",
        "accident",
        "breathing problem",
        "can't breathe",
        "cannot breathe",
        "heart attack",
        "stroke",
    ],
    "hi": [
        "सीने में दर्द",
        "खून",
        "बेहोश",
        "आपातकाल",
        "दुर्घटना",
        "सांस",
        "इमरजेंसी",
        "एमरजेंसी",
    ],
    "mr": [
        "छातीत दुखणे",
        "रक्तस्त्राव",
        "बेशुद्ध",
        "आपत्काल",
        "अपघात",
        "श्वास",
        "इमर्जन्सी",
    ],
}

EMERGENCY_MESSAGES = {
    "en": (
        "This appears to be an emergency. "
        "Please visit the nearest hospital or call emergency services immediately."
    ),
    "hi": (
        "यह एक आपातकालीन स्थिति लग रही है। "
        "कृपया तुरंत अस्पताल जाएं या इमरजेंसी सेवाओं से संपर्क करें।"
    ),
    "mr": (
        "ही आपत्कालीन परिस्थिती वाटत आहे. "
        "कृपया त्वरित रुग्णालयात जा किंवा आपत्कालीन सेवांशी संपर्क साधा."
    ),
}


def is_emergency(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower().strip()
    for keywords in EMERGENCY_KEYWORDS.values():
        for kw in keywords:
            if kw.lower() in lowered:
                return True
    return False


def emergency_message(language: str) -> str:
    return EMERGENCY_MESSAGES.get(language, EMERGENCY_MESSAGES["en"])
