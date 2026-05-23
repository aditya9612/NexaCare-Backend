import json
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import CampaignStatus, WhatsAppDeliveryStatus, WhatsAppMessageType
from app.core.exceptions import BadRequestException, NotFoundException
from app.core.logger import logger
from app.models.whatsapp_model import MessageDelivery, WhatsAppCampaign, WhatsAppMessage
from app.repositories.appointment_repository import AppointmentRepository
from app.repositories.patient_repository import PatientRepository
from app.repositories.whatsapp_repository import WhatsAppRepository
from app.schemas.whatsapp_schema import (
    BroadcastRequest,
    DeliveryStatusResponse,
    SendMediaRequest,
    SendMessageRequest,
    SendReminderRequest,
    SendTemplateRequest,
    WebhookPayload,
    WhatsAppAnalyticsResponse,
    WhatsAppMessageResponse,
)
from app.utils.helpers import generate_campaign_code, utc_now
from app.utils.pagination import build_paginated_result
from app.utils.redis_service import cache_get, cache_set
from app.utils.twilio_client import twilio_client
from app.utils.whatsapp_sender import send_whatsapp


class WhatsAppService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = WhatsAppRepository(db)
        self.patient_repo = PatientRepository(db)
        self.appointment_repo = AppointmentRepository(db)

    async def send_message(self, data: SendMessageRequest) -> WhatsAppMessageResponse:
        if data.patient_id and not await self.patient_repo.get_by_id(data.patient_id):
            raise NotFoundException("Patient not found")

        message = WhatsAppMessage(
            patient_id=data.patient_id,
            phone_number=data.phone_number,
            message_type=data.message_type,
            message_content=data.message_content,
            media_url=data.media_url,
            delivery_status=WhatsAppDeliveryStatus.PENDING,
        )
        message = await self.repo.create_message(message)
        await self._queue_send(message.id)
        return WhatsAppMessageResponse.model_validate(message)

    async def send_template(self, data: SendTemplateRequest) -> WhatsAppMessageResponse:
        template = await self.repo.get_template(data.template_name)
        if not template:
            raise NotFoundException(f"Template '{data.template_name}' not found")

        body = template.template_body
        for key, value in data.variables.items():
            body = body.replace(f"{{{{{key}}}}}", value)

        return await self.send_message(
            SendMessageRequest(
                patient_id=data.patient_id,
                phone_number=data.phone_number,
                message_content=body,
                message_type=WhatsAppMessageType.TEXT,
            )
        )

    async def send_media(self, data: SendMediaRequest) -> WhatsAppMessageResponse:
        content = data.caption or f"Media: {data.message_type}"
        return await self.send_message(
            SendMessageRequest(
                patient_id=data.patient_id,
                phone_number=data.phone_number,
                message_content=content,
                message_type=data.message_type,
                media_url=data.media_url,
            )
        )

    async def send_reminder(self, data: SendReminderRequest) -> WhatsAppMessageResponse:
        patient = await self.patient_repo.get_by_id(data.patient_id)
        if not patient:
            raise NotFoundException("Patient not found")
        appointment = await self.appointment_repo.get_by_id(data.appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")

        phone = data.phone_number or patient.phone
        if not phone:
            raise BadRequestException("Patient phone number not available")

        text = (
            f"Reminder: Your appointment {appointment.appointment_number} is on "
            f"{appointment.appointment_date} at {appointment.appointment_time}. "
            "Reply CONFIRM to confirm."
        )
        return await self.send_message(
            SendMessageRequest(
                patient_id=data.patient_id,
                phone_number=phone,
                message_content=text,
                message_type=WhatsAppMessageType.TEXT,
            )
        )

    async def broadcast(self, data: BroadcastRequest, user_id: int) -> dict:
        campaign = WhatsAppCampaign(
            campaign_name=data.campaign_name,
            message_content=data.message_content,
            status=CampaignStatus.SCHEDULED if data.scheduled_at else CampaignStatus.RUNNING,
            scheduled_at=data.scheduled_at,
            total_recipients=len(data.phone_numbers),
            created_by=user_id,
        )
        campaign = await self.repo.create_campaign(campaign)

        try:
            from app.tasks.whatsapp_tasks import broadcast_campaign

            broadcast_campaign.delay(campaign.id, data.phone_numbers)
        except Exception:
            await self.process_broadcast(campaign.id, data.phone_numbers)

        return {
            "campaign_id": campaign.id,
            "status": campaign.status,
            "total_recipients": campaign.total_recipients,
        }

    async def process_broadcast(self, campaign_id: int, phone_numbers: list[str]) -> None:
        from sqlalchemy import select

        result = await self.db.execute(select(WhatsAppCampaign).where(WhatsAppCampaign.id == campaign_id))
        campaign = result.scalar_one_or_none()
        if not campaign:
            return
        for phone in phone_numbers:
            msg = WhatsAppMessage(
                phone_number=phone,
                message_type=WhatsAppMessageType.TEXT,
                message_content=campaign.message_content,
                delivery_status=WhatsAppDeliveryStatus.PENDING,
                campaign_id=campaign_id,
            )
            msg = await self.repo.create_message(msg)
            await self.dispatch_message(msg.id)
            campaign.sent_count += 1
        campaign.status = CampaignStatus.COMPLETED
        await self.repo.update_campaign(campaign)

    async def dispatch_message(self, message_id: int) -> None:
        message = await self.repo.get_message(message_id)
        if not message:
            return

        sent = False
        provider_id = None
        if twilio_client.is_configured:
            try:
                result = await twilio_client.send_whatsapp(
                    message.phone_number, message.message_content, message.media_url
                )
                provider_id = result.get("sid")
                sent = True
            except Exception as exc:
                logger.error("Twilio WhatsApp failed: %s", exc)
                message.failure_reason = str(exc)
        else:
            sent = await send_whatsapp(message.phone_number, message.message_content)

        message.sent_at = utc_now()
        message.provider_message_id = provider_id
        message.delivery_status = WhatsAppDeliveryStatus.SENT if sent else WhatsAppDeliveryStatus.FAILED
        await self.repo.update_message(message)
        await self.repo.add_delivery(
            MessageDelivery(
                message_id=message.id,
                status=message.delivery_status,
                status_timestamp=utc_now(),
            )
        )

    async def list_messages(
        self, page: int = 1, size: int = 20, patient_id: int | None = None, delivery_status: str | None = None
    ):
        skip = (page - 1) * size
        items = await self.repo.list_messages(skip=skip, limit=size, patient_id=patient_id, delivery_status=delivery_status)
        total = await self.repo.count_messages(patient_id=patient_id, delivery_status=delivery_status)
        return build_paginated_result(
            [WhatsAppMessageResponse.model_validate(m) for m in items], total, page, size
        )

    async def get_delivery_status(self, message_id: int) -> DeliveryStatusResponse:
        message = await self.repo.get_message(message_id)
        if not message:
            raise NotFoundException("Message not found")
        events = [
            {
                "status": d.status,
                "provider_status": d.provider_status,
                "timestamp": d.status_timestamp.isoformat(),
            }
            for d in message.delivery_records
        ]
        return DeliveryStatusResponse(
            message_id=message.id,
            delivery_status=message.delivery_status,
            sent_at=message.sent_at,
            delivered_at=message.delivered_at,
            read_at=message.read_at,
            events=events,
        )

    async def get_analytics(self) -> WhatsAppAnalyticsResponse:
        cache_key = "analytics:whatsapp"
        cached = await cache_get(cache_key)
        if cached:
            return WhatsAppAnalyticsResponse(**cached)

        counts = await self.repo.delivery_counts()
        total_sent = counts.get("Sent", 0) + counts.get("Delivered", 0) + counts.get("Read", 0)
        total_delivered = counts.get("Delivered", 0) + counts.get("Read", 0)
        total_read = counts.get("Read", 0)
        total_failed = counts.get("Failed", 0)
        total = total_sent or 1

        result = WhatsAppAnalyticsResponse(
            total_sent=total_sent,
            total_delivered=total_delivered,
            total_read=total_read,
            total_failed=total_failed,
            delivery_rate=round(total_delivered / total * 100, 2),
            read_rate=round(total_read / total * 100, 2),
            message_type_breakdown=[
                {"type": t, "count": c} for t, c in await self.repo.message_type_breakdown()
            ],
        )
        await cache_set(cache_key, result.model_dump(), ttl=300)
        return result

    async def handle_webhook(self, payload: WebhookPayload) -> dict:
        message = None
        if payload.provider_message_id:
            message = await self.repo.get_by_provider_id(payload.provider_message_id)
        if not message and payload.phone_number:
            messages = await self.repo.list_messages(limit=1)
            message = next((m for m in messages if m.phone_number == payload.phone_number), None)

        if not message:
            return {"status": "ignored", "reason": "message not found"}

        status = payload.status or payload.raw.get("MessageStatus", "")
        now = payload.timestamp or utc_now()
        if status.lower() in ("delivered", "delivery"):
            message.delivery_status = WhatsAppDeliveryStatus.DELIVERED
            message.delivered_at = now
        elif status.lower() == "read":
            message.delivery_status = WhatsAppDeliveryStatus.READ
            message.read_at = now
        elif status.lower() in ("failed", "undelivered"):
            message.delivery_status = WhatsAppDeliveryStatus.FAILED
            message.failure_reason = json.dumps(payload.raw)

        await self.repo.update_message(message)
        await self.repo.add_delivery(
            MessageDelivery(
                message_id=message.id,
                status=message.delivery_status,
                provider_status=status,
                status_timestamp=now,
                raw_payload=json.dumps(payload.raw),
            )
        )
        return {"status": "processed", "message_id": message.id}

    async def _queue_send(self, message_id: int) -> None:
        try:
            from app.tasks.whatsapp_tasks import send_message_async

            send_message_async.delay(message_id)
        except Exception:
            await self.dispatch_message(message_id)
