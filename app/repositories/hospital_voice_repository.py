from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hospital_voice_model import (
    HospitalFaq,
    HospitalPolicy,
    HospitalVoiceConfig,
    HospitalVoiceDocument,
    VoiceCallbackTicket,
)


class HospitalVoiceConfigRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base(self):
        return select(HospitalVoiceConfig).where(HospitalVoiceConfig.is_deleted.is_(False))

    async def get_by_hospital_id(self, hospital_id: int) -> HospitalVoiceConfig | None:
        result = await self.db.execute(
            self._base().where(HospitalVoiceConfig.hospital_id == hospital_id)
        )
        return result.scalar_one_or_none()

    async def get_by_inbound_did(self, did: str) -> HospitalVoiceConfig | None:
        if not did:
            return None
        digits = "".join(c for c in did if c.isdigit())
        result = await self.db.execute(self._base().where(HospitalVoiceConfig.is_active.is_(True)))
        configs = list(result.scalars().all())
        for cfg in configs:
            if not cfg.inbound_did:
                continue
            cfg_digits = "".join(c for c in cfg.inbound_did if c.isdigit())
            if digits and cfg_digits and (digits.endswith(cfg_digits[-10:]) or cfg_digits.endswith(digits[-10:])):
                return cfg
        return None

    async def get_by_id(self, config_id: int) -> HospitalVoiceConfig | None:
        result = await self.db.execute(self._base().where(HospitalVoiceConfig.id == config_id))
        return result.scalar_one_or_none()

    async def create(self, config: HospitalVoiceConfig) -> HospitalVoiceConfig:
        self.db.add(config)
        await self.db.flush()
        await self.db.refresh(config)
        return config

    async def update(self, config: HospitalVoiceConfig) -> HospitalVoiceConfig:
        await self.db.flush()
        await self.db.refresh(config)
        return config

    async def list_active(self) -> list[HospitalVoiceConfig]:
        result = await self.db.execute(self._base().where(HospitalVoiceConfig.is_active.is_(True)))
        return list(result.scalars().all())


class HospitalFaqRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base(self):
        return select(HospitalFaq).where(HospitalFaq.is_deleted.is_(False), HospitalFaq.is_active.is_(True))

    async def list_for_hospital(self, hospital_id: int, language: str | None = None) -> list[HospitalFaq]:
        query = self._base().where(HospitalFaq.hospital_id == hospital_id)
        if language:
            query = query.where(HospitalFaq.language == language)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create(self, faq: HospitalFaq) -> HospitalFaq:
        self.db.add(faq)
        await self.db.flush()
        await self.db.refresh(faq)
        return faq

    async def get_by_id(self, faq_id: int) -> HospitalFaq | None:
        result = await self.db.execute(
            select(HospitalFaq).where(HospitalFaq.id == faq_id, HospitalFaq.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()

    async def update(self, faq: HospitalFaq) -> HospitalFaq:
        await self.db.flush()
        await self.db.refresh(faq)
        return faq


class HospitalPolicyRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_for_hospital(self, hospital_id: int, language: str | None = None) -> list[HospitalPolicy]:
        query = select(HospitalPolicy).where(
            HospitalPolicy.is_deleted.is_(False),
            HospitalPolicy.is_active.is_(True),
            HospitalPolicy.hospital_id == hospital_id,
        )
        if language:
            query = query.where(HospitalPolicy.language == language)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create(self, policy: HospitalPolicy) -> HospitalPolicy:
        self.db.add(policy)
        await self.db.flush()
        await self.db.refresh(policy)
        return policy

    async def get_by_id(self, policy_id: int) -> HospitalPolicy | None:
        result = await self.db.execute(
            select(HospitalPolicy).where(
                HospitalPolicy.id == policy_id, HospitalPolicy.is_deleted.is_(False)
            )
        )
        return result.scalar_one_or_none()

    async def update(self, policy: HospitalPolicy) -> HospitalPolicy:
        await self.db.flush()
        await self.db.refresh(policy)
        return policy


class HospitalVoiceDocumentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_for_hospital(
        self, hospital_id: int, language: str | None = None
    ) -> list[HospitalVoiceDocument]:
        query = select(HospitalVoiceDocument).where(
            HospitalVoiceDocument.is_deleted.is_(False),
            HospitalVoiceDocument.is_active.is_(True),
            HospitalVoiceDocument.hospital_id == hospital_id,
        )
        if language:
            query = query.where(HospitalVoiceDocument.language == language)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create(self, doc: HospitalVoiceDocument) -> HospitalVoiceDocument:
        self.db.add(doc)
        await self.db.flush()
        await self.db.refresh(doc)
        return doc

    async def get_by_id(self, doc_id: int) -> HospitalVoiceDocument | None:
        result = await self.db.execute(
            select(HospitalVoiceDocument).where(
                HospitalVoiceDocument.id == doc_id,
                HospitalVoiceDocument.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def update(self, doc: HospitalVoiceDocument) -> HospitalVoiceDocument:
        await self.db.flush()
        await self.db.refresh(doc)
        return doc


class VoiceCallbackTicketRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, ticket: VoiceCallbackTicket) -> VoiceCallbackTicket:
        self.db.add(ticket)
        await self.db.flush()
        await self.db.refresh(ticket)
        return ticket

    async def list_queued(
        self, limit: int = 50, hospital_id: int | None = None
    ) -> list[VoiceCallbackTicket]:
        stmt = (
            select(VoiceCallbackTicket)
            .where(VoiceCallbackTicket.status == "queued")
            .order_by(VoiceCallbackTicket.created_at.asc())
            .limit(limit)
        )
        if hospital_id is not None:
            stmt = stmt.where(VoiceCallbackTicket.hospital_id == hospital_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update(self, ticket: VoiceCallbackTicket) -> VoiceCallbackTicket:
        await self.db.flush()
        await self.db.refresh(ticket)
        return ticket

    async def get_by_id(self, ticket_id: int) -> VoiceCallbackTicket | None:
        result = await self.db.execute(
            select(VoiceCallbackTicket).where(VoiceCallbackTicket.id == ticket_id)
        )
        return result.scalar_one_or_none()
