from datetime import date, datetime
import os
import re
import tempfile
from typing import Any
import uuid

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    AppointmentStatus,
    EmailCampaignStatus,
    EmailDeliveryStatus,
    EmailMessageType,
    EmailSourceType,
)
from app.core.logger import logger
from app.models.email_model import (
    EmailBatch,
    EmailCampaign,
    EmailMessage,
    EmailTemplate,
)
from app.repositories.email_repository import EmailRepository
from app.schemas.email_schema import (
    BroadcastEmailRequest,
    BroadcastResponse,
    EmailBatchResponse,
    PatientEmailResult,
    PatientReminderResult,
    SendDirectEmailRequest,
    SendEmailReminderRequest,
    SendMediaEmailRequest,
    SendTemplateEmailRequest,
)
from app.utils.email_sender import send_email
from app.utils.helpers import utc_now
from app.utils.redis_service import acquire_lock, release_lock


class EmailService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = EmailRepository(db)

    # ─────────────────────────────────────────────────────────────────────────────
    # 1. SEND APPOINTMENT / FOLLOW-UP REMINDER (MULTI-PATIENT)
    # ─────────────────────────────────────────────────────────────────────────────
    async def send_reminders(
        self,
        hospital_id: int | None,
        request: SendEmailReminderRequest,
    ) -> EmailBatchResponse:
        batch_id = f"batch-rem-{uuid.uuid4().hex[:12]}"
        total_patients = len(request.patient_ids)

        # Async Celery branch for batches > 5 or when force_async is requested
        if total_patients > 5 or request.force_async:
            batch = EmailBatch(
                batch_id=batch_id,
                hospital_id=hospital_id,
                batch_type="REMINDER",
                status="QUEUED",
                total_count=total_patients,
            )
            await self.repo.create_batch(batch)
            await self.db.commit()

            try:
                from app.tasks.email_tasks import send_batch_email_reminders_task
                send_batch_email_reminders_task.delay(
                    batch_id=batch_id,
                    hospital_id=hospital_id,
                    patient_ids=request.patient_ids,
                    custom_notes=request.custom_notes,
                )
            except Exception as exc:
                logger.warning("Celery broker unavailable (%s); reminder batch %s queued in DB", exc, batch_id)

            return EmailBatchResponse(
                batch_id=batch_id,
                is_async=True,
                total_patients=total_patients,
                sent_count=0,
                failed_count=0,
                skipped_count=0,
                results=[],
                message=f"Reminder batch of {total_patients} patients queued for background processing.",
            )

        # Synchronous execution for small batches (<= 5)
        batch = EmailBatch(
            batch_id=batch_id,
            hospital_id=hospital_id,
            batch_type="REMINDER",
            status="PROCESSING",
            total_count=total_patients,
        )
        await self.repo.create_batch(batch)

        results: list[PatientReminderResult] = []
        sent_count = 0
        failed_count = 0
        skipped_count = 0

        for patient_id in request.patient_ids:
            res = await self._process_single_patient_reminder(
                batch_id=batch_id,
                hospital_id=hospital_id,
                patient_id=patient_id,
                custom_notes=request.custom_notes,
            )
            results.append(res)
            if res.status == EmailDeliveryStatus.SENT:
                sent_count += 1
            elif res.status == EmailDeliveryStatus.SKIPPED:
                skipped_count += 1
            else:
                failed_count += 1

        # Update batch summary
        await self.repo.update_batch_summary(
            batch_id=batch_id,
            sent_count=sent_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            results_summary={"results": [r.model_dump(mode="json") for r in results]},
            status="COMPLETED",
        )
        await self.db.commit()

        return EmailBatchResponse(
            batch_id=batch_id,
            is_async=False,
            total_patients=total_patients,
            sent_count=sent_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            results=results,
            message=f"Processed reminders for {total_patients} patients: {sent_count} sent, {skipped_count} skipped, {failed_count} failed.",
        )

    async def _process_single_patient_reminder(
        self,
        batch_id: str,
        hospital_id: int | None,
        patient_id: int,
        custom_notes: str | None,
    ) -> PatientReminderResult:
        """Process follow-up reminder for a single patient independently."""
        try:
            # 1. Fetch patient with hospital tenant isolation
            patient = await self.repo.get_patient(patient_id, hospital_id)
            if not patient:
                return PatientReminderResult(
                    patient_id=patient_id,
                    status=EmailDeliveryStatus.SKIPPED,
                    reason="Patient record not found",
                )

            patient_name = f"{patient.first_name} {patient.last_name}".strip()
            recipient_email = patient.email

            if not recipient_email or "@" not in recipient_email:
                return PatientReminderResult(
                    patient_id=patient_id,
                    patient_name=patient_name,
                    status=EmailDeliveryStatus.SKIPPED,
                    reason="Patient email address missing or invalid",
                )

            # 2. Check follow-up eligibility (Appointment vs Discharge)
            record, status_code, reason = await self.repo.get_eligible_follow_up(
                patient_id=patient_id, hospital_id=hospital_id
            )

            if status_code in ("PAST_FOLLOW_UP", "NO_RECORD"):
                return PatientReminderResult(
                    patient_id=patient_id,
                    patient_name=patient_name,
                    recipient_email=recipient_email,
                    status=EmailDeliveryStatus.SKIPPED,
                    reason=reason,
                )

            # 3. Determine event details & timing
            doctor_name = "Attending Physician"
            appointment_time_str: str | None = None
            appointment_id: int | None = None
            discharge_id: int | None = None

            if status_code == "ELIGIBLE_APPOINTMENT":
                source_type = EmailSourceType.APPOINTMENT
                appointment = record
                appointment_id = appointment.id
                target_date = appointment.appointment_date
                # Real stored appointment time
                if appointment.appointment_time:
                    appointment_time_str = appointment.appointment_time.strftime("%I:%M %p")

                if appointment.doctor:
                    doctor_name = f"Dr. {appointment.doctor.first_name} {appointment.doctor.last_name}".strip()
            else:
                source_type = EmailSourceType.DISCHARGE
                discharge = record
                discharge_id = discharge.id
                target_date = discharge.follow_up_date
                # DO NOT invent 10:00 AM! Follow-up time remains None for Discharge
                appointment_time_str = None

                if discharge.doctor_id:
                    doc = await self.repo.get_doctor(discharge.doctor_id)
                    if doc:
                        doctor_name = f"Dr. {doc.first_name} {doc.last_name}".strip()

            event_id = appointment_id or discharge_id

            # 4. Atomic Database Idempotency Check
            target_date_str = target_date.isoformat() if target_date else "unknown"
            idempotency_key = f"hosp:{hospital_id}:pat:{patient_id}:{source_type.value}:{event_id}:{target_date_str}"

            existing_msg = await self.repo.get_message_by_idempotency_key(idempotency_key)
            if existing_msg and existing_msg.status == EmailDeliveryStatus.SENT:
                return PatientReminderResult(
                    patient_id=patient_id,
                    patient_name=patient_name,
                    recipient_email=recipient_email,
                    status=EmailDeliveryStatus.SKIPPED,
                    reason="Reminder already sent for this follow-up event",
                    source_type=source_type,
                    event_id=event_id,
                    follow_up_date=target_date,
                    appointment_time=appointment_time_str,
                    message_id=existing_msg.id,
                )

            # 5. Distributed Lock with Unique UUID Token
            lock_token = str(uuid.uuid4())
            lock_key = f"lock:email:reminder:{idempotency_key}"
            lock_acquired = await acquire_lock(lock_key, lock_token, expire_seconds=60)
            if not lock_acquired:
                return PatientReminderResult(
                    patient_id=patient_id,
                    patient_name=patient_name,
                    recipient_email=recipient_email,
                    status=EmailDeliveryStatus.SKIPPED,
                    reason="Reminder sending is currently in progress by another worker",
                    source_type=source_type,
                    event_id=event_id,
                    follow_up_date=target_date,
                    appointment_time=appointment_time_str,
                )

            try:
                # 6. Fetch hospital branding
                hospital_name = "NexaCare HMS"
                if hospital_id:
                    hosp = await self.repo.get_hospital(hospital_id)
                    if hosp and hosp.name:
                        hospital_name = hosp.name

                # 7. Render Template
                subject = f"Appointment Follow-up Reminder - {hospital_name}"
                formatted_date = target_date.strftime("%A, %B %d, %Y")

                time_html = f"<p><strong>Time:</strong> {appointment_time_str}</p>" if appointment_time_str else ""
                time_plain = f"Time: {appointment_time_str}\n" if appointment_time_str else ""
                notes_html = f"<p><strong>Special Instructions:</strong> {custom_notes}</p>" if custom_notes else ""
                notes_plain = f"Special Instructions: {custom_notes}\n" if custom_notes else ""

                html_body = f"""
                <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
                    <h2 style="color: #0b6bcb; margin-top: 0;">{hospital_name}</h2>
                    <p>Dear <strong>{patient_name}</strong>,</p>
                    <p>This is a gentle reminder regarding your upcoming medical follow-up consultation.</p>
                    <div style="background-color: #f7f9fc; padding: 15px; border-radius: 6px; margin: 20px 0;">
                        <p style="margin: 0 0 8px 0;"><strong>Doctor:</strong> {doctor_name}</p>
                        <p style="margin: 0 0 8px 0;"><strong>Date:</strong> {formatted_date}</p>
                        {time_html}
                        {notes_html}
                    </div>
                    <p>Please reach out if you need to reschedule or require any assistance.</p>
                    <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;" />
                    <p style="font-size: 12px; color: #777;">Automated message from {hospital_name}. Please do not reply directly to this email.</p>
                </div>
                """

                plain_body = (
                    f"Dear {patient_name},\n\n"
                    f"This is a reminder regarding your upcoming follow-up consultation at {hospital_name}.\n\n"
                    f"Doctor: {doctor_name}\n"
                    f"Date: {formatted_date}\n"
                    f"{time_plain}"
                    f"{notes_plain}\n"
                    f"Regards,\n{hospital_name}"
                )

                # 8. Dispatch Email via SMTP
                send_success = await send_email(
                    to=recipient_email,
                    subject=subject,
                    body=html_body,
                    plain_body=plain_body,
                )

                # 9. Record Message and Delivery Audit Trail
                msg_status = EmailDeliveryStatus.SENT if send_success else EmailDeliveryStatus.FAILED
                failure_reason = None if send_success else "SMTP delivery failed to accept message"

                email_msg = EmailMessage(
                    hospital_id=hospital_id,
                    batch_id=batch_id,
                    patient_id=patient_id,
                    appointment_id=appointment_id,
                    discharge_id=discharge_id,
                    recipient_email=recipient_email,
                    subject=subject,
                    body_html=html_body,
                    body_text=plain_body,
                    message_type=EmailMessageType.HTML,
                    source_type=source_type,
                    target_follow_up_date=target_date,
                    idempotency_key=idempotency_key,
                    status=msg_status,
                    failure_reason=failure_reason,
                    sent_at=utc_now() if send_success else None,
                )
                await self.repo.create_message(email_msg)

                await self.repo.create_delivery(
                    message_id=email_msg.id,
                    status=msg_status,
                    details="SMTP 250 OK - Accepted for delivery" if send_success else "SMTP delivery error",
                )

                # Update appointment flag if applicable
                if send_success and appointment_id and status_code == "ELIGIBLE_APPOINTMENT":
                    record.reminder_sent = True

                return PatientReminderResult(
                    patient_id=patient_id,
                    patient_name=patient_name,
                    recipient_email=recipient_email,
                    status=msg_status,
                    reason=failure_reason,
                    source_type=source_type,
                    event_id=event_id,
                    follow_up_date=target_date,
                    appointment_time=appointment_time_str,
                    message_id=email_msg.id,
                )
            finally:
                await release_lock(lock_key, lock_token)

        except Exception as exc:
            logger.error("Error processing reminder for patient %s: %s", patient_id, exc, exc_info=True)
            return PatientReminderResult(
                patient_id=patient_id,
                status=EmailDeliveryStatus.FAILED,
                reason=f"Internal error: {type(exc).__name__}",
            )

    # ─────────────────────────────────────────────────────────────────────────────
    # 2. SEND TEMPLATE EMAIL (MULTI-PATIENT)
    # ─────────────────────────────────────────────────────────────────────────────
    async def send_template(
        self,
        hospital_id: int | None,
        request: SendTemplateEmailRequest,
    ) -> EmailBatchResponse:
        batch_id = f"batch-tpl-{uuid.uuid4().hex[:12]}"
        total_patients = len(request.patient_ids)

        if total_patients > 5:
            batch = EmailBatch(
                batch_id=batch_id,
                hospital_id=hospital_id,
                batch_type="TEMPLATE",
                status="QUEUED",
                total_count=total_patients,
            )
            await self.repo.create_batch(batch)
            await self.db.commit()

            try:
                from app.tasks.email_tasks import send_batch_template_task
                send_batch_template_task.delay(
                    batch_id=batch_id,
                    hospital_id=hospital_id,
                    patient_ids=request.patient_ids,
                    template_name=request.template_name,
                    language=request.language,
                    variables=request.variables,
                )
            except Exception as exc:
                logger.warning("Celery broker unavailable (%s); template batch %s queued in DB", exc, batch_id)

            return EmailBatchResponse(
                batch_id=batch_id,
                is_async=True,
                total_patients=total_patients,
                sent_count=0,
                failed_count=0,
                skipped_count=0,
                results=[],
                message=f"Template batch of {total_patients} patients queued for background processing.",
            )

        batch = EmailBatch(
            batch_id=batch_id,
            hospital_id=hospital_id,
            batch_type="TEMPLATE",
            status="PROCESSING",
            total_count=total_patients,
        )
        await self.repo.create_batch(batch)

        template = await self.repo.get_template_by_name(
            request.template_name, hospital_id, request.language
        )

        results: list[PatientEmailResult] = []
        sent_count = 0
        failed_count = 0
        skipped_count = 0

        for patient_id in request.patient_ids:
            res = await self._process_single_patient_template(
                batch_id=batch_id,
                hospital_id=hospital_id,
                patient_id=patient_id,
                template=template,
                template_name=request.template_name,
                raw_variables=request.variables,
            )
            results.append(res)
            if res.status == EmailDeliveryStatus.SENT:
                sent_count += 1
            elif res.status == EmailDeliveryStatus.SKIPPED:
                skipped_count += 1
            else:
                failed_count += 1

        await self.repo.update_batch_summary(
            batch_id=batch_id,
            sent_count=sent_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            results_summary={"results": [r.model_dump(mode="json") for r in results]},
            status="COMPLETED",
        )
        await self.db.commit()

        return EmailBatchResponse(
            batch_id=batch_id,
            is_async=False,
            total_patients=total_patients,
            sent_count=sent_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            results=results,
            message=f"Processed template emails for {total_patients} patients: {sent_count} sent, {skipped_count} skipped, {failed_count} failed.",
        )

    async def _process_single_patient_template(
        self,
        batch_id: str,
        hospital_id: int | None,
        patient_id: int,
        template: EmailTemplate | None,
        template_name: str,
        raw_variables: dict[str, Any],
    ) -> PatientEmailResult:
        try:
            patient = await self.repo.get_patient(patient_id, hospital_id)
            if not patient:
                return PatientEmailResult(
                    patient_id=patient_id,
                    status=EmailDeliveryStatus.SKIPPED,
                    reason="Patient record not found",
                )

            patient_name = f"{patient.first_name} {patient.last_name}".strip()
            recipient_email = patient.email

            if not recipient_email or "@" not in recipient_email:
                return PatientEmailResult(
                    patient_id=patient_id,
                    patient_name=patient_name,
                    status=EmailDeliveryStatus.SKIPPED,
                    reason="Patient email address missing or invalid",
                )

            if not template:
                return PatientEmailResult(
                    patient_id=patient_id,
                    patient_name=patient_name,
                    recipient_email=recipient_email,
                    status=EmailDeliveryStatus.FAILED,
                    reason=f"Template '{template_name}' not found or inactive",
                )

            # Build patient-isolated variable dictionary
            patient_vars = dict(raw_variables)
            patient_vars["patient_name"] = patient_name
            patient_vars["first_name"] = patient.first_name
            patient_vars["last_name"] = patient.last_name
            patient_vars["patient_code"] = patient.patient_code

            hospital_name = "NexaCare HMS"
            if hospital_id:
                hosp = await self.repo.get_hospital(hospital_id)
                if hosp and hosp.name:
                    hospital_name = hosp.name
            patient_vars["hospital_name"] = hospital_name
            patient_vars.setdefault("clinic", hospital_name)

            # Render placeholders
            subject = self._render_template_string(template.subject, patient_vars)
            body_html = self._render_template_string(template.body_html, patient_vars)
            body_text = self._render_template_string(template.body_text or "", patient_vars) if template.body_text else None

            send_success = await send_email(
                to=recipient_email,
                subject=subject,
                body=body_html,
                plain_body=body_text,
            )

            msg_status = EmailDeliveryStatus.SENT if send_success else EmailDeliveryStatus.FAILED
            failure_reason = None if send_success else "SMTP delivery failed to accept message"

            email_msg = EmailMessage(
                hospital_id=hospital_id,
                batch_id=batch_id,
                patient_id=patient_id,
                recipient_email=recipient_email,
                subject=subject,
                body_html=body_html,
                body_text=body_text,
                message_type=EmailMessageType.TEMPLATE,
                source_type=EmailSourceType.GENERAL,
                status=msg_status,
                failure_reason=failure_reason,
                sent_at=utc_now() if send_success else None,
            )
            await self.repo.create_message(email_msg)
            await self.repo.create_delivery(
                message_id=email_msg.id,
                status=msg_status,
                details="SMTP 250 OK" if send_success else "SMTP delivery error",
            )

            return PatientEmailResult(
                patient_id=patient_id,
                patient_name=patient_name,
                recipient_email=recipient_email,
                status=msg_status,
                reason=failure_reason,
                message_id=email_msg.id,
            )
        except Exception as exc:
            logger.error("Error sending template email to patient %s: %s", patient_id, exc, exc_info=True)
            return PatientEmailResult(
                patient_id=patient_id,
                status=EmailDeliveryStatus.FAILED,
                reason=f"Internal error: {type(exc).__name__}",
            )

    # ─────────────────────────────────────────────────────────────────────────────
    # 3. SEND MEDIA / ATTACHMENT EMAIL (MULTI-PATIENT)
    # ─────────────────────────────────────────────────────────────────────────────
    async def send_media(
        self,
        hospital_id: int | None,
        request: SendMediaEmailRequest,
    ) -> EmailBatchResponse:
        batch_id = f"batch-med-{uuid.uuid4().hex[:12]}"
        total_patients = len(request.patient_ids)

        if total_patients > 5:
            batch = EmailBatch(
                batch_id=batch_id,
                hospital_id=hospital_id,
                batch_type="MEDIA",
                status="QUEUED",
                total_count=total_patients,
            )
            await self.repo.create_batch(batch)
            await self.db.commit()

            try:
                from app.tasks.email_tasks import send_batch_media_task
                send_batch_media_task.delay(
                    batch_id=batch_id,
                    hospital_id=hospital_id,
                    patient_ids=request.patient_ids,
                    message_type=request.message_type.value,
                    media_url=request.media_url,
                    caption=request.caption,
                )
            except Exception as exc:
                logger.warning("Celery broker unavailable (%s); media batch %s queued in DB", exc, batch_id)

            return EmailBatchResponse(
                batch_id=batch_id,
                is_async=True,
                total_patients=total_patients,
                sent_count=0,
                failed_count=0,
                skipped_count=0,
                results=[],
                message=f"Media email batch of {total_patients} patients queued for background processing.",
            )

        batch = EmailBatch(
            batch_id=batch_id,
            hospital_id=hospital_id,
            batch_type="MEDIA",
            status="PROCESSING",
            total_count=total_patients,
        )
        await self.repo.create_batch(batch)

        results: list[PatientEmailResult] = []
        sent_count = 0
        failed_count = 0
        skipped_count = 0

        for patient_id in request.patient_ids:
            res = await self._process_single_patient_media(
                batch_id=batch_id,
                hospital_id=hospital_id,
                patient_id=patient_id,
                message_type=request.message_type,
                media_url=request.media_url,
                caption=request.caption,
            )
            results.append(res)
            if res.status == EmailDeliveryStatus.SENT:
                sent_count += 1
            elif res.status == EmailDeliveryStatus.SKIPPED:
                skipped_count += 1
            else:
                failed_count += 1

        await self.repo.update_batch_summary(
            batch_id=batch_id,
            sent_count=sent_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            results_summary={"results": [r.model_dump(mode="json") for r in results]},
            status="COMPLETED",
        )
        await self.db.commit()

        return EmailBatchResponse(
            batch_id=batch_id,
            is_async=False,
            total_patients=total_patients,
            sent_count=sent_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            results=results,
            message=f"Processed media emails for {total_patients} patients: {sent_count} sent, {skipped_count} skipped, {failed_count} failed.",
        )

    async def _process_single_patient_media(
        self,
        batch_id: str,
        hospital_id: int | None,
        patient_id: int,
        message_type: EmailMessageType,
        media_url: str,
        caption: str | None,
    ) -> PatientEmailResult:
        try:
            patient = await self.repo.get_patient(patient_id, hospital_id)
            if not patient:
                return PatientEmailResult(
                    patient_id=patient_id,
                    status=EmailDeliveryStatus.SKIPPED,
                    reason="Patient record not found",
                )

            patient_name = f"{patient.first_name} {patient.last_name}".strip()
            recipient_email = patient.email

            if not recipient_email or "@" not in recipient_email:
                return PatientEmailResult(
                    patient_id=patient_id,
                    patient_name=patient_name,
                    status=EmailDeliveryStatus.SKIPPED,
                    reason="Patient email address missing or invalid",
                )

            hospital_name = "NexaCare HMS"
            if hospital_id:
                hosp = await self.repo.get_hospital(hospital_id)
                if hosp and hosp.name:
                    hospital_name = hosp.name

            subject = f"Medical Document / Report for {patient_name} - {hospital_name}"
            caption_text = caption or "Please find your requested medical document attached / linked below."

            # Resolve / download attachment if local file or valid HTTP/HTTPS URL
            attachment_path: str | None = None
            temp_file_to_cleanup: str | None = None

            if media_url:
                if os.path.isfile(media_url):
                    attachment_path = media_url
                elif media_url.startswith(("http://", "https://")):
                    try:
                        ext = ".pdf" if message_type == EmailMessageType.PDF else ".bin"
                        raw_filename = media_url.split("?")[0].rstrip("/").split("/")[-1]
                        if not raw_filename or "." not in raw_filename:
                            raw_filename = f"document_{patient_id}{ext}"

                        temp_path = os.path.join(tempfile.gettempdir(), f"nexacare_{uuid.uuid4().hex[:6]}_{raw_filename}")
                        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                            resp = await client.get(media_url)
                            if resp.status_code == 200 and resp.content:
                                with open(temp_path, "wb") as f:
                                    f.write(resp.content)
                                attachment_path = temp_path
                                temp_file_to_cleanup = temp_path
                    except Exception as dl_err:
                        logger.warning("Could not download media_url for attachment: %s", dl_err)

            attachment_badge = f"""
                <div style="background-color: #e8f4fd; border: 1px solid #b6e0fe; border-radius: 6px; padding: 12px; margin: 15px 0;">
                    <p style="margin: 0; font-weight: bold; color: #084298;">📎 File Attached: {os.path.basename(attachment_path)}</p>
                </div>
            """ if attachment_path else ""

            html_body = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
                <h2 style="color: #0b6bcb; margin-top: 0;">{hospital_name}</h2>
                <p>Dear <strong>{patient_name}</strong>,</p>
                <p>{caption_text}</p>
                {attachment_badge}
                <div style="margin: 20px 0; padding: 15px; background: #f0f7ff; border-radius: 6px; text-align: center;">
                    <a href="{media_url}" target="_blank" style="display: inline-block; padding: 10px 20px; background-color: #0b6bcb; color: #ffffff; text-decoration: none; border-radius: 4px; font-weight: bold;">
                        View / Download Online
                    </a>
                    <p style="font-size: 11px; color: #666; margin-top: 8px;">File link: {media_url}</p>
                </div>
                <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;" />
                <p style="font-size: 12px; color: #777;">Automated message from {hospital_name}.</p>
            </div>
            """

            plain_body = f"Dear {patient_name},\n\n{caption_text}\n\nDocument Link: {media_url}\n\nRegards,\n{hospital_name}"

            try:
                send_success = await send_email(
                    to=recipient_email,
                    subject=subject,
                    body=html_body,
                    plain_body=plain_body,
                    attachment_path=attachment_path,
                )
            finally:
                if temp_file_to_cleanup and os.path.exists(temp_file_to_cleanup):
                    try:
                        os.remove(temp_file_to_cleanup)
                    except OSError:
                        pass

            msg_status = EmailDeliveryStatus.SENT if send_success else EmailDeliveryStatus.FAILED
            failure_reason = None if send_success else "SMTP delivery failed to accept message"

            email_msg = EmailMessage(
                hospital_id=hospital_id,
                batch_id=batch_id,
                patient_id=patient_id,
                recipient_email=recipient_email,
                subject=subject,
                body_html=html_body,
                body_text=plain_body,
                media_url=media_url,
                message_type=message_type.value,
                source_type=EmailSourceType.GENERAL,
                status=msg_status,
                failure_reason=failure_reason,
                sent_at=utc_now() if send_success else None,
            )
            await self.repo.create_message(email_msg)
            await self.repo.create_delivery(
                message_id=email_msg.id,
                status=msg_status,
                details="SMTP 250 OK" if send_success else "SMTP delivery error",
            )

            return PatientEmailResult(
                patient_id=patient_id,
                patient_name=patient_name,
                recipient_email=recipient_email,
                status=msg_status,
                reason=failure_reason,
                message_id=email_msg.id,
            )
        except Exception as exc:
            logger.error("Error sending media email to patient %s: %s", patient_id, exc, exc_info=True)
            return PatientEmailResult(
                patient_id=patient_id,
                status=EmailDeliveryStatus.FAILED,
                reason=f"Internal error: {type(exc).__name__}",
            )

    # ─────────────────────────────────────────────────────────────────────────────
    # 4. DIRECT EMAIL (SINGLE TRANSACTIONAL)
    # ─────────────────────────────────────────────────────────────────────────────
    async def send_direct_message(
        self,
        hospital_id: int | None,
        request: SendDirectEmailRequest,
    ) -> EmailMessage:
        send_success = await send_email(
            to=request.to_email,
            subject=request.subject,
            body=request.body_html,
            plain_body=request.body_text,
        )

        msg_status = EmailDeliveryStatus.SENT if send_success else EmailDeliveryStatus.FAILED
        failure_reason = None if send_success else "SMTP delivery failed to accept message"

        email_msg = EmailMessage(
            hospital_id=hospital_id,
            recipient_email=request.to_email,
            subject=request.subject,
            body_html=request.body_html,
            body_text=request.body_text,
            message_type=EmailMessageType.HTML,
            source_type=EmailSourceType.GENERAL,
            status=msg_status,
            failure_reason=failure_reason,
            sent_at=utc_now() if send_success else None,
        )
        await self.repo.create_message(email_msg)
        await self.repo.create_delivery(
            message_id=email_msg.id,
            status=msg_status,
            details="SMTP 250 OK" if send_success else "SMTP delivery error",
        )
        await self.db.commit()
        loaded_msg = await self.repo.get_message_details(email_msg.id, hospital_id)
        return loaded_msg or email_msg

    # ─────────────────────────────────────────────────────────────────────────────
    # 5. BROADCAST CAMPAIGN
    # ─────────────────────────────────────────────────────────────────────────────
    async def create_broadcast_campaign(
        self,
        hospital_id: int | None,
        request: BroadcastEmailRequest,
        created_by: int | None = None,
    ) -> BroadcastResponse:
        now_utc = utc_now()
        is_scheduled = request.scheduled_at is not None and request.scheduled_at > now_utc

        template_id: int | None = None
        if request.template_name:
            tpl = await self.repo.get_template_by_name(request.template_name, hospital_id)
            if tpl:
                template_id = tpl.id

        status = EmailCampaignStatus.SCHEDULED if is_scheduled else EmailCampaignStatus.QUEUED

        campaign = EmailCampaign(
            hospital_id=hospital_id,
            campaign_name=request.campaign_name,
            template_id=template_id,
            message_content=request.message_content,
            status=status,
            scheduled_at=request.scheduled_at if is_scheduled else None,
            total_recipients=len(request.emails),
            created_by=created_by,
        )
        await self.repo.create_campaign(campaign)
        await self.db.commit()

        if not is_scheduled:
            try:
                from app.tasks.email_tasks import broadcast_email_campaign_task
                broadcast_email_campaign_task.delay(
                    campaign_id=campaign.id,
                    emails=[str(e) for e in request.emails],
                    hospital_id=hospital_id,
                )
            except Exception as exc:
                logger.warning("Celery broker unavailable (%s); broadcast campaign %s queued in DB for Celery Beat sweeper", exc, campaign.id)

        return BroadcastResponse(
            campaign_id=campaign.id,
            campaign_name=campaign.campaign_name,
            status=status,
            scheduled_at=campaign.scheduled_at,
            total_recipients=len(request.emails),
            message="Campaign scheduled successfully" if is_scheduled else "Broadcast campaign queued for delivery",
        )

    async def execute_broadcast_campaign(
        self,
        campaign_id: int,
        emails: list[str],
        hospital_id: int | None,
    ) -> None:
        campaign = await self.repo.get_campaign(campaign_id, hospital_id)
        if not campaign:
            logger.error("Campaign %s not found for broadcast execution", campaign_id)
            return

        campaign.status = EmailCampaignStatus.RUNNING
        campaign.started_at = utc_now()
        await self.db.flush()

        sent_count = 0
        failed_count = 0
        subject = campaign.campaign_name
        body = campaign.message_content or f"<p>{campaign.campaign_name}</p>"

        for email in emails:
            try:
                success = await send_email(to=email, subject=subject, body=body)
                status = EmailDeliveryStatus.SENT if success else EmailDeliveryStatus.FAILED

                msg = EmailMessage(
                    hospital_id=hospital_id,
                    campaign_id=campaign.id,
                    recipient_email=email,
                    subject=subject,
                    body_html=body,
                    message_type=EmailMessageType.HTML,
                    source_type=EmailSourceType.CAMPAIGN,
                    status=status,
                    sent_at=utc_now() if success else None,
                )
                await self.repo.create_message(msg)
                await self.repo.create_delivery(msg.id, status, "SMTP 250 OK" if success else "SMTP delivery error")

                if success:
                    sent_count += 1
                else:
                    failed_count += 1
            except Exception as exc:
                logger.error("Failed to broadcast email to %s: %s", email, exc)
                failed_count += 1

        campaign.sent_count = sent_count
        campaign.failed_count = failed_count
        campaign.status = EmailCampaignStatus.COMPLETED
        campaign.completed_at = utc_now()
        await self.db.commit()

    # ─────────────────────────────────────────────────────────────────────────────
    # 6. BATCH STATUS
    # ─────────────────────────────────────────────────────────────────────────────
    async def get_batch_status(self, batch_id: str, hospital_id: int | None = None) -> EmailBatchResponse | None:
        batch = await self.repo.get_batch(batch_id, hospital_id)
        if not batch:
            return None

        summary_results = (batch.results_summary or {}).get("results", [])
        return EmailBatchResponse(
            batch_id=batch.batch_id,
            is_async=batch.status in ("QUEUED", "PROCESSING"),
            total_patients=batch.total_count,
            sent_count=batch.sent_count,
            failed_count=batch.failed_count,
            skipped_count=batch.skipped_count,
            results=summary_results,
            message=f"Batch {batch.batch_id} status: {batch.status}",
        )

    # ─────────────────────────────────────────────────────────────────────────────
    # HELPER: TEMPLATE RENDERING
    # ─────────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _render_template_string(template_str: str, variables: dict[str, Any]) -> str:
        def replace(match):
            key = match.group(1).strip()
            return str(variables.get(key, f"{{{key}}}"))

        return re.sub(r"\{([a-zA-Z0-9_]+)\}", replace, template_str)

