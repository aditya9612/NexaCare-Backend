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
    FAQ DB → Policies → Documents → OpenAI (low confidence → transfer).
    Never invent fees, timings, or doctor information.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.faq_repo = HospitalFaqRepository(db)
        self.policy_repo = HospitalPolicyRepository(db)
        self.doc_repo = HospitalVoiceDocumentRepository(db)

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

        # Try English corpus if language-specific miss
        if language != "en":
            en_snap = await self._load_snapshot(hospital_id, "en")
            hit = self._keyword_search(question, en_snap)
            if hit:
                return hit

        ai = await self._openai_fallback(question, language, snapshot)
        return ai

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

    def _tokenize(self, text: str) -> set[str]:
        tokens = re.findall(r"[a-zA-Z\u0900-\u097F]{3,}", (text or "").lower())
        return set(tokens)

    def _score(self, query_tokens: set[str], corpus: str) -> float:
        if not query_tokens:
            return 0.0
        corpus_tokens = self._tokenize(corpus)
        if not corpus_tokens:
            return 0.0
        overlap = query_tokens & corpus_tokens
        return len(overlap) / max(len(query_tokens), 1)

    def _keyword_search(self, question: str, snapshot: dict) -> Optional[FaqAnswer]:
        q_tokens = self._tokenize(question)
        best: Optional[FaqAnswer] = None
        best_score = 0.0

        for faq in snapshot.get("faqs") or []:
            corpus = f"{faq.get('question', '')} {faq.get('tags', '')}"
            score = self._score(q_tokens, corpus)
            if score > best_score and score >= 0.35:
                best_score = score
                best = FaqAnswer(
                    found=True,
                    answer=faq["answer"],
                    source="faq",
                    confidence=min(1.0, score),
                    faq_hit=True,
                )

        for policy in snapshot.get("policies") or []:
            corpus = f"{policy.get('title', '')} {policy.get('body', '')} {policy.get('category', '')}"
            score = self._score(q_tokens, corpus)
            if score > best_score and score >= 0.4:
                best_score = score
                best = FaqAnswer(
                    found=True,
                    answer=policy["body"][:500],
                    source="policy",
                    confidence=min(1.0, score),
                    faq_hit=True,
                )

        for doc in snapshot.get("documents") or []:
            corpus = f"{doc.get('title', '')} {doc.get('content', '')}"
            score = self._score(q_tokens, corpus)
            if score > best_score and score >= 0.4:
                best_score = score
                best = FaqAnswer(
                    found=True,
                    answer=doc["content"][:500],
                    source="document",
                    confidence=min(1.0, score),
                    faq_hit=True,
                )

        return best

    async def _openai_fallback(
        self, question: str, language: str, snapshot: dict
    ) -> FaqAnswer:
        threshold = settings.VOICE_AI_CONFIDENCE_THRESHOLD
        context_bits = []
        for faq in (snapshot.get("faqs") or [])[:20]:
            context_bits.append(f"Q: {faq['question']}\nA: {faq['answer']}")
        for policy in (snapshot.get("policies") or [])[:10]:
            context_bits.append(f"Policy {policy['title']}: {policy['body'][:300]}")
        context = "\n\n".join(context_bits) if context_bits else "No hospital knowledge base entries."

        if not settings.OPENAI_API_KEY:
            return FaqAnswer(
                found=False,
                answer=TRANSFER_PHRASES.get(language, TRANSFER_PHRASES["en"]),
                source="transfer",
                should_transfer=True,
                ai_fallback=True,
                confidence=0.0,
            )

        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            system = (
                "You are a hospital voice FAQ assistant for an Indian hospital. "
                "Answer ONLY using the provided hospital knowledge base. "
                "Never invent fees, timings, doctor names, or medical advice. "
                "Never diagnose, prescribe medicine, or suggest surgery. "
                "If the answer is not clearly in the knowledge base, reply exactly: "
                "NO_ANSWER. "
                "Respond in the patient's language code: " + language
            )
            user = f"Knowledge base:\n{context}\n\nPatient question: {question}"
            response = await client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.1,
                max_tokens=250,
            )
            text = (response.choices[0].message.content or "").strip()
            if not text or "NO_ANSWER" in text.upper() or len(text) < 8:
                return FaqAnswer(
                    found=False,
                    answer=TRANSFER_PHRASES.get(language, TRANSFER_PHRASES["en"]),
                    source="transfer",
                    should_transfer=True,
                    ai_fallback=True,
                    confidence=0.2,
                )
            # Heuristic confidence: presence of grounded context tokens
            conf = 0.75 if context_bits else 0.4
            if conf < threshold:
                return FaqAnswer(
                    found=False,
                    answer=TRANSFER_PHRASES.get(language, TRANSFER_PHRASES["en"]),
                    source="transfer",
                    should_transfer=True,
                    ai_fallback=True,
                    confidence=conf,
                )
            return FaqAnswer(
                found=True,
                answer=text,
                source="openai",
                confidence=conf,
                ai_fallback=True,
            )
        except Exception as exc:
            logger.warning("FAQ OpenAI fallback failed: %s", exc)
            return FaqAnswer(
                found=False,
                answer=TRANSFER_PHRASES.get(language, TRANSFER_PHRASES["en"]),
                source="transfer",
                should_transfer=True,
                ai_fallback=True,
                confidence=0.0,
            )

    async def invalidate_cache(self, hospital_id: int) -> None:
        for lang in ("en", "hi", "mr"):
            from app.utils.redis_service import cache_delete

            await cache_delete(self._cache_key(hospital_id, lang))
