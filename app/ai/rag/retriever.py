"""
KnowledgeRetriever — hybrid semantic + keyword retrieval over hospital knowledge embeddings.

Integration:
- Loads vectors via EmbeddingStore (MySQL + Redis cache)
- Lazy-backfills missing embeddings from MySQL KB snapshot
- Called by RagFaqService only

Does not call OpenAI chat; does not touch booking flows.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings.service import EmbeddingService, EmbeddingUnavailableError
from app.ai.embeddings.store import (
    EmbeddingStore,
    build_embed_text,
    label_for_entry,
)
from app.core.logger import logger
from app.repositories.hospital_voice_repository import (
    HospitalFaqRepository,
    HospitalPolicyRepository,
    HospitalVoiceDocumentRepository,
)

# Source reliability for active KB rows (not a tiebreaker — used in fusion).
SOURCE_AUTHORITY_SCORE = {"faq": 1.0, "policy": 0.85, "document": 0.70}
# Legacy alias kept for tests referencing the old constant name.
SOURCE_AUTHORITY_BONUS = SOURCE_AUTHORITY_SCORE

# Canonical hospital FAQs are stored under this language; always merged for retrieval.
CANONICAL_KB_LANGUAGE = "mr"

SEMANTIC_FUSION_WEIGHT = 0.65
KEYWORD_FUSION_WEIGHT = 0.35
WEAK_SEMANTIC_ANSWER_BLOCK = 0.55
ANSWER_BAND_WITHOUT_SEMANTIC_CAP = 0.89

# Retrieval-only token equivalence (never changes KB answers).
TOKEN_EQUIVALENCE_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"opd", "opd", "ओपीडी", "ओपडी", "ओपिडी", "ओपीडीची"}),
    frozenset({"timing", "time", "hours", "hour", "vel", "वेळ", "vajta", "vajey", "vajet", "वाजता", "वाजे", "vajeyparyant", "वाजेपर्यंत"}),
    frozenset({"kiti", "किती", "when"}),
    frozenset({"kay", "काय", "what"}),
    frozenset({"aahe", "aahet", "ahe", "ahet", "आहे", "आहेत", "ka", "का"}),
    frozenset(
        {
            "suru",
            "start",
            "starts",
            "hote",
            "hota",
            "hot",
            "hotat",
            "hot",
            "open",
            "सुरू",
            "चालू",
            "chalu",
            "होते",
            "होता",
            "होत",
            "उघड",
            "उघडे",
            "asate",
            "असते",
            "aste",
            "अस्त",
            "hoga",
            "hogi",
        }
    ),
    frozenset({"insurance", "cashless", "इन्शुरन्स", "कॅशलेस", "cashless"}),
    frozenset({"ambulance", "अॅम्ब्युलन्स", "number", "नंबर", "contact", "phone"}),
    frozenset({"hospital", "रुग्णालय", "rugnalay", "aspatal", "अस्पताल"}),
    frozenset({"parking", "पार्किंग", "available", "availble", "उपलब्ध"}),
    frozenset({"doctor", "dr", "डॉक्टर", "udya", "उद्या"}),
    frozenset({"billing", "बिलिंग", "counter", "close", "closed", "band", "बंद"}),
    frozenset({"appointment", "अपॉइंटमेंट", "cancel", "cancellation", "रद्द"}),
    frozenset(
        {
            "sunday",
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "रविवार",
            "रविवारी",
            "सोमवार",
            "ravivar",
            "ravivari",
        }
    ),
    frozenset({"location", "address", "patta", "पत्ता", "kuthe", "कुठे"}),
    frozenset({"visiting", "visit", "visitor", "visitors", "भेट"}),
    frozenset({"appointment", "अपॉइंटमेंट", "booking", "book"}),
    frozenset({"cancellation", "cancel", "रद्द"}),
    frozenset({"pharmacy", "फार्मसी", "medical", "store"}),
    frozenset({"laboratory", "lab", "लॅब", "blood", "test"}),
    frozenset({"contact", "phone", "number", "संपर्क"}),
)

# Distinct hospital topics for keyword entity alignment (retrieval-only).
ENTITY_SCORING_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"opd", "ओपीडी", "ओपडी", "ओपिडी", "ओपीडीची"}),
    frozenset({"parking", "पार्किंग"}),
    frozenset({"insurance", "cashless", "इन्शुरन्स", "कॅशलेस"}),
    frozenset({"visiting", "visit", "visitor", "visitors", "भेट", "रुग्णालयाची", "हॉस्पिटल"}),
    frozenset({"emergency", "आपत्कालीन", "dept", "department", "विभाग"}),
    frozenset({"ambulance", "अॅम्ब्युलन्स", "रुग्णवाहिका", "एम्बुलेंस"}),
    frozenset({"doctor", "dr", "डॉक्टर"}),
    frozenset({"billing", "बिलिंग", "counter"}),
    frozenset({"appointment", "अपॉइंटमेंट", "booking", "book"}),
    frozenset({"cancellation", "cancel", "रद्द"}),
    frozenset({"location", "address", "patta", "पत्ता", "kuthe", "कुठे"}),
    frozenset({"contact", "phone", "number", "संपर्क", "क्रमांक"}),
    frozenset({"pharmacy", "फार्मसी", "फार्मसीची", "medical", "store", "medicine", "shop"}),
    frozenset({"laboratory", "lab", "लॅब", "लॅबची", "blood", "test", "x-ray", "mri"}),
)

OPD_ENTITY_TOKENS = frozenset({"opd", "ओपीडी", "ओपडी", "ओपिडी", "ओपीडीची"})
SUNDAY_DAY_TOKENS = frozenset(
    {"sunday", "ravivar", "ravivari", "रविवार", "रविवारी"}
)
AVAILABILITY_STATUS_TOKENS = frozenset(
    {
        "suru",
        "start",
        "starts",
        "open",
        "asate",
        "aste",
        "ahe",
        "aahe",
        "ahet",
        "aahet",
        "सुरू",
        "चालू",
        "chalu",
        "असते",
        "अस्त",
        "आहे",
        "आहेत",
        "होते",
        "होता",
        "होत",
        "hota",
        "hote",
        "hotat",
        "hot",
        "hoga",
        "hogi",
        "उघड",
        "उघडे",
    }
)
TIMING_INTENT_TOKENS = frozenset(
    {
        "kiti",
        "किती",
        "vajta",
        "vajey",
        "vajet",
        "वाजता",
        "वाजे",
        "वेळ",
        "vel",
        "timing",
        "time",
        "hours",
        "hour",
        "when",
        "kab",
        "कधी",
    }
)

# Generic tokens that alone must not drive entity/topic alignment.
GENERIC_ENTITY_TOKENS = frozenset(
    {
        "timing",
        "time",
        "times",
        "hours",
        "hour",
        "open",
        "close",
        "closed",
        "contact",
        "phone",
        "number",
        "booking",
        "book",
        "available",
        "department",
        "dept",
        "service",
        "services",
        "today",
        "tomorrow",
        "vel",
        "vajta",
        "vajey",
        "what",
        "when",
        "where",
        "how",
        "is",
        "the",
        "a",
        "an",
        "ka",
        "aahe",
        "hai",
        "kya",
        "kay",
        "kiti",
        "kab",
    }
)

# Hospital / entity terms kept as-is during retrieval normalization (never invent facts).
PRESERVE_TERMS = frozenset(
    {
        "opd",
        "icu",
        "er",
        "emergency",
        "doctor",
        "dr",
        "insurance",
        "cashless",
        "billing",
        "appointment",
        "ambulance",
        "hospital",
        "timing",
        "timings",
        "time",
        "hours",
        "hour",
        "available",
        "availability",
        "open",
        "close",
        "closed",
        "counter",
        "admission",
        "department",
        "dept",
        "parking",
        "location",
        "contact",
        "number",
        "phone",
        "sunday",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "patil",
        "sharma",
        "desai",
        "joshi",
    }
)

# Roman Marathi phrases (longest first) — retrieval-only, maps to Devanagari for embedding/keyword.
ROMAN_MARATHI_PHRASES: tuple[tuple[str, str], ...] = (
    ("aahet ka", "आहेत का"),
    ("aahe ka", "आहे का"),
    ("kay aahe", "काय आहे"),
    ("kiti vajeyparyant", "किती वाजेपर्यंत"),
    ("kiti vajta", "किती वाजता"),
    ("kiti vajey", "किती वाजे"),
    ("suru hote", "सुरू होते"),
    ("suru hot", "सुरू होत"),
    ("ugad aahe", "उघड आहे"),
    ("band aahe", "बंद आहे"),
    ("sur hote", "सुरू होते"),
    ("suru aste", "सुरू असते"),
)

# Common Roman Marathi tokens for FAQ/voice queries (retrieval-only).
ROMAN_MARATHI_WORDS: dict[str, str] = {
    "kiti": "किती",
    "vajta": "वाजता",
    "vajey": "वाजे",
    "vajet": "वाजता",
    "suru": "सुरू",
    "hote": "होते",
    "hota": "होता",
    "hotat": "होतात",
    "hot": "होत",
    "aahe": "आहे",
    "aahet": "आहेत",
    "ahe": "आहे",
    "ahet": "आहेत",
    "ka": "का",
    "kay": "काय",
    "kai": "काय",
    "udya": "उद्या",
    "udyaa": "उद्या",
    "aj": "आज",
    "aaj": "आज",
    "kaal": "काल",
    "kal": "काल",
    "aaste": "असते",
    "la": "ला",
    "chi": "ची",
    "che": "चे",
    "cha": "चा",
    "nahi": "नाही",
    "mala": "मला",
    "tumhi": "तुम्ही",
    "tumhala": "तुम्हाला",
    "kas": "कस",
    "kasa": "कसा",
    "kase": "कसे",
    "kash": "कश",
    "aste": "असते",
    "asat": "असत",
    "asate": "असते",
    "ugad": "उघड",
    "ugade": "उघडे",
    "band": "बंद",
    "rugnalay": "रुग्णालय",
    "milat": "मिळत",
    "mil": "मिळ",
    "namaskar": "नमस्कार",
    "kuthe": "कुठे",
    "konti": "कोणती",
    "kon": "कोण",
}

# Minimal Roman Hindi tokens for FAQ retrieval (retrieval-only).
ROMAN_HINDI_WORDS: dict[str, str] = {
    "kab": "कब",
    "kya": "क्या",
    "hai": "है",
    "hain": "हैं",
    "ka": "का",
    "ki": "की",
    "ke": "के",
    "kal": "कल",
    "aaj": "आज",
    "udya": "कल",
    "shuru": "शुरू",
    "hoti": "होती",
    "hota": "होता",
    "hote": "होते",
    "kahan": "कहाँ",
    "kuthe": "कहाँ",
    "milega": "मिलेगा",
    "milegi": "मिलेगी",
    "available": "available",
    "number": "number",
    "contact": "contact",
}

# Roman Hindi phrases (longest first) — retrieval-only.
ROMAN_HINDI_PHRASES: tuple[tuple[str, str], ...] = (
    ("hai kya", "है क्या"),
    ("hain kya", "हैं क्या"),
    ("kab shuru hota hai", "कब शुरू होता है"),
    ("kab shuru hoti hai", "कब शुरू होती है"),
    ("kya hai", "क्या है"),
    ("available hai", "available है"),
    ("available hai kya", "available है क्या"),
)

# Common STT spelling variants (retrieval-only, deterministic).
STT_SPELLING_FIXES: tuple[tuple[str, str], ...] = (
    (r"वाजजता", "वाजता"),
    (r"वाज्जता", "वाजता"),
    (r"ओपिडी", "ओपीडी"),
    (r"ओप\s*डी", "ओपीडी"),
    (r"ओपी\s*डी", "ओपीडी"),
    (r"ओपी\s*डी\s*ची", "ओपीडीची"),
    (r"ओपी\s*डी\s*चि", "ओपीडीची"),
)

# Controlled time-intent query variants (retrieval assistance only).
_TIME_INTENT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"किती\s+वाजता\s+सुरू\s+होते", "timing काय आहे"),
    (r"वेळ\s+काय\s+आहे", "timing काय आहे"),
    (r"ओपीडीची\s+वेळ\s+काय\s+आहे", "OPD timing काय आहे"),
    (r"what\s+time\s+does\s+opd\s+start", "OPD timing काय आहे"),
    (r"when\s+does\s+opd\s+open", "OPD timing काय आहे"),
    (r"opd\s+kab\s+shuru\s+hota\s+hai", "OPD timing काय आहे"),
    (r"is\s+parking\s+available", "पार्किंग उपलब्ध आहे का"),
    (r"is\s+cashless\s+insurance\s+available", "कॅशलेस इन्शुरन्स आहे का"),
    (r"cashless\s+insurance\s+hai\s+kya", "कॅशलेस इन्शुरन्स आहे का"),
    (r"opd\s+chi\s+timing\s+kay\s+aahe", "OPD किती वाजता सुरू होते"),
    (r"pharmacy\s+chi\s+timing\s+kay\s+aahe", "फार्मसीची वेळ काय आहे"),
    (r"lab\s+chi\s+timing\s+kay\s+aahe", "लॅबची वेळ काय आहे"),
    (r"what\s+time\s+is\s+(?:the\s+)?pharmacy\s+open", "फार्मसीची वेळ काय आहे"),
    (r"what\s+time\s+is\s+(?:the\s+)?lab\s+open", "लॅबची वेळ काय आहे"),
    (r"is\s+emergency\s+open\s+24\s+hours", "आपत्कालीन विभाग किती वाजता उघड असतो"),
    (r"opd\s+timing\s+काय\s+आहे", "OPD किती वाजता सुरू होते"),
    (r"ओपीडीची\s+वेळ\s+काय\s+आहे", "OPD किती वाजता सुरू होते"),
    (r"hospital\s+timings", "भेट वेळ काय आहे"),
    (r"hospital\s+open\s+time", "भेट वेळ काय आहे"),
    (r"emergency\s+contact", "आपत्कालीन विभागाचा संपर्क"),
)


@dataclass
class RetrievedChunk:
    """One retrieved KB entry with similarity score."""

    source: str  # faq | policy | document
    id: int
    text: str
    label: str
    score: float
    semantic_score: float = 0.0
    keyword_score: float = 0.0
    tag_score: float = 0.0
    entity_score: float = 0.0
    language_score: float = 0.0
    authority_score: float = 0.0
    exact_match_score: float = 0.0
    phrase_match_score: float = 0.0
    decision_reason: str = ""
    normalized_candidate: str = ""
    candidate_question: str = ""


@dataclass
class DiagnosticCandidate:
    """Score decomposition for one retrieved KB entry."""

    source: str
    id: int
    rank: int
    semantic_score: float
    keyword_score: float
    tag_score: float
    entity_score: float
    language_score: float
    authority_bonus: float
    exact_match_score: float
    phrase_match_score: float
    fused_score: float
    decision_reason: str
    normalized_candidate: str
    candidate_question: str
    label: str


@dataclass
class RetrievalDiagnostic:
    """Full retrieval diagnostic for one patient query."""

    original_query: str
    detected_language: str
    normalized_query: str
    query_variants: list[str]
    candidates: list[DiagnosticCandidate]
    confidence_action: str
    top_fused_score: float


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity; returns 0.0 on empty/mismatched vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def _normalize_query(text: str) -> str:
    """Whitespace cleanup + STT fixes + retrieval-only Roman Marathi → Devanagari."""
    collapsed = re.sub(r"\s+", " ", (text or "").strip())
    if not collapsed:
        return collapsed
    collapsed = unicodedata.normalize("NFKC", _apply_stt_fixes(collapsed))
    return _retrieval_normalize(collapsed)


def _retrieval_normalize(text: str) -> str:
    """
    Map Roman Marathi tokens to Devanagari to improve hybrid retrieval against mr KB.
    Preserves hospital entities (OPD, doctor names, insurance, days, etc.).
    """
    result = text
    for roman, dev in ROMAN_MARATHI_PHRASES:
        result = re.sub(rf"(?i)\b{re.escape(roman)}\b", dev, result)
    for roman, dev in ROMAN_HINDI_PHRASES:
        result = re.sub(rf"(?i)\b{re.escape(roman)}\b", dev, result)

    def _replace_latin_word(match: re.Match[str]) -> str:
        word = match.group(0)
        key = word.lower()
        if key in PRESERVE_TERMS:
            return word
        if key == "availble":
            return "available"
        mapped = ROMAN_MARATHI_WORDS.get(key)
        if mapped:
            return mapped
        return ROMAN_HINDI_WORDS.get(key, word)

    result = re.sub(r"[A-Za-z]+", _replace_latin_word, result)
    return re.sub(r"\s+", " ", result).strip()


def build_faq_retrieval_embed_text(question: str, tags: str, answer: str) -> str:
    """Build FAQ embed text with retrieval normalization on question+tags only."""
    norm_q = _normalize_query(question)
    norm_tags = _normalize_query(tags) if tags else ""
    return build_embed_text("faq", question=norm_q, tags=norm_tags, answer=answer)


def _retrieval_query_variants(normalized: str) -> list[str]:
    """Controlled retrieval query variants (max 4); never used for answer generation."""
    variants = [normalized]
    if not normalized:
        return variants
    for pattern, replacement in _TIME_INTENT_PATTERNS:
        alt = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
        alt = re.sub(r"\s+", " ", alt).strip()
        if alt and alt != normalized and alt not in variants:
            variants.append(alt)
    return variants[:4]


@dataclass
class RetrievalScoreResult:
    """Decomposed retrieval confidence for one candidate."""

    fused: float
    decision_reason: str


def _apply_stt_fixes(text: str) -> str:
    result = text or ""
    for pattern, replacement in STT_SPELLING_FIXES:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result


def _normalize_for_match(text: str) -> str:
    """Aggressive normalization for exact/phrase comparison (retrieval-only)."""
    collapsed = unicodedata.normalize("NFKC", _apply_stt_fixes(text or ""))
    collapsed = _retrieval_normalize(collapsed)
    collapsed = re.sub(r"[^\w\s\u0900-\u097F]", " ", collapsed)
    collapsed = re.sub(r"\s+", " ", collapsed).strip().lower()
    return collapsed


def _canonical_match_tokens(text: str) -> set[str]:
    """Expand tokens with equivalence groups for cross-script FAQ matching."""
    tokens = _expand_tokens(_tokenize(_normalize_for_match(text)))
    canonical = set(tokens)
    for token in list(tokens):
        for group in TOKEN_EQUIVALENCE_GROUPS:
            if token in group:
                ascii_tokens = sorted(x for x in group if x.isascii() and len(x) > 1)
                canonical.add(ascii_tokens[0] if ascii_tokens else min(group, key=len))
                canonical |= {t for t in group if len(t) > 1}
    return {t for t in canonical if len(t) > 1}


def _match_bigrams(text: str) -> set[str]:
    words = _normalize_for_match(text).split()
    if len(words) < 2:
        return set()
    return {" ".join(words[i : i + 2]) for i in range(len(words) - 1)}


def _exact_match_score(query: str, label: str) -> float:
    """Deterministic exact/near-exact question match after normalization."""
    q_norm = _normalize_for_match(query)
    question = _extract_question_from_label(label)
    if not q_norm or not question:
        return 0.0
    q_part = _normalize_for_match(question)
    if not q_part:
        return 0.0
    if q_norm == q_part:
        return 1.0
    if q_part in q_norm or q_norm in q_part:
        return 0.96
    q_tokens = _canonical_match_tokens(query)
    c_tokens = _canonical_match_tokens(question)
    if not q_tokens or not c_tokens:
        return 0.0
    if q_tokens == c_tokens:
        return 0.98
    overlap = len(q_tokens & c_tokens) / max(len(q_tokens), len(c_tokens))
    if overlap >= 0.95:
        return 0.95
    if overlap >= 0.85:
        return 0.90
    if overlap >= 0.75:
        return 0.82
    return min(0.70, overlap)


def _phrase_match_score(query: str, label: str, embed_text: str) -> float:
    """Phrase-level alignment against canonical question and tag phrases."""
    q_norm = _normalize_for_match(query)
    question = _extract_question_from_label(label)
    if not q_norm or not question:
        return 0.0
    q_tokens = _canonical_match_tokens(query)
    if not q_tokens:
        return 0.0

    candidates = [_normalize_for_match(question)]
    tags_raw = _extract_tags_from_embed_text(embed_text)
    for tag in tags_raw.split(","):
        phrase = tag.strip()
        if len(phrase) >= 4:
            candidates.append(_normalize_for_match(phrase))

    best = 0.0
    q_bigrams = _match_bigrams(query)
    for cand in candidates:
        if not cand:
            continue
        if cand == q_norm:
            best = max(best, 0.95)
            continue
        c_tokens = _canonical_match_tokens(cand)
        if not c_tokens:
            continue
        overlap = len(q_tokens & c_tokens) / max(len(q_tokens), 1)
        if overlap >= 0.90:
            best = max(best, 0.92)
        elif overlap >= 0.75:
            best = max(best, 0.85)
        elif overlap >= 0.60:
            best = max(best, 0.72)
        c_bigrams = _match_bigrams(cand)
        if q_bigrams and c_bigrams:
            bg_overlap = len(q_bigrams & c_bigrams) / max(len(q_bigrams), 1)
            if bg_overlap >= 0.45:
                best = max(best, min(0.90, 0.68 + bg_overlap * 0.25))
    return best


def _authority_score(source: str, *, is_active: bool = True) -> float:
    """FAQ source reliability from KB metadata (active canonical FAQ = 1.0)."""
    if not is_active:
        return 0.0
    return SOURCE_AUTHORITY_SCORE.get(source, 0.50)


def compute_retrieval_confidence(
    *,
    semantic: float,
    keyword: float,
    tag: float,
    entity: float,
    language: float,
    authority: float,
    exact_match: float,
    phrase_match: float,
    source: str = "faq",
) -> RetrievalScoreResult:
    """
    Multi-signal confidence fusion with deterministic match protection.

    Strong exact/phrase matches can reach ANSWER band even when embeddings are weak.
    Keyword-only overlap without entity alignment cannot reach ANSWER band.
    """
    _ = source  # reserved for future per-source tuning

    if entity > 0.0 and entity < 0.52 and keyword >= 0.45:
        fused = min(
            SEMANTIC_FUSION_WEIGHT * max(0.0, semantic)
            + KEYWORD_FUSION_WEIGHT * max(0.0, keyword),
            0.55,
        )
        return RetrievalScoreResult(fused=fused, decision_reason="entity_mismatch")

    if entity <= 0.0 and keyword >= 0.70 and tag >= 0.70:
        fused = min(
            SEMANTIC_FUSION_WEIGHT * max(0.0, semantic)
            + KEYWORD_FUSION_WEIGHT * max(0.0, keyword),
            ANSWER_BAND_WITHOUT_SEMANTIC_CAP,
        )
        return RetrievalScoreResult(fused=fused, decision_reason="entity_mismatch")

    if exact_match >= 0.98 and entity >= 0.72:
        fused = max(
            0.96,
            0.12 * semantic
            + 0.12 * keyword
            + 0.08 * tag
            + 0.10 * entity
            + 0.05 * language
            + 0.08 * authority
            + 0.25 * exact_match
            + 0.20 * phrase_match,
        )
        return RetrievalScoreResult(
            fused=min(0.98, fused),
            decision_reason="strong_deterministic_match",
        )

    if exact_match >= 0.92 and entity >= 0.72:
        fused = max(
            0.93,
            0.12 * semantic
            + 0.12 * keyword
            + 0.08 * tag
            + 0.10 * entity
            + 0.05 * language
            + 0.08 * authority
            + 0.25 * exact_match
            + 0.20 * phrase_match,
        )
        return RetrievalScoreResult(
            fused=min(0.98, fused),
            decision_reason="strong_deterministic_match",
        )

    if (
        phrase_match >= 0.88
        and keyword >= 0.85
        and entity >= 0.80
        and tag >= 0.85
    ):
        fused = max(
            0.91,
            0.84 + phrase_match * 0.12,
            0.18 * semantic
            + 0.18 * keyword
            + 0.10 * tag
            + 0.12 * entity
            + 0.05 * language
            + 0.07 * authority
            + 0.15 * exact_match
            + 0.15 * phrase_match,
        )
        return RetrievalScoreResult(
            fused=min(0.97, fused),
            decision_reason="strong_phrase_match",
        )

    if (
        keyword >= 0.85
        and tag >= 0.85
        and entity >= 0.80
        and language >= 0.95
        and (phrase_match >= 0.70 or exact_match >= 0.70)
    ):
        fused = max(
            0.91,
            0.12 * semantic
            + 0.18 * keyword
            + 0.12 * tag
            + 0.12 * entity
            + 0.05 * language
            + 0.10 * exact_match
            + 0.18 * phrase_match,
        )
        return RetrievalScoreResult(
            fused=min(0.97, fused),
            decision_reason="multi_signal_agreement",
        )

    fused = (
        0.28 * max(0.0, semantic)
        + 0.22 * max(0.0, keyword)
        + 0.10 * max(0.0, tag)
        + 0.12 * max(0.0, entity)
        + 0.05 * max(0.0, language)
        + 0.08 * max(0.0, authority)
        + 0.10 * max(0.0, exact_match)
        + 0.05 * max(0.0, phrase_match)
    )

    independent_signals = [
        keyword >= 0.85,
        tag >= 0.85,
        entity >= 0.80,
        language >= 0.95,
        exact_match >= 0.85 or phrase_match >= 0.88,
    ]
    strong_signal_count = sum(independent_signals)
    reason = "weighted_fusion"
    has_deterministic = exact_match >= 0.85 or phrase_match >= 0.88
    if (
        strong_signal_count >= 3
        and entity >= 0.80
        and (
            semantic >= WEAK_SEMANTIC_ANSWER_BLOCK
            or has_deterministic
            or (keyword >= 0.85 and tag >= 0.85 and phrase_match >= 0.70)
        )
    ):
        fused = max(fused, min(0.96, 0.84 + 0.03 * strong_signal_count))
        reason = "multi_signal_agreement"
    elif (
        strong_signal_count >= 2
        and entity >= 0.80
        and keyword >= 0.85
        and tag >= 0.85
        and (semantic >= 0.55 or has_deterministic or phrase_match >= 0.70)
    ):
        fused = max(fused, min(0.92, 0.76 + 0.05 * strong_signal_count))
        reason = "multi_signal_agreement"

    deterministic = max(exact_match, phrase_match)
    if semantic < WEAK_SEMANTIC_ANSWER_BLOCK and deterministic < 0.80:
        if entity < 0.72 or keyword < 0.55 or tag < 0.70:
            fused = min(fused, ANSWER_BAND_WITHOUT_SEMANTIC_CAP)
            reason = "weak_semantic_cap"

    if entity < 0.52 and keyword >= 0.70 and semantic < 0.40:
        fused = min(fused, 0.68)
        reason = "keyword_only_no_entity"

    # Preserve strong embedding agreement path (original hybrid formula).
    if semantic >= WEAK_SEMANTIC_ANSWER_BLOCK and keyword >= 0.55:
        embedding_path = (
            SEMANTIC_FUSION_WEIGHT * max(0.0, semantic)
            + KEYWORD_FUSION_WEIGHT * max(0.0, keyword)
        )
        fused = max(fused, embedding_path)

    return RetrievalScoreResult(fused=min(1.0, fused), decision_reason=reason)


def fuse_retrieval_score(cosine: float, keyword: float, source: str = "faq") -> float:
    """
    Legacy hybrid entry point — delegates to multi-signal fusion with neutral metadata.
    Keyword overlap alone cannot reach the answer confidence band.
    """
    return compute_retrieval_confidence(
        semantic=cosine,
        keyword=keyword,
        tag=0.0,
        entity=0.0,
        language=0.85,
        authority=_authority_score(source),
        exact_match=0.0,
        phrase_match=0.0,
        source=source,
    ).fused


def _tokenize(text: str) -> set[str]:
    """Tokenize Latin and Devanagari words (matras stay attached to consonants)."""
    tokens: set[str] = set()
    for t in re.findall(r"[A-Za-z]+|[\u0900-\u097F]+", (text or "").lower()):
        if len(t) > 1:
            tokens.add(t)
    return tokens


def _expand_tokens(tokens: set[str]) -> set[str]:
    expanded = set(tokens)
    for group in TOKEN_EQUIVALENCE_GROUPS:
        if expanded & group:
            expanded |= {t for t in group if len(t) > 1}
    return expanded


def _extract_question_from_label(label: str) -> str:
    if "Q:" not in label:
        return ""
    return label.split("Q:", 1)[-1].split("\n", 1)[0].strip()


def _stem_entity_token(token: str) -> str:
    """Strip Marathi/Roman possessive and postposition suffixes for entity alignment."""
    for suffix in (
        "च्या",
        "ची",
        "चा",
        "चे",
        "चं",
        "ला",
        "ली",
        "ना",
        "chi",
        "che",
        "cha",
    ):
        if token.endswith(suffix) and len(token) > len(suffix) + 1:
            return token[: -len(suffix)]
    return token


def _retrieval_tokens(text: str) -> set[str]:
    """Tokenize query/candidate text with STT + cross-script normalization."""
    raw = _tokenize(_normalize_for_match(text))
    tokens: set[str] = set()
    for token in raw:
        tokens.add(token)
        stem = _stem_entity_token(token)
        if stem != token:
            tokens.add(stem)
    return tokens


def _expanded_retrieval_tokens(text: str) -> set[str]:
    return _expand_tokens(_retrieval_tokens(text))


def _query_has_opd_entity(query: str) -> bool:
    return bool(_expanded_retrieval_tokens(query) & OPD_ENTITY_TOKENS)


def _query_has_sunday_opd_availability_intent(query: str) -> bool:
    """Sunday + OPD + open/availability phrasing without explicit timing intent."""
    tokens = _expanded_retrieval_tokens(query)
    has_sunday = bool(tokens & SUNDAY_DAY_TOKENS)
    has_opd = bool(tokens & OPD_ENTITY_TOKENS)
    has_avail = bool(tokens & AVAILABILITY_STATUS_TOKENS)
    has_timing = bool(tokens & TIMING_INTENT_TOKENS)
    return has_sunday and has_opd and has_avail and not has_timing


def _candidate_sunday_opd_strength(label: str, embed_text: str) -> float:
    """
    Rank Sunday-specific OPD availability FAQs above general OPD timing FAQs.
    Returns 1.0 for Sunday OPD availability, 0.0 for general timing-only OPD.
    """
    question = _extract_question_from_label(label)
    tags = _extract_tags_from_embed_text(embed_text)
    q_tokens = _expanded_retrieval_tokens(question)
    tag_tokens = _expanded_retrieval_tokens(tags)
    q_sunday = bool(q_tokens & SUNDAY_DAY_TOKENS)
    tag_sunday = bool(tag_tokens & SUNDAY_DAY_TOKENS)
    q_timing = bool(q_tokens & TIMING_INTENT_TOKENS)
    if q_sunday and not q_timing:
        return 1.0
    if q_timing:
        return 0.0
    if tag_sunday:
        return 0.7
    return 0.3


def _apply_sunday_opd_availability_adjustment(
    fused: float,
    *,
    query: str,
    label: str,
    embed_text: str,
    decision_reason: str,
) -> tuple[float, str]:
    """Boost Sunday OPD availability FAQs; demote general OPD timing for those queries."""
    if not _query_has_sunday_opd_availability_intent(query):
        return fused, decision_reason
    strength = _candidate_sunday_opd_strength(label, embed_text)
    if strength >= 1.0:
        adjusted = max(fused, 0.91)
        return min(1.0, adjusted + 0.02), "sunday_opd_availability_match"
    if strength <= 0.0:
        return min(fused, 0.68), "sunday_opd_timing_mismatch"
    return fused, decision_reason


def _entity_group_ids(tokens: set[str]) -> set[int]:
    """Detect topic entities without expanding generic tokens like contact/number."""
    base = set(tokens)
    for token in list(tokens):
        stem = _stem_entity_token(token)
        if stem != token:
            base.add(stem)

    expanded = set(base)
    for group in ENTITY_SCORING_GROUPS:
        if expanded & group:
            expanded |= {t for t in group if len(t) > 1}

    matched: set[int] = set()
    for idx, group in enumerate(ENTITY_SCORING_GROUPS):
        primary = {t for t in (base & group) if t not in GENERIC_ENTITY_TOKENS}
        if primary:
            matched.add(idx)
    return matched


def _entity_topic_conflict(query: str, embed_text: str, label: str) -> bool:
    """True when query names a hospital topic that conflicts with the candidate."""
    q_groups = _entity_group_ids(_retrieval_tokens(query))
    if not q_groups:
        return False
    question_part = _extract_question_from_label(label)
    c_groups = _entity_group_ids(_retrieval_tokens(question_part))
    if not c_groups:
        corpus_raw = " ".join(p for p in (question_part, embed_text or "", label) if p)
        c_groups = _entity_group_ids(_retrieval_tokens(corpus_raw))
    elif not _query_has_opd_entity(query):
        # Question defines the FAQ topic; tag-only entity overlap must not override.
        opd_group = 0
        q_non_opd = {g for g in q_groups if g != opd_group}
        if q_non_opd and opd_group in c_groups and not (q_groups & c_groups):
            return True
    return bool(c_groups) and not (q_groups & c_groups)


def _entity_match_score(query: str, embed_text: str, label: str) -> float:
    """Topic entity alignment score (retrieval-only, explainable)."""
    if _entity_topic_conflict(query, embed_text, label):
        return 0.0
    q_groups = _entity_group_ids(_retrieval_tokens(query))
    if not q_groups:
        return 0.0
    question_part = _extract_question_from_label(label)
    corpus_raw = " ".join(p for p in (question_part, embed_text or "", label) if p)
    c_groups = _entity_group_ids(_retrieval_tokens(corpus_raw))
    if not c_groups:
        return 0.0
    overlap = q_groups & c_groups
    if not overlap:
        return 0.0
    score = min(0.95, 0.72 + 0.12 * len(overlap))

    q_lower = query.lower()
    corpus_lower = corpus_raw.lower()
    if "emergency" in q_lower and "ambulance" not in q_lower:
        if "ambulance" in corpus_lower or "अॅम्ब्युलन्स" in corpus_lower:
            if "emergency" not in corpus_lower and "आपत्कालीन" not in corpus_lower:
                return min(score, 0.55)
    if "ambulance" in q_lower or "अॅम्ब्युलन्स" in query or "रुग्णवाहिका" in query:
        if "ambulance" not in corpus_lower and "अॅम्ब्युलन्स" not in corpus_lower:
            return min(score, 0.55)
    if ("book" in q_lower or "booking" in q_lower) and "cancel" not in q_lower:
        if "cancel" in corpus_lower or "रद्द" in corpus_lower or "cancellation" in corpus_lower:
            return min(score, 0.55)
    if ("cancel" in q_lower or "cancellation" in q_lower) and "book" not in q_lower:
        if "book" in corpus_lower and "cancel" not in corpus_lower and "रद्द" not in corpus_lower:
            return min(score, 0.55)
    if ("contact" in q_lower or "संपर्क" in query or "क्रमांक" in query) and (
        "number" in q_lower or "phone" in q_lower or "क्रमांक" in query
    ):
        if "ambulance" not in q_lower and "emergency" not in q_lower and "आपत्कालीन" not in query:
            if (
                ("ambulance" in corpus_lower or "अॅम्ब्युलन्स" in corpus_lower)
                and "contact" not in question_part.lower()
                and "संपर्क" not in question_part
            ):
                return min(score, 0.55)
    if ("emergency" in q_lower or "आपत्कालीन" in query) and (
        "contact" in q_lower or "संपर्क" in query
    ):
        if (
            ("ambulance" in corpus_lower or "अॅम्ब्युलन्स" in corpus_lower)
            and "emergency" not in corpus_lower
            and "आपत्कालीन" not in corpus_lower
        ):
            return min(score, 0.55)
    return score


def _language_compatibility_score(query_language: str, kb_language: str) -> float:
    """Score language alignment between query and KB row (retrieval-only)."""
    q = (query_language or "en").lower()
    kb = (kb_language or CANONICAL_KB_LANGUAGE).lower()
    if q == kb:
        return 1.0
    if kb == CANONICAL_KB_LANGUAGE and q in ("en", "hi", "mr", "mixed"):
        return 0.85
    if q == "en" and kb == CANONICAL_KB_LANGUAGE:
        return 0.85
    return 0.70


def _apply_entity_keyword_adjustment(
    score: float, query: str, corpus_raw: str
) -> float:
    """Penalize cross-topic keyword matches; boost aligned topic matches."""
    q_tokens = _retrieval_tokens(query)
    q_groups = _entity_group_ids(q_tokens)
    if not q_groups:
        return score
    c_groups = _entity_group_ids(_retrieval_tokens(corpus_raw))
    if not c_groups:
        return min(score, 0.52)
    if q_groups & c_groups:
        adjusted = min(0.95, score + 0.08)
        q_lower = query.lower()
        c_lower = corpus_raw.lower()
        if "emergency" in q_lower and "ambulance" not in q_lower:
            if "ambulance" in c_lower or "अॅम्ब्युलन्स" in c_lower:
                if "emergency" not in c_lower and "आपत्कालीन" not in c_lower:
                    return min(adjusted, 0.55)
        if "cancel" in q_lower and "appointment" in q_lower:
            if "cancel" in c_lower or "रद्द" in c_lower or "cancellation" in c_lower:
                return min(0.95, adjusted + 0.05)
        return adjusted
    return min(score, 0.52)


def _keyword_score(query: str, embed_text: str, label: str) -> float:
    """Lightweight overlap / exact-match boost using existing KB text fields."""
    normalized_query = _normalize_for_match(query)
    q_lower = normalized_query.lower()
    q_tokens = _expand_tokens(_retrieval_tokens(query))
    if not q_tokens:
        return 0.0

    question_part = _extract_question_from_label(label)
    corpus_raw = " ".join(
        p for p in (question_part, embed_text or "", label) if p
    )
    corpus_tokens = _expand_tokens(_tokenize(corpus_raw))

    if question_part:
        q_part_lower = question_part.lower()
        if q_part_lower == q_lower or q_part_lower in q_lower or q_lower in q_part_lower:
            return _apply_entity_keyword_adjustment(0.95, query, corpus_raw)
        q_part_tokens = _expand_tokens(_tokenize(question_part))
        if q_part_tokens:
            overlap = len(q_tokens & q_part_tokens) / max(len(q_tokens), 1)
            if overlap >= 0.75:
                return _apply_entity_keyword_adjustment(0.85, query, corpus_raw)
            if overlap >= 0.55:
                return _apply_entity_keyword_adjustment(0.72, query, corpus_raw)

    if not corpus_tokens:
        return 0.0
    overlap = len(q_tokens & corpus_tokens) / max(len(q_tokens), 1)
    base = min(0.75, overlap * 0.7)
    return _apply_entity_keyword_adjustment(base, query, corpus_raw)


def _extract_tags_from_embed_text(embed_text: str) -> str:
    """Tags line is the second segment in FAQ embed text (question, tags, answer)."""
    parts = [p.strip() for p in (embed_text or "").split("\n") if p.strip()]
    if len(parts) >= 3:
        return parts[1]
    if len(parts) == 2:
        return parts[1]
    return ""


def _tag_match_score(query: str, embed_text: str) -> float:
    """
    Score alignment between query and FAQ tag phrases (retrieval-only).
    Requires substantive tag phrase overlap; never used without semantic evidence upstream.
    """
    tags_raw = _extract_tags_from_embed_text(embed_text)
    if not tags_raw:
        return 0.0
    q_norm = _normalize_query(query).lower()
    if not q_norm:
        return 0.0
    q_tokens = _expand_tokens(_tokenize(q_norm))
    best = 0.0
    for tag in tags_raw.split(","):
        phrase = tag.strip()
        if len(phrase) < 3:
            continue
        phrase_norm = _normalize_query(phrase).lower()
        if not phrase_norm:
            continue
        if phrase_norm == q_norm or phrase_norm in q_norm or q_norm in phrase_norm:
            best = max(best, 0.95)
            continue
        p_tokens = _expand_tokens(_tokenize(phrase_norm))
        if not p_tokens:
            continue
        overlap = len(q_tokens & p_tokens) / max(len(q_tokens), 1)
        if overlap >= 0.70:
            best = max(best, 0.88)
        elif overlap >= 0.50:
            best = max(best, 0.72)
    return best


def _apply_controlled_tag_boost(
    fused: float, cosine: float, keyword: float, tag: float
) -> float:
    """
    Small boost when semantic + keyword evidence exists and tag phrase aligns.
    Does not bypass weak-semantic cap or push sub-0.90 scores into ANSWER band.
    """
    if cosine < WEAK_SEMANTIC_ANSWER_BLOCK:
        return fused
    if tag < 0.85 or keyword < 0.55:
        return fused
    if fused >= 0.90:
        return fused
    return min(ANSWER_BAND_WITHOUT_SEMANTIC_CAP, fused + min(0.04, tag * 0.04))


class KnowledgeRetriever:
    """Retrieve Top-K knowledge entries for a hospital FAQ question."""

    def __init__(
        self,
        db: AsyncSession,
        embedder: EmbeddingService | None = None,
        store: EmbeddingStore | None = None,
    ):
        self.db = db
        self.embedder = embedder or EmbeddingService()
        self.store = store or EmbeddingStore(db, self.embedder)
        self.faq_repo = HospitalFaqRepository(db)
        self.policy_repo = HospitalPolicyRepository(db)
        self.doc_repo = HospitalVoiceDocumentRepository(db)

    async def diagnose(
        self,
        hospital_id: int,
        query: str,
        language: str = "en",
        top_k: int = 15,
    ) -> RetrievalDiagnostic:
        """Return decomposed retrieval scores for diagnostics (no side effects)."""
        from app.ai.confidence.scorer import ConfidenceScorer
        from app.ai.voice_appointment_assistant.language import detect_language

        original = query or ""
        normalized = _normalize_query(original)
        variants = _retrieval_query_variants(normalized)
        detected = detect_language(original, current=language or "en")
        detected_str = detected.value if hasattr(detected, "value") else str(detected)

        if not normalized:
            return RetrievalDiagnostic(
                original_query=original,
                detected_language=detected_str,
                normalized_query=normalized,
                query_variants=variants,
                candidates=[],
                confidence_action="transfer",
                top_fused_score=0.0,
            )

        scored = await self._score_all_items(hospital_id, normalized, variants, language)
        scorer = ConfidenceScorer()
        top_fused = scored[0]["fused"] if scored else 0.0
        action = scorer.score(top_fused).action.value

        candidates = [
            DiagnosticCandidate(
                source=row["source"],
                id=int(row["id"]),
                rank=idx + 1,
                semantic_score=row["cosine"],
                keyword_score=row["keyword"],
                tag_score=row["tag"],
                entity_score=row["entity"],
                language_score=row["language"],
                authority_bonus=row["authority"],
                exact_match_score=row["exact_match"],
                phrase_match_score=row["phrase_match"],
                fused_score=row["fused"],
                decision_reason=row["decision_reason"],
                normalized_candidate=row["normalized_candidate"],
                candidate_question=row["candidate_question"],
                label=row["label"],
            )
            for idx, row in enumerate(scored[: max(1, top_k)])
        ]

        return RetrievalDiagnostic(
            original_query=original,
            detected_language=detected_str,
            normalized_query=normalized,
            query_variants=variants,
            candidates=candidates,
            confidence_action=action,
            top_fused_score=top_fused,
        )

    async def retrieve(
        self,
        hospital_id: int,
        query: str,
        language: str = "en",
        top_k: int = 5,
    ) -> list[RetrievedChunk]:
        """Embed query and return Top-K chunks sorted by fused score desc."""
        raw_query = _normalize_query(query)
        if not raw_query:
            return []

        variants = _retrieval_query_variants(raw_query)
        try:
            scored_rows = await self._score_all_items(
                hospital_id, raw_query, variants, language
            )
        except EmbeddingUnavailableError:
            raise

        if not scored_rows:
            return []

        chunks = [
            RetrievedChunk(
                source=row["source"],
                id=int(row["id"]),
                text=row["text"],
                label=row["label"],
                score=row["fused"],
                semantic_score=row["cosine"],
                keyword_score=row["keyword"],
                tag_score=row["tag"],
                entity_score=row["entity"],
                language_score=row["language"],
                authority_score=row["authority"],
                exact_match_score=row["exact_match"],
                phrase_match_score=row["phrase_match"],
                decision_reason=row["decision_reason"],
                normalized_candidate=row["normalized_candidate"],
                candidate_question=row["candidate_question"],
            )
            for row in scored_rows
        ]
        return chunks[: max(1, top_k)]

    async def _score_all_items(
        self,
        hospital_id: int,
        normalized_query: str,
        query_variants: list[str],
        language: str,
    ) -> list[dict[str, Any]]:
        """Score all KB items; returns sorted dict rows with decomposed scores."""
        query_vecs: list[list[float]] = []
        for variant in query_variants:
            vec = await self.embedder.embed_text(variant)
            if not vec:
                logger.warning("KnowledgeRetriever: empty query embedding for %r", variant)
                raise EmbeddingUnavailableError("empty query embedding vector")
            query_vecs.append(vec)

        items = await self._load_scoped_kb_items(hospital_id, language)

        scored: list[dict[str, Any]] = []
        score_forms = query_variants or [normalized_query]
        for item in items:
            vec = item.get("embedding") or []
            cosine = max(cosine_similarity(qv, vec) for qv in query_vecs)
            embed_text = item.get("embed_text") or ""
            label = item.get("label") or f"[{item['source']}:{item['id']}]"
            question_part = _extract_question_from_label(label)
            normalized_candidate = _normalize_for_match(question_part)
            keyword = max(
                _keyword_score(form, embed_text, label) for form in score_forms
            )
            tag = max(_tag_match_score(form, embed_text) for form in score_forms)
            entity = max(
                _entity_match_score(form, embed_text, label) for form in score_forms
            )
            exact = max(_exact_match_score(form, label) for form in score_forms)
            phrase = max(
                _phrase_match_score(form, label, embed_text) for form in score_forms
            )
            kb_lang = item.get("language") or language
            lang_score = _language_compatibility_score(language, kb_lang)
            source = item["source"]
            authority = _authority_score(source, is_active=True)
            confidence = compute_retrieval_confidence(
                semantic=cosine,
                keyword=keyword,
                tag=tag,
                entity=entity,
                language=lang_score,
                authority=authority,
                exact_match=exact,
                phrase_match=phrase,
                source=source,
            )
            fused, decision_reason = _apply_sunday_opd_availability_adjustment(
                confidence.fused,
                query=normalized_query,
                label=label,
                embed_text=embed_text,
                decision_reason=confidence.decision_reason,
            )
            scored.append(
                {
                    "source": source,
                    "id": int(item["id"]),
                    "text": item.get("text") or "",
                    "label": label,
                    "cosine": cosine,
                    "keyword": keyword,
                    "tag": tag,
                    "entity": entity,
                    "language": lang_score,
                    "authority": authority,
                    "exact_match": exact,
                    "phrase_match": phrase,
                    "fused": fused,
                    "decision_reason": decision_reason,
                    "normalized_candidate": normalized_candidate,
                    "candidate_question": question_part,
                    "hospital_id": item.get("hospital_id"),
                    "active": True,
                    "deleted": False,
                }
            )

        scored.sort(
            key=lambda r: (
                r["fused"],
                r["exact_match"],
                r["phrase_match"],
                r["entity"],
                r["keyword"],
            ),
            reverse=True,
        )
        return scored

    async def _load_scoped_kb_items(
        self, hospital_id: int, query_language: str
    ) -> list[dict[str, Any]]:
        """
        Load hospital-scoped KB vectors for retrieval.

        Marathi is the canonical FAQ language — always included for en/hi/mixed queries
        so multilingual tags and embeddings remain reachable without translation.
        """
        languages: list[str] = []

        def _add(lang: str) -> None:
            if lang and lang not in languages:
                languages.append(lang)

        _add(query_language or "en")
        if query_language != CANONICAL_KB_LANGUAGE:
            _add(CANONICAL_KB_LANGUAGE)
        if query_language not in (CANONICAL_KB_LANGUAGE, "en"):
            _add("en")

        items: list[dict[str, Any]] = []
        seen: set[tuple[str, int]] = set()
        for lang in languages:
            for item in await self._load_enriched_vectors(hospital_id, lang):
                key = (item["source"], int(item["id"]))
                if key in seen:
                    continue
                items.append(item)
                seen.add(key)
        return items

    async def _load_enriched_vectors(
        self, hospital_id: int, language: str
    ) -> list[dict[str, Any]]:
        kb_lookup = await self._build_kb_lookup(hospital_id, language)
        items = await self.store.list_active_vectors(
            hospital_id, language, kb_lookup=kb_lookup
        )

        # Lazy backfill when KB has rows but embeddings are missing
        if len(items) < len(kb_lookup):
            await self._backfill_missing(hospital_id, language, kb_lookup, items)
            items = await self.store.list_active_vectors(
                hospital_id, language, kb_lookup=kb_lookup
            )

        for item in items:
            ref = f"{item['source']}:{item['id']}"
            meta = kb_lookup.get(ref, {})
            item["embed_text"] = meta.get("embed_text") or ""
            item["label"] = meta.get("label") or item.get("label") or ref
            item["language"] = meta.get("language") or language
        return items

    async def _build_kb_lookup(
        self, hospital_id: int, language: str
    ) -> dict[str, dict[str, Any]]:
        lookup: dict[str, dict[str, Any]] = {}
        faqs = await self.faq_repo.list_for_hospital(hospital_id, language)
        for f in faqs:
            ref = f"faq:{f.id}"
            lookup[ref] = {
                "text": f.answer,
                "label": label_for_entry(
                    "faq", f.id, question=f.question, answer=f.answer
                ),
                "embed_text": build_faq_retrieval_embed_text(
                    f.question,
                    f.tags or "",
                    f.answer,
                ),
                "language": f.language or language,
                "hospital_id": f.hospital_id,
                "source_type": "faq",
                "source_id": f.id,
            }
        policies = await self.policy_repo.list_for_hospital(hospital_id, language)
        for p in policies:
            ref = f"policy:{p.id}"
            lookup[ref] = {
                "text": p.body,
                "label": label_for_entry(
                    "policy",
                    p.id,
                    title=p.title,
                    body=p.body,
                    category=p.category or "",
                ),
                "embed_text": build_embed_text(
                    "policy",
                    title=p.title,
                    category=p.category or "",
                    body=p.body,
                ),
                "language": p.language or language,
                "hospital_id": p.hospital_id,
                "source_type": "policy",
                "source_id": p.id,
            }
        docs = await self.doc_repo.list_for_hospital(hospital_id, language)
        for d in docs:
            ref = f"document:{d.id}"
            lookup[ref] = {
                "text": d.content,
                "label": label_for_entry(
                    "document", d.id, title=d.title, content=d.content
                ),
                "embed_text": build_embed_text(
                    "document", title=d.title, content=d.content
                ),
                "language": d.language or language,
                "hospital_id": d.hospital_id,
                "source_type": "document",
                "source_id": d.id,
            }
        return lookup

    async def _backfill_missing(
        self,
        hospital_id: int,
        language: str,
        kb_lookup: dict[str, dict[str, Any]],
        existing: list[dict[str, Any]],
    ) -> None:
        have = {(i["source"], i["id"]) for i in existing}
        for ref, meta in kb_lookup.items():
            key = (meta["source_type"], meta["source_id"])
            if key in have:
                continue
            try:
                await self.store.upsert_kb_entry(
                    hospital_id=hospital_id,
                    source_type=meta["source_type"],
                    source_id=meta["source_id"],
                    language=meta.get("language") or language,
                    embed_text=meta["embed_text"],
                    answer_text=meta["text"],
                    label=meta["label"],
                )
            except Exception as exc:
                logger.warning("Lazy embed backfill failed for %s: %s", ref, exc)
