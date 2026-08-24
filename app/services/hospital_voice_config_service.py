from dataclasses import dataclass
from enum import Enum
import logging

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
from app.utils.phone_utils import inbound_dids_match, normalize_inbound_did
from app.utils.redis_service import cache_delete, cache_get, cache_set

_SECRET_FIELDS = ("exotel_api_key", "exotel_api_token", "exotel_sid")

logger = logging.getLogger("nexacare.voice.hospital_resolution")


class HospitalResolutionSource(str, Enum):
    EXPLICIT_HOSPITAL_ID = "explicit_hospital_id"
    SESSION_HOSPITAL_ID = "session_hospital_id"
    DID_MATCH = "did_match"
    DEV_SINGLE_HOSPITAL_FALLBACK = "dev_single_hospital_fallback"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class HospitalResolutionResult:
    hospital_id: int | None
    config: HospitalVoiceConfig | None
    source: HospitalResolutionSource
    matched_count: int = 0


def mask_inbound_did(did: str) -> str:
    """Mask inbound DID for logs — last 4 digits only."""
    digits = "".join(c for c in (did or "") if c.isdigit())
    if len(digits) <= 4:
        return "***"
    return f"***{digits[-4:]}"


def is_dev_single_hospital_fallback_enabled() -> bool:
    return bool(
        settings.VOICE_SINGLE_HOSPITAL_DEV_FALLBACK
        and settings.APP_ENV.lower() not in ("production", "prod")
    )


def log_hospital_resolution_attempt(
    *,
    call_sid: str = "",
    masked_did: str = "",
    normalized_did: str = "",
    step: str = "",
    service: str = "",
) -> None:
    logger.info(
        "hospital_resolution_attempt call_sid=%s masked_did=%s normalized_did=%s step=%s service=%s",
        call_sid or None,
        masked_did or None,
        normalized_did or None,
        step or None,
        service or None,
    )


def log_hospital_resolution(
    result: HospitalResolutionResult,
    *,
    call_sid: str = "",
    masked_did: str = "",
    step: str = "",
    service: str = "",
    active_config_count: int | None = None,
) -> None:
    payload = {
        "event": "hospital_resolution_success",
        "call_sid": call_sid or None,
        "masked_inbound_did": masked_did or None,
        "resolved_hospital_id": result.hospital_id,
        "resolution_source": result.source.value,
        "matched_count": result.matched_count,
        "step": step or None,
        "service": service or None,
        "active_config_count": active_config_count,
    }
    if result.source == HospitalResolutionSource.UNRESOLVED:
        payload["event"] = "hospital_resolution_failed"
        logger.warning("hospital_resolution_failed %s", payload)
    else:
        logger.info("hospital_resolution_success %s", payload)


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

    async def resolve_inbound_hospital(
        self,
        *,
        to_number: str = "",
        hospital_id: int | None = None,
    ) -> HospitalResolutionResult:
        """
        Resolve exactly one hospital for an inbound voice call.

        Priority:
        1. Explicit hospital_id (must be active)
        2. Exact inbound DID match (exactly one active config)
        3. Dev single-hospital fallback (explicit flag + non-production + exactly one active config)
        4. Unresolved — never guess in production/multi-hospital mode
        """
        if hospital_id:
            config = await self.repo.get_by_hospital_id(hospital_id)
            if config and config.is_active and not config.is_deleted:
                return HospitalResolutionResult(
                    hospital_id=config.hospital_id,
                    config=config,
                    source=HospitalResolutionSource.EXPLICIT_HOSPITAL_ID,
                    matched_count=1,
                )
            return HospitalResolutionResult(
                hospital_id=None,
                config=None,
                source=HospitalResolutionSource.UNRESOLVED,
                matched_count=0,
            )

        if to_number:
            matches = await self.repo.find_active_by_inbound_did(to_number)
            if len(matches) == 1:
                cfg = matches[0]
                return HospitalResolutionResult(
                    hospital_id=cfg.hospital_id,
                    config=cfg,
                    source=HospitalResolutionSource.DID_MATCH,
                    matched_count=1,
                )
            if len(matches) > 1:
                return HospitalResolutionResult(
                    hospital_id=None,
                    config=None,
                    source=HospitalResolutionSource.UNRESOLVED,
                    matched_count=len(matches),
                )

        if is_dev_single_hospital_fallback_enabled():
            configs = await self.repo.list_active()
            if len(configs) == 1:
                cfg = configs[0]
                return HospitalResolutionResult(
                    hospital_id=cfg.hospital_id,
                    config=cfg,
                    source=HospitalResolutionSource.DEV_SINGLE_HOSPITAL_FALLBACK,
                    matched_count=1,
                )

        return HospitalResolutionResult(
            hospital_id=None,
            config=None,
            source=HospitalResolutionSource.UNRESOLVED,
            matched_count=0,
        )

    async def resolve_for_inbound(
        self, to_number: str = "", hospital_id: int | None = None
    ) -> HospitalVoiceConfig | None:
        result = await self.resolve_inbound_hospital(
            to_number=to_number,
            hospital_id=hospital_id,
        )
        return result.config

    async def validate_twilio_did_configuration(self, twilio_to_number: str = "") -> None:
        """Log actionable diagnostics when Twilio To does not match any inbound_did."""
        if not twilio_to_number:
            return
        normalized_twilio = normalize_inbound_did(twilio_to_number)
        configs = await self.repo.list_active()
        if not configs:
            logger.warning(
                "voice_config_missing: no active hospital_voice_configs — inbound calls cannot resolve hospital_id"
            )
            return
        matched = [c for c in configs if c.inbound_did and inbound_dids_match(c.inbound_did, twilio_to_number)]
        if len(matched) == 1:
            return
        masked = mask_inbound_did(twilio_to_number)
        configured = [
            mask_inbound_did(c.inbound_did) for c in configs if c.inbound_did
        ]
        logger.warning(
            "voice_inbound_did_mismatch twilio_to=%s normalized=%s active_configs=%s configured_dids=%s "
            "fix=UPDATE hospital_voice_configs.inbound_did OR enable DEVELOPMENT_SINGLE_HOSPITAL=true (dev only)",
            masked,
            normalized_twilio,
            len(configs),
            configured,
        )

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
