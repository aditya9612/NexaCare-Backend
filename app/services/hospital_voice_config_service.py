from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import TelephonyProviderType, VoiceLanguage
from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.models.hospital_voice_model import HospitalVoiceConfig
from app.repositories.hospital_repository import HospitalRepository
from app.repositories.hospital_voice_repository import HospitalVoiceConfigRepository
from app.schemas.hospital_voice_schema import (
    HospitalVoiceConfigCreate,
    HospitalVoiceConfigResponse,
    HospitalVoiceConfigUpdate,
)
from app.utils.credential_crypto import encrypt_secret
from app.utils.redis_service import cache_delete, cache_get, cache_set

_SECRET_FIELDS = ("exotel_api_key", "exotel_api_token", "exotel_sid")


class HospitalVoiceConfigService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = HospitalVoiceConfigRepository(db)
        self.hospital_repo = HospitalRepository(db)

    def _cache_key(self, hospital_id: int) -> str:
        return f"voice:config:{hospital_id}"

    def _encrypt_payload(self, payload: dict) -> dict:
        out = dict(payload)
        for field in _SECRET_FIELDS:
            if field in out and out[field]:
                out[field] = encrypt_secret(out[field])
        return out

    def _to_response(self, config: HospitalVoiceConfig) -> HospitalVoiceConfigResponse:
        return HospitalVoiceConfigResponse.model_validate(config)

    async def get_for_hospital(self, hospital_id: int) -> HospitalVoiceConfigResponse | None:
        cached = await cache_get(self._cache_key(hospital_id))
        if cached:
            return HospitalVoiceConfigResponse.model_validate(cached)

        config = await self.repo.get_by_hospital_id(hospital_id)
        if not config:
            return None
        response = self._to_response(config)
        await cache_set(
            self._cache_key(hospital_id),
            response.model_dump(mode="json"),
            ttl=settings.VOICE_CONFIG_CACHE_TTL_SECONDS,
        )
        return response

    async def get_entity(self, hospital_id: int) -> HospitalVoiceConfig | None:
        return await self.repo.get_by_hospital_id(hospital_id)

    async def resolve_for_inbound(
        self, to_number: str = "", hospital_id: int | None = None
    ) -> HospitalVoiceConfig | None:
        if hospital_id:
            return await self.repo.get_by_hospital_id(hospital_id)
        if to_number:
            return await self.repo.get_by_inbound_did(to_number)
        configs = await self.repo.list_active()
        return configs[0] if configs else None

    async def create(self, data: HospitalVoiceConfigCreate) -> HospitalVoiceConfigResponse:
        if not await self.hospital_repo.get_by_id(data.hospital_id):
            raise NotFoundException("Hospital not found")
        existing = await self.repo.get_by_hospital_id(data.hospital_id)
        if existing:
            raise ConflictException("Voice config already exists for this hospital")
        if data.telephony_provider not in TelephonyProviderType.ALL:
            raise BadRequestException("Invalid telephony provider")
        if data.default_language not in VoiceLanguage.ALL:
            raise BadRequestException("Invalid default language")

        payload = self._encrypt_payload(data.model_dump())
        config = HospitalVoiceConfig(**payload)
        config = await self.repo.create(config)
        await cache_delete(self._cache_key(data.hospital_id))
        return self._to_response(config)

    async def update(
        self, hospital_id: int, data: HospitalVoiceConfigUpdate
    ) -> HospitalVoiceConfigResponse:
        config = await self.repo.get_by_hospital_id(hospital_id)
        if not config:
            raise NotFoundException("Hospital voice config not found")
        payload = self._encrypt_payload(data.model_dump(exclude_unset=True))
        if "telephony_provider" in payload and payload["telephony_provider"] not in TelephonyProviderType.ALL:
            raise BadRequestException("Invalid telephony provider")
        if "default_language" in payload and payload["default_language"] not in VoiceLanguage.ALL:
            raise BadRequestException("Invalid default language")
        for key, value in payload.items():
            setattr(config, key, value)
        config = await self.repo.update(config)
        await cache_delete(self._cache_key(hospital_id))
        return self._to_response(config)

    async def upsert(
        self, hospital_id: int, data: HospitalVoiceConfigUpdate | HospitalVoiceConfigCreate
    ) -> HospitalVoiceConfigResponse:
        existing = await self.repo.get_by_hospital_id(hospital_id)
        if existing:
            update = HospitalVoiceConfigUpdate.model_validate(
                data.model_dump(exclude={"hospital_id"}, exclude_unset=True)
            )
            return await self.update(hospital_id, update)
        create = HospitalVoiceConfigCreate(
            hospital_id=hospital_id,
            **data.model_dump(exclude={"hospital_id"}, exclude_unset=True),
        )
        return await self.create(create)
