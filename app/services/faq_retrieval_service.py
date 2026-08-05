import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logger import logger
from app.repositories.hospital_voice_repository import (
    HospitalFaqRepository,
    HospitalPolicyRepository,
    HospitalVoiceDocumentRepository,
)
from app.services.medical_safety_guard import MedicalSafetyGuard
from app.utils.redis_service import cache_get, cache_set

_KEYWORD_THRESHOLD = 0.35
_TYPE_PRIORITY = {"faq": 3, "policy": 2, "document": 1}
_MATCH_PREFIX = re.compile(
    r"^MATCH:(faq|policy|document):(\d+)\s*$",
    re.IGNORECASE,
)

# Common hospital FAQ terms across English, Hindi, and Marathi.
_SYNONYM_GROUPS = (
    {"hours", "hour", "timing", "timings", "time", "open", "opening", "schedule", "समय", "घंटे", "वेळ", "उघडे", "खुला"},
    {"location", "address", "place", "where", "पता", "स्थान", "पत्ता", "कहाँ", "कुठे"},
    {"contact", "phone", "call", "number", "संपर्क", "फोन", "नंबर"},
    {"fee", "fees", "cost", "charge", "price", "शुल्क", "कीमत"},
    {"parking", "park", "पार्किंग"},
    {"insurance", "बीमा", "विमा"},
)

_QUERY_FILLERS = frozenset(
    {
        "the", "a", "an", "is", "are", "was", "were", "what", "when", "where", "how",
        "please", "tell", "about", "your", "you", "can", "could", "would", "do", "does",
        "क्या", "कृपया", "मुझे", "बताइए", "बताओ", "आप", "है", "हैं", "का", "की", "के",
        "मला", "सांगा", "कृपया", "आहे", "तुमचा", "तुमची",
    }
)


@dataclass
class FaqAnswer:
    found: bool
    answer: str = ""
    source: str = ""  # faq | policy | document | openai | none | transfer
    confidence: float = 0.0
    faq_hit: bool = False
    ai_fallback: bool = False
    should_transfer: bool = False


TRANSFER_PHRASES = {
    "en": "I could not find a reliable answer. Let me transfer you to reception.",
    "hi": "मुझे विश्वसनीय उत्तर नहीं मिला। मैं आपको रिसेप्शन से जोड़ती हूँ।",
    "mr": "मला विश्वासार्ह उत्तर सापडले नाही. मी तुम्हाला रिसेप्शनशी जोडते.",
}


class FaqRetrievalService:
    """
    Retrieval-first FAQ:
    FAQ DB → Policies → Documents → OpenAI KB selection (low confidence → transfer).
    Never invent fees, timings, or doctor information.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.faq_repo = HospitalFaqRepository(db)
        self.policy_repo = HospitalPolicyRepository(db)
        self.doc_repo = HospitalVoiceDocumentRepository(db)
        self._synonym_lookup = self._build_synonym_lookup()

    @staticmethod
    def _build_synonym_lookup() -> dict[str, set[str]]:
        lookup: dict[str, set[str]] = {}
        for group in _SYNONYM_GROUPS:
            for token in group:
                lookup[token] = group
        return lookup

    def _cache_key(self, hospital_id: int, language: str) -> str:
        return f"voice:faq:{hospital_id}:{language}"

    async def answer(
        self,
        hospital_id: int,
        question: str,
        language: str = "en",
    ) -> FaqAnswer:
        safety = MedicalSafetyGuard.check(question, language)
        if safety.is_medical_advice:
            return FaqAnswer(
                found=False,
                answer=safety.refusal_message,
                source="transfer",
                should_transfer=True,
                confidence=1.0,
            )

        snapshot = await self._load_snapshot(hospital_id, language)
        hit = self._keyword_search(question, snapshot)
        if hit:
            return hit

        en_snap = None
        if language != "en":
            en_snap = await self._load_snapshot(hospital_id, "en")
            hit = self._keyword_search(question, en_snap)
            if hit:
                return hit

        merged = self._merge_snapshots(snapshot, en_snap)
        return await self._openai_fallback(question, language, merged)

    async def _load_snapshot(self, hospital_id: int, language: str) -> dict:
        key = self._cache_key(hospital_id, language)
        cached = await cache_get(key)
        if cached:
            return cached

        faqs = await self.faq_repo.list_for_hospital(hospital_id, language)
        policies = await self.policy_repo.list_for_hospital(hospital_id, language)
        docs = await self.doc_repo.list_for_hospital(hospital_id, language)
        snapshot = {
            "faqs": [
                {"id": f.id, "question": f.question, "answer": f.answer, "tags": f.tags or ""}
                for f in faqs
            ],
            "policies": [
                {"id": p.id, "title": p.title, "body": p.body, "category": p.category or ""}
                for p in policies
            ],
            "documents": [
                {"id": d.id, "title": d.title, "content": d.content}
                for d in docs
            ],
        }
        await cache_set(key, snapshot, ttl=settings.VOICE_FAQ_CACHE_TTL_SECONDS)
        return snapshot

    def _normalize_text(self, text: str) -> str:
        lowered = (text or "").lower()
        lowered = re.sub(r"[^\w\s\u0900-\u097F]", " ", lowered)
        return re.sub(r"\s+", " ", lowered).strip()

    def _tokenize(self, text: str) -> set[str]:
        normalized = self._normalize_text(text)
        tokens = re.findall(r"[a-zA-Z\u0900-\u097F]{2,}", normalized)
        return {t for t in tokens if t not in _QUERY_FILLERS}

    def _expand_synonyms(self, tokens: set[str]) -> set[str]:
        expanded = set(tokens)
        for token in tokens:
            group = self._synonym_lookup.get(token)
            if group:
                expanded |= group
        return expanded

    def _field_score(
        self,
        raw_tokens: set[str],
        expanded_tokens: set[str],
        fields: dict[str, str],
        weights: dict[str, float],
    ) -> float:
        if not raw_tokens:
            return 0.0
        total_weight = sum(weights.values())
        if total_weight <= 0:
            return 0.0
        score = 0.0
        for field, weight in weights.items():
            field_tokens = self._tokenize(fields.get(field, ""))
            if not field_tokens:
                continue
            overlap = len(expanded_tokens & field_tokens) / max(len(raw_tokens), 1)
            score += overlap * weight
        return score / total_weight

    def _is_better_match(self, score: float, source: str, best_score: float, best_source: str) -> bool:
        if score > best_score:
            return True
        if score < best_score:
            return False
        return _TYPE_PRIORITY.get(source, 0) > _TYPE_PRIORITY.get(best_source, 0)

    def _keyword_search(self, question: str, snapshot: dict) -> Optional[FaqAnswer]:
        raw_tokens = self._tokenize(question)
        q_tokens = self._expand_synonyms(raw_tokens)
        best: Optional[FaqAnswer] = None
        best_score = 0.0
        best_source = ""

        for faq in snapshot.get("faqs") or []:
            score = self._field_score(
                raw_tokens,
                q_tokens,
                {
                    "question": faq.get("question", ""),
                    "tags": faq.get("tags", ""),
                    "answer": faq.get("answer", ""),
                },
                {"question": 1.0, "tags": 0.8, "answer": 0.6},
            )
            if score >= _KEYWORD_THRESHOLD and self._is_better_match(score, "faq", best_score, best_source):
                best_score = score
                best_source = "faq"
                best = FaqAnswer(
                    found=True,
                    answer=faq["answer"],
                    source="faq",
                    confidence=min(1.0, max(0.55, score)),
                    faq_hit=True,
                )

        for policy in snapshot.get("policies") or []:
            score = self._field_score(
                raw_tokens,
                q_tokens,
                {
                    "title": policy.get("title", ""),
                    "category": policy.get("category", ""),
                    "body": policy.get("body", ""),
                },
                {"title": 1.0, "category": 0.8, "body": 0.5},
            )
            if score >= _KEYWORD_THRESHOLD and self._is_better_match(score, "policy", best_score, best_source):
                best_score = score
                best_source = "policy"
                best = FaqAnswer(
                    found=True,
                    answer=policy["body"],
                    source="policy",
                    confidence=min(1.0, max(0.55, score)),
                    faq_hit=True,
                )

        for doc in snapshot.get("documents") or []:
            score = self._field_score(
                raw_tokens,
                q_tokens,
                {
                    "title": doc.get("title", ""),
                    "content": doc.get("content", ""),
                },
                {"title": 1.0, "content": 0.6},
            )
            if score >= _KEYWORD_THRESHOLD and self._is_better_match(score, "document", best_score, best_source):
                best_score = score
                best_source = "document"
                best = FaqAnswer(
                    found=True,
                    answer=doc["content"],
                    source="document",
                    confidence=min(1.0, max(0.55, score)),
                    faq_hit=True,
                )

        return best

    @staticmethod
    def _merge_snapshots(primary: dict, secondary: dict | None) -> dict:
        if not secondary:
            return primary

        def _merge_list(key: str) -> list:
            seen = {item["id"] for item in primary.get(key) or []}
            merged = list(primary.get(key) or [])
            for item in secondary.get(key) or []:
                if item["id"] not in seen:
                    merged.append(item)
                    seen.add(item["id"])
            return merged

        return {
            "faqs": _merge_list("faqs"),
            "policies": _merge_list("policies"),
            "documents": _merge_list("documents"),
        }

    def _kb_entries(self, snapshot: dict) -> list[dict]:
        entries: list[dict] = []
        for faq in snapshot.get("faqs") or []:
            entries.append(
                {
                    "ref": f"faq:{faq['id']}",
                    "source": "faq",
                    "id": faq["id"],
                    "text": faq["answer"],
                    "label": f"[faq:{faq['id']}] Q: {faq['question']}\nA: {faq['answer']}",
                }
            )
        for policy in snapshot.get("policies") or []:
            entries.append(
                {
                    "ref": f"policy:{policy['id']}",
                    "source": "policy",
                    "id": policy["id"],
                    "text": policy["body"],
                    "label": (
                        f"[policy:{policy['id']}] Title: {policy['title']}\n"
                        f"Category: {policy.get('category', '')}\n"
                        f"Body: {policy['body']}"
                    ),
                }
            )
        for doc in snapshot.get("documents") or []:
            entries.append(
                {
                    "ref": f"document:{doc['id']}",
                    "source": "document",
                    "id": doc["id"],
                    "text": doc["content"],
                    "label": f"[document:{doc['id']}] Title: {doc['title']}\nContent: {doc['content']}",
                }
            )
        return entries

    def _lookup_kb_entry(self, snapshot: dict, source: str, entry_id: int) -> Optional[dict]:
        key = {"faq": "faqs", "policy": "policies", "document": "documents"}.get(source)
        if not key:
            return None
        for item in snapshot.get(key) or []:
            if item["id"] == entry_id:
                if source == "faq":
                    return {"source": "faq", "text": item["answer"]}
                if source == "policy":
                    return {"source": "policy", "text": item["body"]}
                return {"source": "document", "text": item["content"]}
        return None

    def _ground_to_kb(self, text: str, snapshot: dict) -> Optional[tuple[str, str, float]]:
        normalized = self._normalize_text(text)
        if not normalized:
            return None

        best: Optional[tuple[str, str, float]] = None
        for entry in self._kb_entries(snapshot):
            candidate = self._normalize_text(entry["text"])
            if not candidate:
                continue
            if normalized == candidate or normalized in candidate or candidate in normalized:
                return entry["source"], entry["text"], 0.9
            overlap = len(self._tokenize(text) & self._tokenize(entry["text"]))
            if overlap == 0:
                continue
            score = overlap / max(len(self._tokenize(text)), 1)
            if score >= settings.VOICE_AI_CONFIDENCE_THRESHOLD and (
                best is None or score > best[2]
            ):
                best = (entry["source"], entry["text"], score)

        return best

    def _transfer_answer(self, language: str, confidence: float = 0.0) -> FaqAnswer:
        return FaqAnswer(
            found=False,
            answer=TRANSFER_PHRASES.get(language, TRANSFER_PHRASES["en"]),
            source="transfer",
            should_transfer=True,
            ai_fallback=True,
            confidence=confidence,
        )

    async def _openai_fallback(
        self, question: str, language: str, snapshot: dict
    ) -> FaqAnswer:
        threshold = settings.VOICE_AI_CONFIDENCE_THRESHOLD
        entries = self._kb_entries(snapshot)

        if not entries:
            return self._transfer_answer(language, confidence=0.0)

        if not settings.OPENAI_API_KEY:
            return self._transfer_answer(language, confidence=0.0)

        catalog = "\n\n".join(entry["label"] for entry in entries[:40])
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            system = (
                "You are a hospital voice FAQ selector for an Indian hospital. "
                "Choose exactly one knowledge-base entry that answers the patient question. "
                "Never invent information. Never diagnose or prescribe. "
                "Reply with ONLY one of these formats:\n"
                "MATCH:faq:<id>\n"
                "MATCH:policy:<id>\n"
                "MATCH:document:<id>\n"
                "NO_ANSWER\n"
                "Do not include any other text."
            )
            user = f"Knowledge base:\n{catalog}\n\nPatient question: {question}"
            response = await client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.0,
                max_tokens=40,
            )
            text = (response.choices[0].message.content or "").strip()
            if text.upper() == "NO_ANSWER":
                return self._transfer_answer(language, confidence=0.2)

            match = _MATCH_PREFIX.match(text)
            if match:
                source = match.group(1).lower()
                entry_id = int(match.group(2))
                resolved = self._lookup_kb_entry(snapshot, source, entry_id)
                if resolved:
                    return FaqAnswer(
                        found=True,
                        answer=resolved["text"],
                        source=resolved["source"],
                        confidence=0.85,
                        ai_fallback=True,
                    )
                return self._transfer_answer(language, confidence=0.2)

            grounded = self._ground_to_kb(text, snapshot)
            if grounded:
                source, answer_text, conf = grounded
                if conf >= threshold:
                    return FaqAnswer(
                        found=True,
                        answer=answer_text,
                        source=source,
                        confidence=conf,
                        ai_fallback=True,
                    )

            return self._transfer_answer(language, confidence=0.2)
        except Exception as exc:
            logger.warning("FAQ OpenAI fallback failed: %s", exc)
            return self._transfer_answer(language, confidence=0.0)

    async def invalidate_cache(self, hospital_id: int) -> None:
        for lang in ("en", "hi", "mr"):
            from app.utils.redis_service import cache_delete

            await cache_delete(self._cache_key(hospital_id, lang))
