"""Live FAQ RAG evaluation cases and metrics for Hospital 1 KB."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalCase:
    query: str
    expected_topic: str
    language_group: str  # marathi | roman_marathi | english | hindi | mixed | negative
    positive: bool = True


EVAL_CASES: tuple[EvalCase, ...] = (
    # Marathi
    EvalCase("ओपीडीची वेळ काय आहे?", "opd", "marathi"),
    EvalCase("कॅशलेस इन्शुरन्स आहे का?", "insurance", "marathi"),
    EvalCase("पार्किंग उपलब्ध आहे का?", "parking", "marathi"),
    EvalCase("डॉक्टर उद्या उपलब्ध आहेत का?", "doctor", "marathi"),
    EvalCase("रविवारी ओपीडी असते का?", "opd", "marathi"),
    # Roman Marathi
    EvalCase("OPD kiti vajta suru hote?", "opd", "roman_marathi"),
    EvalCase("cashless insurance aahe ka?", "insurance", "roman_marathi"),
    EvalCase("parking available aahe ka?", "parking", "roman_marathi"),
    EvalCase("doctor udya available aahet ka?", "doctor", "roman_marathi"),
    EvalCase("ravivari OPD aste ka?", "opd", "roman_marathi"),
    # English
    EvalCase("What time does OPD start?", "opd", "english"),
    EvalCase("Is cashless insurance available?", "insurance", "english"),
    EvalCase("Is parking available?", "parking", "english"),
    EvalCase("Is the doctor available tomorrow?", "doctor", "english"),
    EvalCase("Is OPD open on Sunday?", "opd", "english"),
    # Hindi
    EvalCase("OPD kab shuru hota hai?", "opd", "hindi"),
    EvalCase("Cashless insurance hai kya?", "insurance", "hindi"),
    EvalCase("Parking available hai kya?", "parking", "hindi"),
    EvalCase("Doctor kal available hain?", "doctor", "hindi"),
    EvalCase("Ravivar ko OPD hota hai kya?", "opd", "hindi"),
    # Mixed
    EvalCase("OPD chi timing kay aahe?", "opd", "mixed"),
    EvalCase("Cashless insurance available आहे का?", "insurance", "mixed"),
    EvalCase("Doctor उद्या available आहेत का?", "doctor", "mixed"),
    EvalCase("Parking available aahe ka?", "parking", "mixed"),
    # Negative
    EvalCase("quantum flux capacitor warranty?", "none", "negative", False),
    EvalCase("weather forecast today?", "none", "negative", False),
    EvalCase("unrelated hospital service?", "none", "negative", False),
    EvalCase("another hospital's information?", "none", "negative", False),
)


def recall_at_k(ranked_ids: list[int], expected_id: int | None, k: int) -> float:
    if expected_id is None:
        return 0.0
    return 1.0 if expected_id in ranked_ids[:k] else 0.0


def hit_at_1(ranked_ids: list[int], expected_id: int | None) -> float:
    if expected_id is None or not ranked_ids:
        return 0.0
    return 1.0 if ranked_ids[0] == expected_id else 0.0


def mrr(ranked_ids: list[int], expected_id: int | None) -> float:
    if expected_id is None:
        return 0.0
    for idx, fid in enumerate(ranked_ids, start=1):
        if fid == expected_id:
            return 1.0 / idx
    return 0.0
