from datetime import date, datetime
from typing import Any
from sqlalchemy import func, select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import AppointmentStatus, EmailCampaignStatus, EmailDeliveryStatus
from app.models.appointment_model import Appointment
from app.models.discharge_model import Discharge
from app.models.doctor_model import Doctor
from app.models.email_model import (
    EmailBatch,
    EmailCampaign,
    EmailDelivery,
    EmailMessage,
    EmailTemplate,
)
from app.models.hospital_model import Hospital
from app.models.patient_model import Patient
from app.utils.pagination import PaginationParams


class EmailRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_patient(self, patient_id: int, hospital_id: int | None = None) -> Patient | None:
        """Fetch patient with optional hospital/tenant isolation."""
        stmt = select(Patient).where(Patient.id == patient_id, Patient.is_deleted.is_(False))
        if hospital_id is not None:
            stmt = stmt.where(Patient.hospital_id == hospital_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_doctor(self, doctor_id: int) -> Doctor | None:
        stmt = select(Doctor).where(Doctor.id == doctor_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_hospital(self, hospital_id: int) -> Hospital | None:
        stmt = select(Hospital).where(Hospital.id == hospital_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_eligible_follow_up(
        self, patient_id: int, hospital_id: int | None = None, today: date | None = None
    ) -> tuple[Appointment | Discharge | None, str, str | None]:
        """
        Check patient follow-up eligibility:
        1. Prioritize upcoming Follow-up appointments (appointment_type in follow_up, follow-up, followup).
        2. Fallback to Discharge follow_up_date.
        3. Check past follow-ups to provide accurate 'Follow-up date has already passed' reason.
        4. Distinguish normal OPD appointments from follow-ups.
        Returns: (record, status_code, reason)
        """
        if today is None:
            today = date.today()

        # Step 1: Query upcoming follow-up appointments
        apt_conditions = [
            Appointment.patient_id == patient_id,
            Appointment.appointment_date >= today,
            func.lower(Appointment.appointment_type).in_(["follow_up", "follow-up", "followup"]),
            Appointment.appointment_status.notin_([AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW]),
        ]
        if hospital_id is not None:
            apt_conditions.append(Appointment.hospital_id == hospital_id)

        upcoming_apt_stmt = (
            select(Appointment)
            .options(selectinload(Appointment.doctor), selectinload(Appointment.patient))
            .where(*apt_conditions)
            .order_by(Appointment.appointment_date.asc(), Appointment.appointment_time.asc())
            .limit(1)
        )
        upcoming_apt_res = await self.db.execute(upcoming_apt_stmt)
        upcoming_apt = upcoming_apt_res.scalar_one_or_none()
        if upcoming_apt:
            return (upcoming_apt, "ELIGIBLE_APPOINTMENT", None)

        # Step 2: Query fallback Discharge record
        dc_conditions = [
            Discharge.patient_id == patient_id,
            Discharge.follow_up_date.isnot(None),
            Discharge.discharge_status.notin_(["CANCELLED"]),
        ]
        if hospital_id is not None:
            dc_conditions.append(Discharge.hospital_id == hospital_id)

        upcoming_dc_stmt = (
            select(Discharge)
            .where(and_(*dc_conditions, Discharge.follow_up_date >= today))
            .order_by(Discharge.follow_up_date.asc(), Discharge.id.desc())
            .limit(1)
        )
        upcoming_dc_res = await self.db.execute(upcoming_dc_stmt)
        upcoming_dc = upcoming_dc_res.scalar_one_or_none()
        if upcoming_dc:
            return (upcoming_dc, "ELIGIBLE_DISCHARGE", None)

        # Step 3: Check if there was any past follow-up date (Appointment or Discharge)
        past_apt_stmt = (
            select(Appointment)
            .where(
                Appointment.patient_id == patient_id,
                Appointment.appointment_date < today,
                func.lower(Appointment.appointment_type).in_(["follow_up", "follow-up", "followup"]),
                Appointment.appointment_status.notin_([AppointmentStatus.CANCELLED]),
            )
            .order_by(Appointment.appointment_date.desc())
            .limit(1)
        )
        if hospital_id is not None:
            past_apt_stmt = past_apt_stmt.where(Appointment.hospital_id == hospital_id)
        past_apt_res = await self.db.execute(past_apt_stmt)
        past_apt = past_apt_res.scalar_one_or_none()

        past_dc_stmt = (
            select(Discharge)
            .where(
                Discharge.patient_id == patient_id,
                Discharge.follow_up_date < today,
                Discharge.discharge_status.notin_(["CANCELLED"]),
            )
            .order_by(Discharge.follow_up_date.desc())
            .limit(1)
        )
        if hospital_id is not None:
            past_dc_stmt = past_dc_stmt.where(Discharge.hospital_id == hospital_id)
        past_dc_res = await self.db.execute(past_dc_stmt)
        past_dc = past_dc_res.scalar_one_or_none()

        if past_apt or past_dc:
            return (past_apt or past_dc, "PAST_FOLLOW_UP", "Follow-up date has already passed")

        return (None, "NO_RECORD", "No valid upcoming appointment or follow-up record found")

    async def get_message_by_idempotency_key(self, idempotency_key: str) -> EmailMessage | None:
        stmt = (
            select(EmailMessage)
            .options(selectinload(EmailMessage.deliveries))
            .where(EmailMessage.idempotency_key == idempotency_key)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_message(self, message: EmailMessage) -> EmailMessage:
        self.db.add(message)
        await self.db.flush()
        await self.db.refresh(message)
        return message

    async def create_delivery(self, message_id: int, status: str, details: str | None = None) -> EmailDelivery:
        delivery = EmailDelivery(message_id=message_id, status=status, details=details)
        self.db.add(delivery)
        await self.db.flush()
        return delivery

    async def create_batch(self, batch: EmailBatch) -> EmailBatch:
        self.db.add(batch)
        await self.db.flush()
        await self.db.refresh(batch)
        return batch

    async def get_batch(self, batch_id: str, hospital_id: int | None = None) -> EmailBatch | None:
        stmt = (
            select(EmailBatch)
            .options(selectinload(EmailBatch.messages))
            .where(EmailBatch.batch_id == batch_id)
        )
        if hospital_id is not None:
            stmt = stmt.where(EmailBatch.hospital_id == hospital_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_batch_summary(
        self,
        batch_id: str,
        sent_count: int,
        failed_count: int,
        skipped_count: int,
        results_summary: dict[str, Any] | None,
        status: str = "COMPLETED",
    ) -> None:
        stmt = select(EmailBatch).where(EmailBatch.batch_id == batch_id)
        res = await self.db.execute(stmt)
        batch = res.scalar_one_or_none()
        if batch:
            batch.sent_count = sent_count
            batch.failed_count = failed_count
            batch.skipped_count = skipped_count
            batch.results_summary = results_summary
            batch.status = status
            await self.db.flush()

    async def get_template_by_name(
        self, name: str, hospital_id: int | None = None, language: str = "en"
    ) -> EmailTemplate | None:
        # Check hospital-specific template first, fallback to system-wide (hospital_id is null)
        stmt = select(EmailTemplate).where(
            EmailTemplate.name == name,
            EmailTemplate.language == language,
            EmailTemplate.is_active.is_(True),
        )
        if hospital_id is not None:
            stmt = stmt.where(or_(EmailTemplate.hospital_id == hospital_id, EmailTemplate.hospital_id.is_(None)))
            stmt = stmt.order_by(EmailTemplate.hospital_id.is_(None), EmailTemplate.hospital_id.desc())
        else:
            stmt = stmt.where(EmailTemplate.hospital_id.is_(None))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_template(self, template: EmailTemplate) -> EmailTemplate:
        self.db.add(template)
        await self.db.flush()
        await self.db.refresh(template)
        return template

    async def create_campaign(self, campaign: EmailCampaign) -> EmailCampaign:
        self.db.add(campaign)
        await self.db.flush()
        await self.db.refresh(campaign)
        return campaign

    async def get_campaign(self, campaign_id: int, hospital_id: int | None = None) -> EmailCampaign | None:
        stmt = select(EmailCampaign).where(EmailCampaign.id == campaign_id)
        if hospital_id is not None:
            stmt = stmt.where(EmailCampaign.hospital_id == hospital_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_due_scheduled_campaigns(self, now_utc: datetime) -> list[EmailCampaign]:
        stmt = (
            select(EmailCampaign)
            .where(
                EmailCampaign.status == EmailCampaignStatus.SCHEDULED,
                EmailCampaign.scheduled_at <= now_utc,
            )
            .order_by(EmailCampaign.scheduled_at.asc())
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def list_messages(
        self,
        hospital_id: int | None,
        pagination: PaginationParams,
        status: str | None = None,
        patient_id: int | None = None,
        source_type: str | None = None,
        search: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> tuple[list[EmailMessage], int]:
        conditions = []
        if hospital_id is not None:
            conditions.append(EmailMessage.hospital_id == hospital_id)
        if status:
            conditions.append(EmailMessage.status == status)
        if patient_id:
            conditions.append(EmailMessage.patient_id == patient_id)
        if source_type:
            conditions.append(EmailMessage.source_type == source_type)
        if search:
            conditions.append(
                or_(
                    EmailMessage.recipient_email.ilike(f"%{search}%"),
                    EmailMessage.subject.ilike(f"%{search}%"),
                )
            )
        if start_date:
            conditions.append(EmailMessage.created_at >= datetime.combine(start_date, datetime.min.time()))
        if end_date:
            conditions.append(EmailMessage.created_at <= datetime.combine(end_date, datetime.max.time()))

        count_stmt = select(func.count(EmailMessage.id)).where(*conditions)
        total_res = await self.db.execute(count_stmt)
        total = total_res.scalar_one()

        stmt = (
            select(EmailMessage)
            .options(selectinload(EmailMessage.deliveries))
            .where(*conditions)
            .order_by(EmailMessage.created_at.desc())
            .offset(pagination.skip)
            .limit(pagination.size)
        )
        items_res = await self.db.execute(stmt)
        items = list(items_res.scalars().all())
        return items, total

    async def get_message_details(self, message_id: int, hospital_id: int | None = None) -> EmailMessage | None:
        stmt = (
            select(EmailMessage)
            .options(selectinload(EmailMessage.deliveries))
            .where(EmailMessage.id == message_id)
        )
        if hospital_id is not None:
            stmt = stmt.where(EmailMessage.hospital_id == hospital_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()
