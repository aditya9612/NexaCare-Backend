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

SOURCE_AUTHORITY_BONUS = {"faq": 0.02, "policy": 0.01, "document": 0.0}

# Canonical hospital FAQs are stored under this language; always merged for retrieval.
CANONICAL_KB_LANGUAGE = "mr"

SEMANTIC_FUSION_WEIGHT = 0.65
KEYWORD_FUSION_WEIGHT = 0.35
WEAK_SEMANTIC_ANSWER_BLOCK = 0.55
ANSWER_BAND_WITHOUT_SEMANTIC_CAP = 0.89

# Retrieval-only token equivalence (never changes KB answers).
TOKEN_EQUIVALENCE_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"opd", "opd", "ओपीडी", "ओपडी", "ओपीडीची"}),
    frozenset({"timing", "time", "hours", "hour", "vel", "वेळ", "vajta", "vajey", "vajet", "वाजता", "वाजे", "vajeyparyant", "वाजेपर्यंत"}),
    frozenset({"kiti", "किती", "when"}),
    frozenset({"kay", "काय", "what"}),
    frozenset({"aahe", "aahet", "ahe", "ahet", "आहे", "आहेत", "ka", "का"}),
    frozenset({"suru", "start", "starts", "hote", "hota", "hot", "hotat", "hot", "open", "सुरू", "होते", "होता", "होत", "उघड", "उघडे", "asate", "असते", "aste", "अस्त"}),
    frozenset({"insurance", "cashless", "इन्शुरन्स", "कॅशलेस", "cashless"}),
    frozenset({"ambulance", "अॅम्ब्युलन्स", "number", "नंबर", "contact", "phone"}),
    frozenset({"hospital", "रुग्णालय", "rugnalay", "aspatal", "अस्पताल"}),
    frozenset({"parking", "पार्किंग", "available", "availble", "उपलब्ध"}),
    frozenset({"doctor", "dr", "डॉक्टर", "udya", "उद्या"}),
    frozenset({"billing", "बिलिंग", "counter", "close", "closed", "band", "बंद"}),
    frozenset({"appointment", "अपॉइंटमेंट", "cancel", "cancellation", "रद्द"}),
    frozenset({"sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "रविवार", "सोमवार"}),
    frozenset({"location", "address", "patta", "पत्ता", "kuthe", "कुठे"}),
    frozenset({"visiting", "visit", "visitor", "visitors", "भेट"}),
    frozenset({"ravivar", "ravivari", "रविवार", "sunday"}),
    frozenset({"appointment", "अपॉइंटमेंट", "booking", "book"}),
    frozenset({"cancellation", "cancel", "रद्द"}),
    frozenset({"pharmacy", "फार्मसी", "medical", "store"}),
    frozenset({"laboratory", "lab", "लॅब", "blood", "test"}),
    frozenset({"contact", "phone", "number", "संपर्क"}),
)

# Distinct hospital topics for keyword entity alignment (retrieval-only).
ENTITY_SCORING_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"opd", "ओपीडी", "ओपडी", "ओपीडीची"}),
    frozenset({"parking", "पार्किंग"}),
    frozenset({"insurance", "cashless", "इन्शुरन्स", "कॅशलेस"}),
    frozenset({"visiting", "visit", "visitor", "visitors", "भेट", "timings", "open"}),
    frozenset({"emergency", "आपत्कालीन", "emergency", "dept", "department", "विभाग"}),
    frozenset({"ambulance", "अॅम्ब्युलन्स", "रुग्णवाहिका", "एम्बुलेंस"}),
    frozenset({"doctor", "dr", "डॉक्टर"}),
    frozenset({"billing", "बिलिंग", "counter"}),
    frozenset({"appointment", "अपॉइंटमेंट", "booking", "book"}),
    frozenset({"cancellation", "cancel", "रद्द"}),
    frozenset({"location", "address", "patta", "पत्ता", "kuthe", "कुठे"}),
    frozenset({"contact", "phone", "number", "संपर्क", "क्रमांक"}),
    frozenset({"pharmacy", "फार्मसी", "medical", "store", "medicine", "shop"}),
    frozenset({"laboratory", "lab", "लॅब", "blood", "test", "x-ray", "mri"}),
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
    fused_score: float
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
    """Whitespace cleanup + retrieval-only Roman Marathi → Devanagari (never generates facts)."""
    collapsed = re.sub(r"\s+", " ", (text or "").strip())
    if not collapsed:
        return collapsed
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


def fuse_retrieval_score(cosine: float, keyword: float, source: str = "faq") -> float:
    """
    Hybrid score: semantic primary, keyword secondary.
    Keyword overlap alone cannot reach the answer confidence band.
    """
    authority = SOURCE_AUTHORITY_BONUS.get(source, 0.0)
    fused = (
        SEMANTIC_FUSION_WEIGHT * max(0.0, cosine)
        + KEYWORD_FUSION_WEIGHT * max(0.0, keyword)
        + authority
    )
    if cosine < WEAK_SEMANTIC_ANSWER_BLOCK:
        fused = min(fused, ANSWER_BAND_WITHOUT_SEMANTIC_CAP)
    return fused


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


def _entity_group_ids(tokens: set[str]) -> set[int]:
    """Detect topic entities without expanding generic tokens like contact/number."""
    expanded = set(tokens)
    for group in ENTITY_SCORING_GROUPS:
        if expanded & group:
            expanded |= {t for t in group if len(t) > 1}
    return {idx for idx, group in enumerate(ENTITY_SCORING_GROUPS) if expanded & group}


def _entity_match_score(query: str, embed_text: str, label: str) -> float:
    """Topic entity alignment score (retrieval-only, explainable)."""
    q_groups = _entity_group_ids(_tokenize(query))
    if not q_groups:
        return 0.0
    question_part = _extract_question_from_label(label)
    corpus_raw = " ".join(p for p in (question_part, embed_text or "", label) if p)
    c_groups = _entity_group_ids(_tokenize(corpus_raw))
    if not c_groups:
        return 0.0
    overlap = q_groups & c_groups
    if not overlap:
        return 0.0
    return min(0.95, 0.72 + 0.12 * len(overlap))


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
    q_tokens = _tokenize(query)
    q_groups = _entity_group_ids(q_tokens)
    if not q_groups:
        return score
    c_groups = _entity_group_ids(_tokenize(corpus_raw))
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
    q_lower = query.lower()
    q_tokens = _expand_tokens(_tokenize(query))
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
                fused_score=row["fused"],
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
        for item in items:
            vec = item.get("embedding") or []
            cosine = max(cosine_similarity(qv, vec) for qv in query_vecs)
            embed_text = item.get("embed_text") or ""
            keyword = _keyword_score(
                normalized_query,
                embed_text,
                item.get("label") or "",
            )
            tag = _tag_match_score(normalized_query, embed_text)
            entity = _entity_match_score(
                normalized_query, embed_text, item.get("label") or ""
            )
            kb_lang = item.get("language") or language
            lang_score = _language_compatibility_score(language, kb_lang)
            source = item["source"]
            authority = SOURCE_AUTHORITY_BONUS.get(source, 0.0)
            fused = fuse_retrieval_score(cosine, keyword, source)
            fused = _apply_controlled_tag_boost(fused, cosine, keyword, tag)
            if entity >= 0.84 and keyword >= 0.55:
                fused = min(0.95, fused + 0.03)
            scored.append(
                {
                    "source": source,
                    "id": int(item["id"]),
                    "text": item.get("text") or "",
                    "label": item.get("label") or f"[{source}:{item['id']}]",
                    "cosine": cosine,
                    "keyword": keyword,
                    "tag": tag,
                    "entity": entity,
                    "language": lang_score,
                    "authority": authority,
                    "fused": fused,
                }
            )

        scored.sort(key=lambda r: (r["fused"], r["entity"], r["keyword"]), reverse=True)
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
