from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.voice_appointment_assistant.language import detect_language as ai_detect_language
from app.core.constants import VoiceLanguage
from app.repositories.patient_repository import PatientRepository
from app.utils.phone_utils import indian_mobile_last10
from app.utils.redis_service import cache_delete, cache_get, cache_set

TEMP_LANG_TTL = 90 * 24 * 3600  # 90 days


@dataclass
class LanguageResolution:
    language: str
    source: str  # preferred | temp_store | dtmf | hospital_default | ai_fallback | pending_dtmf
    patient_id: Optional[int] = None
    needs_dtmf_menu: bool = False


def _temp_lang_key(phone: str) -> str:
    return f"voice:lang:{indian_mobile_last10(phone)}"


class LanguageResolverService:
    """
    Production language strategy:
    1. Match patient by phone → preferred_language
    2. Temp Redis store for unknown callers
    3. Else DTMF menu (1 EN / 2 HI / 3 MR)
    4. AI detect_language only when allow_ai_fallback (speech-only / DTMF timeout)
    Never auto-switch mid-call once language is locked.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.patient_repo = PatientRepository(db)

    async def resolve_for_inbound(
        self,
        from_number: str,
        hospital_default: str = VoiceLanguage.EN,
        dtmf_digit: str | None = None,
        speech_for_fallback: str | None = None,
        allow_ai_fallback: bool = False,
    ) -> LanguageResolution:
        patient = await self.find_patient_by_phone(from_number)

        if dtmf_digit and dtmf_digit in VoiceLanguage.DTMF_MAP:
            language = VoiceLanguage.DTMF_MAP[dtmf_digit]
            await self.persist_language(from_number, language, patient_id=patient.id if patient else None)
            return LanguageResolution(
                language=language,
                source="dtmf",
                patient_id=patient.id if patient else None,
            )

        if patient and patient.preferred_language in VoiceLanguage.ALL:
            return LanguageResolution(
                language=patient.preferred_language,
                source="preferred",
                patient_id=patient.id,
            )

        temp = await cache_get(_temp_lang_key(from_number))
        if isinstance(temp, str) and temp in VoiceLanguage.ALL:
            if patient:
                patient.preferred_language = temp
                await self.db.flush()
                await cache_delete(_temp_lang_key(from_number))
                return LanguageResolution(
                    language=temp,
                    source="preferred",
                    patient_id=patient.id,
                )
            return LanguageResolution(
                language=temp,
                source="temp_store",
                patient_id=None,
            )

        if allow_ai_fallback and speech_for_fallback:
            detected = ai_detect_language(speech_for_fallback, hospital_default)
            if detected in VoiceLanguage.ALL:
                await self.persist_language(
                    from_number, detected, patient_id=patient.id if patient else None
                )
                return LanguageResolution(
                    language=detected,
                    source="ai_fallback",
                    patient_id=patient.id if patient else None,
                )

        default = hospital_default if hospital_default in VoiceLanguage.ALL else VoiceLanguage.EN
        return LanguageResolution(
            language=default,
            source="pending_dtmf",
            patient_id=patient.id if patient else None,
            needs_dtmf_menu=True,
        )

    async def persist_language(
        self, phone: str, language: str, patient_id: int | None = None
    ) -> None:
        if language not in VoiceLanguage.ALL:
            return
        patient = None
        if patient_id:
            patient = await self.patient_repo.get_by_id(patient_id)
        if not patient:
            patient = await self.find_patient_by_phone(phone)
        if patient:
            patient.preferred_language = language
            await self.db.flush()
            await cache_delete(_temp_lang_key(phone))
            return
        await cache_set(_temp_lang_key(phone), language, ttl=TEMP_LANG_TTL)

    async def promote_temp_language_to_patient(self, phone: str, patient_id: int) -> None:
        temp = await cache_get(_temp_lang_key(phone))
        if not isinstance(temp, str) or temp not in VoiceLanguage.ALL:
            return
        patient = await self.patient_repo.get_by_id(patient_id)
        if patient and not patient.preferred_language:
            patient.preferred_language = temp
            await self.db.flush()
        await cache_delete(_temp_lang_key(phone))

    async def find_patient_by_phone(self, phone: str):
        last10 = indian_mobile_last10(phone)
        if not last10:
            return None
        return await self.patient_repo.get_by_phone(last10)

    async def save_preferred_language(self, patient_id: int, language: str) -> None:
        if language not in VoiceLanguage.ALL:
            return
        patient = await self.patient_repo.get_by_id(patient_id)
        if patient:
            patient.preferred_language = language
            await self.db.flush()
            if patient.phone:
                await cache_delete(_temp_lang_key(patient.phone))
