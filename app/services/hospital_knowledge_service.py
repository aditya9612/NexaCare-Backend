from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundException
from app.models.hospital_voice_model import HospitalFaq, HospitalPolicy, HospitalVoiceDocument
from app.repositories.hospital_voice_repository import (
    HospitalFaqRepository,
    HospitalPolicyRepository,
    HospitalVoiceDocumentRepository,
)
from app.schemas.hospital_voice_schema import (
    HospitalFaqCreate,
    HospitalFaqResponse,
    HospitalFaqUpdate,
    HospitalPolicyCreate,
    HospitalPolicyResponse,
    HospitalPolicyUpdate,
    HospitalVoiceDocumentCreate,
    HospitalVoiceDocumentResponse,
    HospitalVoiceDocumentUpdate,
)
from app.services.canonical_faq_specs import CANONICAL_TOPICS, build_canonical_faq_specs
from app.services.faq_retrieval_service import FaqRetrievalService
from app.services.knowledge_embedding_sync import (
    deactivate_kb_embedding,
    sync_document_embedding,
    sync_faq_embedding,
    sync_policy_embedding,
)
from app.utils.helpers import utc_now


class HospitalKnowledgeService:
    """Admin CRUD for FAQ / policies / documents used by voice retrieval."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.faq_repo = HospitalFaqRepository(db)
        self.policy_repo = HospitalPolicyRepository(db)
        self.doc_repo = HospitalVoiceDocumentRepository(db)

    async def create_faq(self, data: HospitalFaqCreate) -> HospitalFaqResponse:
        faq = HospitalFaq(**data.model_dump())
        faq = await self.faq_repo.create(faq)
        await sync_faq_embedding(self.db, faq)
        await FaqRetrievalService(self.db).invalidate_cache(data.hospital_id)
        return HospitalFaqResponse.model_validate(faq)

    async def get_faq(self, faq_id: int) -> HospitalFaqResponse:
        faq = await self.faq_repo.get_by_id(faq_id)
        if not faq:
            raise NotFoundException("FAQ not found")
        return HospitalFaqResponse.model_validate(faq)

    async def update_faq(self, faq_id: int, data: HospitalFaqUpdate) -> HospitalFaqResponse:
        faq = await self.faq_repo.get_by_id(faq_id)
        if not faq:
            raise NotFoundException("FAQ not found")
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(faq, k, v)
        faq = await self.faq_repo.update(faq)
        await sync_faq_embedding(self.db, faq)
        await FaqRetrievalService(self.db).invalidate_cache(faq.hospital_id)
        return HospitalFaqResponse.model_validate(faq)

    async def list_faqs(self, hospital_id: int, language: str | None = None) -> list[HospitalFaqResponse]:
        items = await self.faq_repo.list_for_hospital(hospital_id, language)
        return [HospitalFaqResponse.model_validate(i) for i in items]

    async def delete_faq(self, faq_id: int) -> None:
        faq = await self.faq_repo.get_by_id(faq_id)
        if not faq:
            raise NotFoundException("FAQ not found")
        faq.is_deleted = True
        faq.deleted_at = utc_now()
        await self.faq_repo.update(faq)
        await deactivate_kb_embedding(self.db, "faq", faq.id, faq.hospital_id)
        await FaqRetrievalService(self.db).invalidate_cache(faq.hospital_id)

    async def create_policy(self, data: HospitalPolicyCreate) -> HospitalPolicyResponse:
        policy = HospitalPolicy(**data.model_dump())
        policy = await self.policy_repo.create(policy)
        await sync_policy_embedding(self.db, policy)
        await FaqRetrievalService(self.db).invalidate_cache(data.hospital_id)
        return HospitalPolicyResponse.model_validate(policy)

    async def get_policy(self, policy_id: int) -> HospitalPolicyResponse:
        policy = await self.policy_repo.get_by_id(policy_id)
        if not policy:
            raise NotFoundException("Policy not found")
        return HospitalPolicyResponse.model_validate(policy)

    async def update_policy(self, policy_id: int, data: HospitalPolicyUpdate) -> HospitalPolicyResponse:
        policy = await self.policy_repo.get_by_id(policy_id)
        if not policy:
            raise NotFoundException("Policy not found")
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(policy, k, v)
        policy = await self.policy_repo.update(policy)
        await sync_policy_embedding(self.db, policy)
        await FaqRetrievalService(self.db).invalidate_cache(policy.hospital_id)
        return HospitalPolicyResponse.model_validate(policy)

    async def list_policies(
        self, hospital_id: int, language: str | None = None
    ) -> list[HospitalPolicyResponse]:
        items = await self.policy_repo.list_for_hospital(hospital_id, language)
        return [HospitalPolicyResponse.model_validate(i) for i in items]

    async def create_document(
        self, data: HospitalVoiceDocumentCreate
    ) -> HospitalVoiceDocumentResponse:
        doc = HospitalVoiceDocument(**data.model_dump())
        doc = await self.doc_repo.create(doc)
        await sync_document_embedding(self.db, doc)
        await FaqRetrievalService(self.db).invalidate_cache(data.hospital_id)
        return HospitalVoiceDocumentResponse.model_validate(doc)

    async def get_document(self, doc_id: int) -> HospitalVoiceDocumentResponse:
        doc = await self.doc_repo.get_by_id(doc_id)
        if not doc:
            raise NotFoundException("Document not found")
        return HospitalVoiceDocumentResponse.model_validate(doc)

    async def update_document(
        self, doc_id: int, data: HospitalVoiceDocumentUpdate
    ) -> HospitalVoiceDocumentResponse:
        doc = await self.doc_repo.get_by_id(doc_id)
        if not doc:
            raise NotFoundException("Document not found")
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(doc, k, v)
        doc = await self.doc_repo.update(doc)
        await sync_document_embedding(self.db, doc)
        await FaqRetrievalService(self.db).invalidate_cache(doc.hospital_id)
        return HospitalVoiceDocumentResponse.model_validate(doc)

    async def list_documents(
        self, hospital_id: int, language: str | None = None
    ) -> list[HospitalVoiceDocumentResponse]:
        items = await self.doc_repo.list_for_hospital(hospital_id, language)
        return [HospitalVoiceDocumentResponse.model_validate(i) for i in items]

    async def seed_from_env(self, hospital_id: int) -> int:
        """Seed basic FAQ from HOSPITAL_* env settings if none exist."""
        existing = await self.faq_repo.list_for_hospital(hospital_id, "en")
        if existing:
            return 0
        seeds = [
            HospitalFaqCreate(
                hospital_id=hospital_id,
                question="What are the hospital visiting hours?",
                answer=f"Our hospital hours are {settings.HOSPITAL_HOURS}.",
                language="en",
                tags="hours,timing,open",
            ),
            HospitalFaqCreate(
                hospital_id=hospital_id,
                question="Where is the hospital located?",
                answer=f"We are located at {settings.HOSPITAL_LOCATION}.",
                language="en",
                tags="location,address",
            ),
            HospitalFaqCreate(
                hospital_id=hospital_id,
                question="How can I contact the hospital?",
                answer=f"You can contact us at {settings.HOSPITAL_CONTACT}.",
                language="en",
                tags="contact,phone",
            ),
        ]
        for item in seeds:
            await self.create_faq(item)
        return len(seeds)

    async def ensure_priority_faqs(self, hospital_id: int) -> int:
        """Create missing canonical hospital FAQs (one per topic, multilingual tags)."""
        existing = await self.faq_repo.list_for_hospital(hospital_id, language=None)
        covered_topics: set[str] = set()
        for faq in existing:
            if faq.tags:
                for tag in faq.tags.split(","):
                    key = tag.strip().lower()
                    if key in CANONICAL_TOPICS:
                        covered_topics.add(key)
            q_lower = (faq.question or "").lower()
            for topic in CANONICAL_TOPICS:
                if topic in q_lower or topic in (faq.tags or "").lower():
                    covered_topics.add(topic)

        created = 0
        for spec in build_canonical_faq_specs():
            if spec["topic"] in covered_topics:
                continue
            await self.create_faq(
                HospitalFaqCreate(
                    hospital_id=hospital_id,
                    question=spec["question"],
                    answer=spec["answer"],
                    language=spec["language"],
                    tags=spec["tags"],
                )
            )
            covered_topics.add(spec["topic"])
            created += 1
        return created
