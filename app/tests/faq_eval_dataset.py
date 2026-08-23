"""Offline FAQ retrieval evaluation dataset — positive + negative cases."""

from __future__ import annotations

from app.services.canonical_faq_specs import build_canonical_faq_specs

# Topic → mock KB FAQ id (matches _priority_mock_kb fixture)
TOPIC_TO_MOCK_ID: dict[str, int] = {
    "opd": 1,
    "parking": 2,
    "insurance": 3,
    "visiting": 4,
    "emergency": 5,
    "doctor": 6,
    "billing": 7,
    "ambulance": 8,
    "appointment": 9,
    "cancellation": 10,
    "location": 11,
    "contact": 12,
    "pharmacy": 13,
    "laboratory": 14,
    "emergency_dept": 15,
}


# Standalone tags too ambiguous for Hit@1 eval (would CLARIFY in production).
_AMBIGUOUS_STANDALONE_TAGS = frozenset(
    {
        "timing",
        "hours",
        "hour",
        "contact",
        "phone",
        "number",
        "appointment",
        "cancel",
        "cancellation",
        "emergency",
        "booking",
        "insurance",
        "parking",
        "available",
        "opd",
        "department",
    }
)


def _is_evaluable_query(query: str) -> bool:
    """Skip single-token generic tags that are ambiguous for Hit@1 measurement."""
    key = query.strip().lower()
    if key in _AMBIGUOUS_STANDALONE_TAGS:
        return False
    if len(key) < 8 and " " not in key:
        return False
    return True


def _queries_from_tags(tags: str) -> list[str]:
    return [t.strip() for t in tags.split(",") if len(t.strip()) >= 4]


def build_positive_eval_cases() -> list[tuple[str, int, str]]:
    """Return (query, expected_faq_id, language_group) for all canonical topics."""
    cases: list[tuple[str, int, str]] = []
    for spec in build_canonical_faq_specs():
        topic = spec["topic"]
        faq_id = TOPIC_TO_MOCK_ID.get(topic)
        if faq_id is None:
            continue
        question = spec["question"]
        tags = spec.get("tags", "")
        seen: set[str] = set()

        def _add(q: str, group: str) -> None:
            key = q.strip().lower()
            if key and key not in seen:
                seen.add(key)
                cases.append((q.strip(), faq_id, group))

        _add(question, "marathi")
        for tag_query in _queries_from_tags(tags):
            if not _is_evaluable_query(tag_query):
                continue
            group = "marathi"
            if any("\u0900" <= c <= "\u097F" for c in tag_query):
                if any(c.isascii() and c.isalpha() for c in tag_query):
                    group = "mixed"
                else:
                    group = "marathi"
            elif any(w in tag_query.lower() for w in ("aahe", "aahet", "vajta", "kay", "kiti", "udya", "aste")):
                group = "roman_marathi"
            elif any(w in tag_query.lower() for w in ("hai", "kya", "kab", "hota", "hain")):
                group = "hindi"
            else:
                group = "english"
            _add(tag_query, group)
    return cases


NEGATIVE_EVAL_QUERIES: tuple[str, ...] = (
    "quantum flux capacitor warranty?",
    "weather forecast today?",
    "unrelated hospital service?",
    "another hospital's information?",
    "stock market update?",
    "cricket match score?",
    "movie ticket booking?",
    "pizza delivery near me?",
    "flight schedule to Dubai?",
    "software bug in Windows?",
    "best restaurant in Mumbai?",
    "political election results?",
    "cryptocurrency price today?",
    "how to hack wifi password?",
    "dating advice please?",
    "school homework help?",
    "car insurance quote online?",
    "hotel booking in Goa?",
    "train ticket availability?",
    "visa application process?",
    "passport renewal steps?",
    "income tax filing help?",
    "mutual fund investment advice?",
    "real estate property rates?",
    "job interview tips?",
    "resume writing service?",
    "grocery delivery app?",
    "electricity bill payment online?",
    "mobile recharge offer?",
    "netflix subscription plan?",
    "amazon order tracking?",
    "facebook account recovery?",
    "instagram followers increase?",
    "youtube video download?",
    "gaming cheat codes?",
    "lottery winning numbers?",
    "horoscope today?",
    "astrology consultation?",
    "tarot card reading?",
    "fortune teller near me?",
    "pet grooming service?",
    "plumber contact number?",
    "electrician for home repair?",
    "carpenter work quotation?",
    "interior design ideas?",
    "wedding planner contact?",
    "photography studio rates?",
    "gym membership fees?",
    "yoga class schedule?",
    "dance class enrollment?",
    "music lesson booking?",
    "language course fees?",
)


POSITIVE_EVAL_CASES = build_positive_eval_cases()

# Legacy compact matrix (kept for backward-compatible regression checks)
OPD_EVAL_CASES = [(q, i) for q, i, _ in POSITIVE_EVAL_CASES if i == 1][:15]
INSURANCE_EVAL_CASES = [(q, i) for q, i, _ in POSITIVE_EVAL_CASES if i == 3][:6]
PARKING_EVAL_CASES = [(q, i) for q, i, _ in POSITIVE_EVAL_CASES if i == 2][:5]
ALL_EVAL_CASES = list({(q, i): (q, i) for q, i, _ in POSITIVE_EVAL_CASES}.values())

LANGUAGE_GROUPS = frozenset({"marathi", "roman_marathi", "english", "hindi", "mixed"})
