from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import CallbackTicketStatus, TransferStatus
from app.core.logger import logger
from app.models.hospital_voice_model import VoiceCallbackTicket
from app.repositories.hospital_voice_repository import VoiceCallbackTicketRepository
from app.telephony.base import TelephonyProvider
from app.telephony.factory import ProviderFactory
from app.utils.twiml_builder import hangup, say, twiml_response


BUSY_MESSAGES = {
    "en": (
        "Reception is currently busy. We have created a callback request. "
        "Our team will call you back shortly. Goodbye."
    ),
    "hi": (
        "रिसेप्शन अभी व्यस्त है। हमने कॉलबैक अनुरोध बना दिया है। "
        "हमारी टीम जल्द आपको वापस कॉल करेगी। अलविदा।"
    ),
    "mr": (
        "रिसेप्शन सध्या व्यस्त आहे. आम्ही कॉलबॅक विनंती तयार केली आहे. "
        "आमची टीम लवकरच तुम्हाला परत कॉल करेल. नमस्कार."
    ),
}

TRANSFER_PROMPTS = {
    "en": "Please wait while I connect you to reception.",
    "hi": "कृपया प्रतीक्षा करें, मैं आपको रिसेप्शन से जोड़ रही हूँ।",
    "mr": "कृपया थांबा, मी तुम्हाला रिसेप्शनशी जोडत आहे.",
}


@dataclass
class TransferResult:
    xml: str
    transfer_status: str
    ticket_id: Optional[int] = None


class ReceptionTransferService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.ticket_repo = VoiceCallbackTicketRepository(db)

    async def transfer(
        self,
        *,
        reception_number: str | None,
        from_number: str,
        language: str = "en",
        hospital_id: int | None = None,
        patient_id: int | None = None,
        call_id: int | None = None,
        reason: str = "patient_requested_reception",
        provider: TelephonyProvider | None = None,
        action_url: str | None = None,
        force_queue: bool = False,
    ) -> TransferResult:
        lang = language if language in BUSY_MESSAGES else "en"
        provider = provider or ProviderFactory.get_default()

        if force_queue or not reception_number:
            ticket = await self._create_ticket(
                hospital_id=hospital_id,
                patient_id=patient_id,
                call_id=call_id,
                phone=from_number,
                reason=reason if reception_number else "no_reception_number",
                language=lang,
            )
            xml = twiml_response(say(BUSY_MESSAGES[lang], provider.say_language(lang)), hangup())
            return TransferResult(
                xml=xml,
                transfer_status=TransferStatus.QUEUED,
                ticket_id=ticket.id,
            )

        prompt = TRANSFER_PROMPTS[lang]
        dial_xml = provider.dial_number(reception_number, action_url=action_url)
        if dial_xml.strip().startswith("<?xml") or dial_xml.strip().startswith("<Response"):
            inner = dial_xml
            if "<Response>" in inner:
                inner = inner.replace(
                    "<Response>",
                    f"<Response>{say(prompt, provider.say_language(lang))}",
                    1,
                )
            xml = inner if inner.startswith("<?xml") else f'<?xml version="1.0" encoding="UTF-8"?>{inner}'
        else:
            xml = twiml_response(say(prompt, provider.say_language(lang)), dial_xml)

        return TransferResult(xml=xml, transfer_status=TransferStatus.INITIATED)

    async def handle_dial_status(
        self,
        *,
        dial_status: str,
        from_number: str,
        language: str = "en",
        hospital_id: int | None = None,
        patient_id: int | None = None,
        call_id: int | None = None,
        provider: TelephonyProvider | None = None,
    ) -> TransferResult:
        status = (dial_status or "").lower()
        provider = provider or ProviderFactory.get_default()
        lang = language if language in BUSY_MESSAGES else "en"

        if status in ("completed", "answered"):
            return TransferResult(
                xml=twiml_response(hangup()),
                transfer_status=TransferStatus.CONNECTED,
            )

        ticket = await self._create_ticket(
            hospital_id=hospital_id,
            patient_id=patient_id,
            call_id=call_id,
            phone=from_number,
            reason=f"reception_{status or 'busy'}",
            language=lang,
        )
        xml = twiml_response(say(BUSY_MESSAGES[lang], provider.say_language(lang)), hangup())
        return TransferResult(
            xml=xml,
            transfer_status=TransferStatus.QUEUED,
            ticket_id=ticket.id,
        )

    async def _create_ticket(
        self,
        *,
        hospital_id: int | None,
        patient_id: int | None,
        call_id: int | None,
        phone: str,
        reason: str,
        language: str,
    ) -> VoiceCallbackTicket:
        ticket = VoiceCallbackTicket(
            hospital_id=hospital_id,
            patient_id=patient_id,
            call_id=call_id,
            phone=phone or "",
            reason=reason,
            status=CallbackTicketStatus.QUEUED,
            language=language,
        )
        return await self.ticket_repo.create(ticket)

    async def list_queued(self, limit: int = 50, hospital_id: int | None = None):
        return await self.ticket_repo.list_queued(limit=limit, hospital_id=hospital_id)

    async def process_queued_tickets(self, limit: int = 20) -> int:
        """
        Full callback workflow:
        queued → notify staff → initiate reception callback → mark called_back / close.
        """
        from app.services.hospital_voice_config_service import HospitalVoiceConfigService
        from app.utils.sms_sender import send_sms

        tickets = await self.ticket_repo.list_queued(limit=limit)
        processed = 0
        config_service = HospitalVoiceConfigService(self.db)

        for ticket in tickets:
            try:
                # 1) Staff notification
                notify_body = (
                    f"NexaCare callback: patient {ticket.phone} "
                    f"needs reception callback. Reason: {ticket.reason or 'n/a'}. "
                    f"Ticket #{ticket.id}"
                )
                reception_number = None
                if ticket.hospital_id:
                    cfg = await config_service.get_entity(ticket.hospital_id)
                    reception_number = cfg.reception_number if cfg else None
                    if reception_number:
                        await send_sms(reception_number, notify_body)
                    logger.info(
                        "Callback ticket #%s staff notified hospital=%s reception=%s",
                        ticket.id,
                        ticket.hospital_id,
                        reception_number,
                    )

                # 2) Reception callback to patient via TelephonyProvider
                provider = ProviderFactory.from_hospital_config(
                    await config_service.get_entity(ticket.hospital_id)
                    if ticket.hospital_id
                    else None
                )
                from app.core.config import settings

                base = settings.PUBLIC_BASE_URL.rstrip("/")
                api = settings.API_V1_PREFIX.rstrip("/")
                # Minimal say+hangup for callback connect (uses reminder health-style placeholder)
                webhook = f"{base}{api}/voice-assistant/twiml/inbound"
                if provider.name == "exotel":
                    webhook = f"{base}{api}/voice-assistant/exotel/inbound"

                result = await provider.initiate_call(
                    ticket.phone,
                    webhook_url=webhook,
                    from_number=reception_number,
                )
                logger.info(
                    "Callback ticket #%s outbound initiated sid=%s simulated=%s",
                    ticket.id,
                    result.provider_call_id,
                    result.simulated,
                )

                if result.simulated:
                    logger.warning(
                        "Callback ticket #%s left queued: provider returned simulated call",
                        ticket.id,
                    )
                    continue

                ticket.status = CallbackTicketStatus.CALLED_BACK
                await self.ticket_repo.update(ticket)
                ticket.status = CallbackTicketStatus.CLOSED
                await self.ticket_repo.update(ticket)
                processed += 1
            except Exception as exc:
                logger.error(
                    "Callback ticket #%s processing failed: %s",
                    ticket.id,
                    exc,
                    exc_info=True,
                )
        return processed
