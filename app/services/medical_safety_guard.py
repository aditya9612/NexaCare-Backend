"""Medical safety guard — never diagnose, prescribe, or suggest surgery."""

from dataclasses import dataclass

MEDICAL_ADVICE_MARKERS = {
    "medicine",
    "medication",
    "tablet",
    "capsule",
    "dosage",
    "prescribe",
    "prescription",
    "surgery",
    "operate",
    "operation",
    "diagnose",
    "diagnosis",
    "what should i take",
    "which medicine",
    "should i take",
    "antibiotic",
    "injection",
    "दवा",
    "दवाई",
    "सर्जरी",
    "ऑपरेशन",
    "निदान",
    "औषध",
    "शस्त्रक्रिया",
}


REFUSAL = {
    "en": (
        "I am not allowed to give medical advice, prescribe medicine, "
        "suggest surgery, or provide a diagnosis. "
        "Please speak to our reception or medical staff. "
        "I can transfer you now."
    ),
    "hi": (
        "मैं चिकित्सा सलाह, दवा, सर्जरी या निदान नहीं दे सकती। "
        "कृपया रिसेप्शन या चिकित्सकीय स्टाफ से बात करें। "
        "मैं आपको अभी ट्रांसफर कर सकती हूँ।"
    ),
    "mr": (
        "मी वैद्यकीय सल्ला, औषध, शस्त्रक्रिया किंवा निदान देऊ शकत नाही. "
        "कृपया रिसेप्शन किंवा वैद्यकीय कर्मचाऱ्यांशी बोला. "
        "मी तुम्हाला आत्ता ट्रान्सफर करू शकते."
    ),
}


@dataclass
class SafetyCheckResult:
    is_medical_advice: bool
    refusal_message: str = ""


class MedicalSafetyGuard:
    @staticmethod
    def check(text: str, language: str = "en") -> SafetyCheckResult:
        lowered = (text or "").lower()
        if not lowered:
            return SafetyCheckResult(is_medical_advice=False)
        hit = any(marker in lowered for marker in MEDICAL_ADVICE_MARKERS)
        if not hit:
            return SafetyCheckResult(is_medical_advice=False)
        return SafetyCheckResult(
            is_medical_advice=True,
            refusal_message=REFUSAL.get(language, REFUSAL["en"]),
        )
