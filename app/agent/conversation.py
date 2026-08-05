"""
app/agent/conversation.py
-------------------------
Phase 6 conversation enhancement helpers for Flow B voice agent.

Rollback: set VOICE_PHASE6_ENABLED=false (default) to restore single-turn FAQ
and immediate hangup after booking. No DB migration required.

Feature flag rollback verification:
  1. Set VOICE_PHASE6_ENABLED=false in .env
  2. Restart uvicorn
  3. Smoke: FAQ answers once then hangs up; booking completes then hangs up
  4. Redis session delete on terminal paths still works
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from app.agent.state import BookingCallState

logger = logging.getLogger("nexacare.agent.conversation")

# ── Limits ───────────────────────────────────────────────────────────────────
MAX_QUESTIONS = 10
MAX_CALL_MINUTES = 15

# ── Intent labels (router-only — does not replace VoiceIntent enum) ──────────
class ConversationIntent(str, Enum):
    FAQ = "FAQ"
    BOOKING = "BOOKING"
    TRANSFER = "TRANSFER"
    GOODBYE = "GOODBYE"
    UNKNOWN = "UNKNOWN"


YesNo = Literal["yes", "no", "unknown"]


def is_phase6_enabled() -> bool:
    try:
        from app.core.config import settings

        return bool(getattr(settings, "VOICE_PHASE6_ENABLED", False))
    except Exception:
        return False


# ── Multilingual phrase sets ─────────────────────────────────────────────────

YES_PHRASES = {
    "en": {"yes", "yeah", "yep", "sure", "continue", "ok", "okay", "1"},
    "hi": {"हाँ", "हां", "जी", "ठीक", "haan", "ha", "ji", "1"},
    "mr": {
        "हो",
        "होय",
        "नक्की",
        "आणखी आहे",
        "विचारायचे आहे",
        "ho",
        "hoy",
        "nakki",
        "1",
    },
}

NO_PHRASES = {
    "en": {"no", "nope", "nothing", "thanks", "thank you", "done", "2"},
    "hi": {"नहीं", "नही", "nahin", "nahi", "2"},
    "mr": {"नाही", "झाले", "बस", "धन्यवाद", "nahi", "zale", "bas", "2"},
}

GOODBYE_PHRASES = {
    "en": {
        "goodbye",
        "bye",
        "thank you",
        "thanks",
        "that's all",
        "thats all",
        "nothing else",
        "no more",
    },
    "hi": {"अलविदा", "धन्यवाद", "बस", "ठीक है"},
    "mr": {"नमस्कार", "धन्यवाद", "बस", "झाले"},
}

TRANSFER_PHRASES = {
    "en": {
        "reception",
        "receptionist",
        "operator",
        "human",
        "person",
        "talk to someone",
        "speak to someone",
        "transfer",
        "4",
    },
    "hi": {"रिसेप्शन", "मानव", "ऑपरेटर", "किसी से बात", "4"},
    "mr": {"रिसेप्शन", "मानव", "ऑपरेटर", "कोणाशी बोल", "4"},
}

BOOKING_PHRASES = {
    "en": {
        "book",
        "booking",
        "appointment",
        "schedule",
        "new appointment",
        "see doctor",
        "1",
    },
    "hi": {
        "बुक",
        "बुकिंग",
        "अपॉइंटमेंट",
        "नियुक्ति",
        "डॉक्टर",
        "मिलना",
        "1",
    },
    "mr": {
        "बुक",
        "बुकिंग",
        "अपॉइंटमेंट",
        "भेट",
        "वेळ",
        "डॉक्टर",
        "book karaychi",
        "appointment book",
        "udya appointment",
        "1",
    },
}

FAQ_PHRASES = {
    "en": {
        "hours",
        "timing",
        "time",
        "open",
        "close",
        "location",
        "address",
        "contact",
        "fee",
        "fees",
        "parking",
        "canteen",
        "cafeteria",
        "hospital",
        "information",
        "info",
        "faq",
        "where",
        "when",
        "what",
        "how",
        "4",
    },
    "hi": {
        "समय",
        "घंटे",
        "खुला",
        "बंद",
        "पता",
        "स्थान",
        "संपर्क",
        "शुल्क",
        "पार्किंग",
        "कैंटीन",
        "अस्पताल",
        "जानकारी",
        "4",
    },
    "mr": {
        "वेळ",
        "किती वाजे",
        "kiti vajey",
        "उघडे",
        "बंद",
        "पत्ता",
        "संपर्क",
        "शुल्क",
        "पार्किंग",
        "parking",
        "canteen",
        "कॅन्टीन",
        "रुग्णालय",
        "rugnalay",
        "माहिती",
        "aahe ka",
        "aahe",
        "4",
    },
}

# Natural Marathi conversational fragments (Phase 6.6)
FAQ_NATURAL_PATTERNS = [
    r"kiti\s+vaj",
    r"rugnalay",
    r"doctor\s+udya",
    r"udya\s+.*mil",
    r"parking\s+aahe",
    r"canteen\s+aahe",
    r"aahe\s+ka",
    r"kay\s+aahe",
    r"sur[uū]?\s+aste",
]

LIMIT_PROMPTS = {
    "en": "We have reached the conversation limit. Thank you for calling NexaCare. Goodbye.",
    "hi": "वार्तालाप की सीमा पूरी हो गई। NexaCare को कॉल करने के लिए धन्यवाद।",
    "mr": "संवादाची मर्यादा पूर्ण झाली. NexaCare ला कॉल केल्याबद्दल धन्यवाद.",
}

GOODBYE_MESSAGES = {
    "en": "Thank you for calling NexaCare.",
    "hi": "धन्यवाद.",
    "mr": "धन्यवाद. NexaCare ला कॉल केल्याबद्दल आभारी आहोत.",
}

FAQ_CONTINUE_PROMPTS = {
    "en": "Do you want to ask anything else?",
    "hi": "क्या आप कुछ और पूछना चाहते हैं?",
    "mr": "तुम्हाला आणखी काही विचारायचे आहे का?",
}

POST_BOOKING_PROMPTS = {
    "en": "Your appointment is confirmed. Do you have any other questions?",
    "hi": "आपका अपॉइंटमेंट कन्फर्म हो गया। कोई और सवाल?",
    "mr": "तुमची अपॉइंटमेंट कन्फर्म झाली. आणखी काही प्रश्न?",
}

RESUME_BOOKING_PROMPTS = {
    "en": "Would you like to continue your appointment booking?",
    "hi": "क्या आप अपॉइंटमेंट बुकिंग जारी रखना चाहते हैं?",
    "mr": "तुम्ही अपॉइंटमेंट बुकिंग सुरू ठेवू इच्छिता?",
}

BOOKING_LOCK_REDIRECT_PROMPTS = {
    "en": (
        "Let's complete your appointment booking first. "
        "After that I'll answer all your questions."
    ),
    "hi": (
        "पहले हम आपकी अपॉइंटमेंट पूरी कर लेते हैं। "
        "उसके बाद मैं आपके सभी प्रश्नों के उत्तर दूँगा।"
    ),
    "mr": (
        "आधी आपण अपॉइंटमेंट बुकिंग पूर्ण करूया. "
        "त्यानंतर मी तुमच्या सर्व प्रश्नांची उत्तरे देईन."
    ),
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _contains_phrase(text: str, phrases: set[str]) -> bool:
    normalized = _normalize(text)
    if not normalized:
        return False
    for phrase in phrases:
        if phrase in normalized or normalized == phrase:
            return True
    return False


def _matches_any_pattern(text: str, patterns: list[str]) -> bool:
    normalized = _normalize(text)
    return any(re.search(p, normalized) for p in patterns)


def detect_yes_no(transcript: str, lang: str) -> YesNo:
    text = (transcript or "").strip()
    if not text:
        return "unknown"

    normalized = _normalize(text)
    digit = text.strip()

    if digit == "1":
        return "yes"
    if digit == "2":
        return "no"

    lang_key = lang if lang in ("en", "hi", "mr") else "en"
    all_yes = set().union(*YES_PHRASES.values())
    all_no = set().union(*NO_PHRASES.values())

    if _contains_phrase(text, YES_PHRASES.get(lang_key, YES_PHRASES["en"])) or normalized in all_yes:
        return "yes"
    if _contains_phrase(text, NO_PHRASES.get(lang_key, NO_PHRASES["en"])) or normalized in all_no:
        return "no"
    return "unknown"


def route_intent(transcript: str, state: BookingCallState) -> ConversationIntent:
    """
    Lightweight pre-state intent router. Routes only — never performs booking.
    Priority: TRANSFER > GOODBYE > BOOKING > FAQ > UNKNOWN.
    """
    text = (transcript or "").strip()
    if not text:
        return ConversationIntent.UNKNOWN

    lang = state.get("language") or "en"
    lang_key = lang if lang in ("en", "hi", "mr") else "en"

    if _contains_phrase(text, TRANSFER_PHRASES.get(lang_key, TRANSFER_PHRASES["en"])):
        return ConversationIntent.TRANSFER

    if _contains_phrase(text, GOODBYE_PHRASES.get(lang_key, GOODBYE_PHRASES["en"])):
        return ConversationIntent.GOODBYE

    if _contains_phrase(text, BOOKING_PHRASES.get(lang_key, BOOKING_PHRASES["en"])):
        return ConversationIntent.BOOKING

    faq_phrases = FAQ_PHRASES.get(lang_key, FAQ_PHRASES["en"])
    if _contains_phrase(text, faq_phrases) or _matches_any_pattern(text, FAQ_NATURAL_PATTERNS):
        return ConversationIntent.FAQ

    # Question-shaped utterances default to FAQ in conversational mode
    if any(ch in text for ch in "?") or text.lower().startswith(
        ("what", "when", "where", "how", "is", "are", "can", "do", "kay", "kiti")
    ):
        return ConversationIntent.FAQ

    return ConversationIntent.UNKNOWN


def goodbye_message(lang: str) -> str:
    return GOODBYE_MESSAGES.get(lang, GOODBYE_MESSAGES["en"])


def faq_continue_prompt(lang: str) -> str:
    return FAQ_CONTINUE_PROMPTS.get(lang, FAQ_CONTINUE_PROMPTS["en"])


def post_booking_prompt(lang: str) -> str:
    return POST_BOOKING_PROMPTS.get(lang, POST_BOOKING_PROMPTS["en"])


def limit_message(lang: str) -> str:
    return LIMIT_PROMPTS.get(lang, LIMIT_PROMPTS["en"])


def init_call_timestamps(state: BookingCallState) -> None:
    if not state.get("call_started_at"):
        state["call_started_at"] = datetime.now(timezone.utc).isoformat()


def update_memory(
    state: BookingCallState,
    *,
    question: Optional[str] = None,
    answer: Optional[str] = None,
    topic: Optional[str] = None,
    intent: Optional[str] = None,
    increment_question: bool = False,
) -> None:
    lang = state.get("language") or "en"
    state["current_language"] = lang

    if question:
        state["last_question"] = question[:500]
    if answer:
        state["last_answer"] = answer[:1000]
    if topic:
        state["current_topic"] = topic[:200]
    if intent:
        state["current_intent"] = intent

    if increment_question:
        state["question_count"] = int(state.get("question_count") or 0) + 1


def record_analytics_event(state: BookingCallState, event: str, **data) -> None:
    events = list(state.get("conversation_analytics") or [])
    events.append(
        {
            "event": event,
            "ts": datetime.now(timezone.utc).isoformat(),
            **{k: v for k, v in data.items() if v is not None},
        }
    )
    # Cap event log size
    state["conversation_analytics"] = events[-50:]
    logger.info(
        "[phase6-analytics] call_sid=%s event=%s data=%s",
        state.get("call_sid"),
        event,
        data,
    )


def bump_counter(state: BookingCallState, field: str) -> None:
    state[field] = int(state.get(field) or 0) + 1


def add_faq_topic(state: BookingCallState, topic: str) -> None:
    if not topic:
        return
    topics = list(state.get("faq_topics") or [])
    short = topic[:120]
    if short not in topics:
        topics.append(short)
    state["faq_topics"] = topics[-20:]


def check_conversation_limits(state: BookingCallState) -> bool:
    """Return True if limits exceeded and call should end."""
    question_count = int(state.get("question_count") or 0)
    if question_count > MAX_QUESTIONS:
        return True

    started = state.get("call_started_at")
    if not started:
        return False
    try:
        started_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
        elapsed = datetime.now(timezone.utc) - started_dt
        if elapsed.total_seconds() > MAX_CALL_MINUTES * 60:
            return True
    except (ValueError, TypeError):
        return False
    return False


def booking_steps() -> set[str]:
    return {
        "collect_name",
        "collect_problem",
        "suggest_doctors",
        "select_slot",
        "confirm",
    }


def is_booking_lock_active(state: BookingCallState) -> bool:
    """True while transactional booking owns the conversation."""
    return (state.get("step") or "") in booking_steps()


def booking_lock_redirect_message(lang: str) -> str:
    lang_key = lang if lang in ("en", "hi", "mr") else "en"
    return BOOKING_LOCK_REDIRECT_PROMPTS.get(lang_key, BOOKING_LOCK_REDIRECT_PROMPTS["en"])


def should_allow_intent_switch(state: BookingCallState, intent: ConversationIntent) -> bool:
    """Guard intent switching during active booking unless explicitly safe."""
    if not is_booking_lock_active(state):
        return True
    # Booking lock: only TRANSFER and GOODBYE may leave booking. FAQ is blocked.
    if intent == ConversationIntent.BOOKING:
        return False
    return intent in {
        ConversationIntent.TRANSFER,
        ConversationIntent.GOODBYE,
    }


def log_session_analytics_summary(state: BookingCallState) -> None:
    logger.info(
        "[phase6-summary] call_sid=%s questions=%s faq=%s booking=%s transfer=%s "
        "unknown=%s lang=%s topics=%s events=%s",
        state.get("call_sid"),
        state.get("question_count"),
        state.get("faq_count"),
        state.get("booking_count"),
        state.get("transfer_count"),
        state.get("unknown_count"),
        state.get("current_language") or state.get("language"),
        state.get("faq_topics"),
        len(state.get("conversation_analytics") or []),
    )
