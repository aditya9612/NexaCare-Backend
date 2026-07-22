import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.doctor_model import Doctor
from app.models.lab_model import TestOrder, TestResult
from app.models.notification_model import Notification
from app.models.patient_model import Patient
from app.models.role_model import Role
from app.models.user_model import User
from app.repositories.notification_repository import NotificationRepository
from app.schemas.notification_schema import NotificationResponse, UnreadCountResponse
from app.utils.email_sender import send_email
from app.utils.helpers import utc_now
from app.utils.pagination import build_paginated_result
from app.utils.sms_sender import send_sms
from app.utils.whatsapp_sender import send_whatsapp
from app.websocket.notification_socket import notification_manager

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, db: AsyncSession | None = None):
        self.db = db
        self.repo = NotificationRepository(db) if db else None

    @staticmethod
    async def notify_appointment_reminder(email: str, phone: str | None, message: str):
        try:
            await send_email(email, "Appointment Reminder", message)
        except Exception as exc:
            logger.warning("Appointment reminder email failed: %s", exc)

        if phone:
            try:
                await send_sms(phone, message)
                await send_whatsapp(phone, message)
            except Exception as exc:
                logger.warning("Appointment reminder SMS/WhatsApp failed: %s", exc)

    # --- Notification Bell UI API Methods ---
    async def list_user_notifications(
        self,
        user_id: int,
        page: int = 1,
        limit: int = 20,
        is_read: bool | None = None,
        notification_type: str | None = None,
    ) -> dict[str, Any]:
        if not self.repo:
            raise ValueError("Database session required for NotificationService DB methods")

        skip = (page - 1) * limit
        items = await self.repo.list_user_notifications(
            user_id=user_id,
            skip=skip,
            limit=limit,
            is_read=is_read,
            notification_type=notification_type,
        )
        total = await self.repo.count_user_notifications(
            user_id=user_id,
            is_read=is_read,
            notification_type=notification_type,
        )
        responses = [NotificationResponse.model_validate(item) for item in items]
        return build_paginated_result(responses, total, page, limit)

    async def get_unread_count(self, user_id: int) -> UnreadCountResponse:
        if not self.repo:
            raise ValueError("Database session required for NotificationService DB methods")

        count = await self.repo.get_unread_count(user_id)
        return UnreadCountResponse(unread_count=count)

    async def mark_as_read(self, notification_id: int, user_id: int) -> NotificationResponse:
        if not self.repo:
            raise ValueError("Database session required for NotificationService DB methods")

        notification = await self.repo.get_by_id(notification_id)
        if not notification:
            raise NotFoundException(f"Notification with ID {notification_id} not found")

        if notification.user_id != user_id:
            raise ForbiddenException("You can only access and update your own notifications")

        updated = await self.repo.mark_as_read(notification_id, user_id)
        return NotificationResponse.model_validate(updated)

    async def mark_all_as_read(self, user_id: int) -> dict[str, Any]:
        if not self.repo:
            raise ValueError("Database session required for NotificationService DB methods")

        count = await self.repo.mark_all_as_read(user_id)
        return {"message": "All notifications marked as read", "updated_count": count}

    # --- Centralized Multichannel Dispatch Engine ---
    async def dispatch_notification(
        self,
        user_id: int,
        title: str,
        message: str,
        notification_type: str,
        reference_type: str | None = None,
        reference_id: int | None = None,
        priority: str = "NORMAL",
        email: str | None = None,
        email_subject: str | None = None,
        email_html: str | None = None,
        phone: str | None = None,
    ) -> Notification | None:
        if not self.repo:
            raise ValueError("Database session required for NotificationService DB methods")

        # 1. DB Channel (with duplicate checking for same event)
        if await self.repo.exists_duplicate(
            user_id=user_id,
            notification_type=notification_type,
            reference_type=reference_type,
            reference_id=reference_id,
        ):
            logger.info(
                f"Skipping duplicate notification: user={user_id}, type={notification_type}, "
                f"ref_type={reference_type}, ref_id={reference_id}"
            )
            return None

        notification = Notification(
            user_id=user_id,
            title=title,
            message=message,
            notification_type=notification_type,
            reference_type=reference_type,
            reference_id=reference_id,
            priority=priority,
            is_read=False,
        )
        created = await self.repo.create(notification)

        # 2. WebSocket Channel (Real-time Bell UI Push)
        try:
            payload = {
                "type": "notification",
                "data": NotificationResponse.model_validate(created).model_dump(mode="json"),
            }
            await notification_manager.send_to_user(user_id, payload)
        except Exception as e:
            logger.warning(f"Failed to push WebSocket notification to user {user_id}: {e}")

        # 3. Email Channel (Async & Fault-Tolerant)
        if email:
            try:
                subject = email_subject or title
                body = email_html or f"<p>{message}</p>"
                asyncio.create_task(send_email(email, subject, body))
            except Exception as e:
                logger.warning(f"Failed to dispatch email notification to {email}: {e}")

        # 4. SMS Channel (Async & Fault-Tolerant)
        if phone:
            try:
                asyncio.create_task(send_sms(phone, message))
            except Exception as e:
                logger.warning(f"Failed to dispatch SMS notification to {phone}: {e}")

        return created

    # --- Backward-compatible internal helper ---
    async def create_notification_internal(
        self,
        user_id: int,
        title: str,
        message: str,
        notification_type: str,
        reference_type: str | None = None,
        reference_id: int | None = None,
        priority: str = "NORMAL",
    ) -> Notification | None:
        return await self.dispatch_notification(
            user_id=user_id,
            title=title,
            message=message,
            notification_type=notification_type,
            reference_type=reference_type,
            reference_id=reference_id,
            priority=priority,
        )

    # --- Appointment Notification Helper ---
    async def notify_appointment_confirmation(
        self,
        user_id: int,
        appointment_number: str,
        patient_name: str,
        doctor_name: str,
        appointment_date: str,
        appointment_time: str,
        email: str | None = None,
        phone: str | None = None,
    ) -> Notification | None:
        title = "Appointment Confirmed"
        message = f"Your appointment {appointment_number} with Dr. {doctor_name} on {appointment_date} at {appointment_time} has been confirmed."

        email_html = f"""
        <h3>Appointment Confirmation</h3>
        <p>Dear {patient_name},</p>
        <p>Your appointment <strong>#{appointment_number}</strong> has been confirmed.</p>
        <ul>
            <li><strong>Doctor:</strong> Dr. {doctor_name}</li>
            <li><strong>Date:</strong> {appointment_date}</li>
            <li><strong>Time:</strong> {appointment_time}</li>
        </ul>
        <p>Thank you for choosing NexaCare HMS.</p>
        """

        return await self.dispatch_notification(
            user_id=user_id,
            title=title,
            message=message,
            notification_type="APPOINTMENT_CONFIRMATION",
            reference_type="APPOINTMENT",
            reference_id=None,
            priority="NORMAL",
            email=email,
            email_subject=f"Appointment Confirmation #{appointment_number}",
            email_html=email_html,
            phone=phone,
        )

    # --- Doctor Appointment Reminder Helper ---
    async def notify_doctor_appointment_reminder(
        self,
        user_id: int,
        appointment_id: int,
        appointment_number: str,
        patient_name: str,
        appointment_date: str,
        appointment_time: str,
        email: str | None = None,
        phone: str | None = None,
    ) -> Notification | None:
        title = "Upcoming Appointment Reminder"
        message = f"Reminder: You have an upcoming appointment #{appointment_number} with Patient {patient_name} scheduled on {appointment_date} at {appointment_time}."

        email_html = f"""
        <h3>Upcoming Appointment Reminder</h3>
        <p>Dear Doctor,</p>
        <p>You have an upcoming appointment scheduled:</p>
        <ul>
            <li><strong>Appointment #:</strong> {appointment_number}</li>
            <li><strong>Patient:</strong> {patient_name}</li>
            <li><strong>Date:</strong> {appointment_date}</li>
            <li><strong>Time:</strong> {appointment_time}</li>
        </ul>
        <p>Please be ready for consultation.</p>
        """

        return await self.dispatch_notification(
            user_id=user_id,
            title=title,
            message=message,
            notification_type="DOCTOR_APPOINTMENT_REMINDER",
            reference_type="APPOINTMENT",
            reference_id=appointment_id,
            priority="NORMAL",
            email=email,
            email_subject=f"Reminder: Upcoming Appointment #{appointment_number} with {patient_name}",
            email_html=email_html,
            phone=phone,
        )

    async def process_doctor_appointment_reminders(self) -> int:
        if not self.db or not self.repo:
            return 0

        from datetime import date, datetime
        from app.models.appointment_model import Appointment
        from app.core.constants import AppointmentStatus

        reminder_minutes = getattr(settings, "DOCTOR_APPOINTMENT_REMINDER_MINUTES", 30)
        today = date.today()

        excluded_statuses = [
            AppointmentStatus.CANCELLED,
            AppointmentStatus.COMPLETED,
            "cancelled",
            "completed",
            "no_show",
            "no-show",
        ]

        stmt = (
            select(Appointment)
            .options(
                selectinload(Appointment.doctor),
                selectinload(Appointment.patient),
            )
            .where(
                Appointment.appointment_status.notin_(excluded_statuses),
                Appointment.appointment_date >= today,
            )
        )
        res = await self.db.execute(stmt)
        appointments = res.scalars().all()

        if not appointments:
            return 0

        created_count = 0
        now = utc_now()

        for appt in appointments:
            if not appt.doctor or not appt.doctor.user_id:
                continue

            appt_datetime = datetime.combine(appt.appointment_date, appt.appointment_time)
            time_diff = (appt_datetime - now.replace(tzinfo=None)).total_seconds() / 60.0

            if -15 <= time_diff <= reminder_minutes:
                patient_name = f"{appt.patient.first_name} {appt.patient.last_name}".strip() if appt.patient else "Patient"
                doctor_user_id = appt.doctor.user_id
                doctor_email = appt.doctor.email
                doctor_phone = appt.doctor.phone

                notif = await self.notify_doctor_appointment_reminder(
                    user_id=doctor_user_id,
                    appointment_id=appt.id,
                    appointment_number=appt.appointment_number,
                    patient_name=patient_name,
                    appointment_date=str(appt.appointment_date),
                    appointment_time=str(appt.appointment_time),
                    email=doctor_email,
                    phone=doctor_phone,
                )
                if notif:
                    created_count += 1

        return created_count

    # --- Feature 1: Lab Critical Value Alert ---
    async def create_critical_value_alert(self, result: TestResult, order: TestOrder) -> Notification | None:
        if not self.db or not self.repo:
            return None

        if not result.is_critical:
            return None

        if not order.doctor_id:
            logger.warning(f"TestOrder {order.id} has no assigned doctor; skipping critical alert.")
            return None

        doc_res = await self.db.execute(
            select(Doctor).where(Doctor.id == order.doctor_id, Doctor.is_deleted.is_(False))
        )
        doctor = doc_res.scalar_one_or_none()
        if not doctor or not doctor.user_id:
            logger.warning(f"Doctor ID {order.doctor_id} has no valid user_id; skipping critical alert.")
            return None

        patient_name = "Unknown Patient"
        patient_email = None
        patient_phone = None
        if order.patient_id:
            pat_res = await self.db.execute(
                select(Patient).where(Patient.id == order.patient_id, Patient.is_deleted.is_(False))
            )
            patient = pat_res.scalar_one_or_none()
            if patient:
                patient_name = f"{patient.first_name} {patient.last_name}".strip()
                patient_email = patient.email
                patient_phone = patient.phone

        test_name = "Lab Test"
        if hasattr(order, "lab_test") and order.lab_test:
            test_name = order.lab_test.test_name
        elif order.lab_test_id:
            from app.models.lab_model import LabTest
            lt_res = await self.db.execute(
                select(LabTest).where(LabTest.id == order.lab_test_id)
            )
            lt = lt_res.scalar_one_or_none()
            if lt:
                test_name = lt.test_name

        title = "Critical Lab Result"
        message = f"Critical value detected for {test_name} (Parameter: {result.parameter_name}, Value: {result.result_value}) of Patient {patient_name}."
        doctor_email = doctor.email

        return await self.dispatch_notification(
            user_id=doctor.user_id,
            title=title,
            message=message,
            notification_type="CRITICAL_VALUE",
            reference_type="TEST_RESULT",
            reference_id=result.id,
            priority="HIGH",
            email=doctor_email,
            email_subject=f"URGENT: Critical Lab Result - {patient_name}",
            phone=doctor.phone,
        )

    # --- Feature 2: Lab Pending Test Reminder ---
    async def process_pending_test_reminders(self) -> int:
        if not self.db or not self.repo:
            return 0

        threshold_hours = getattr(settings, "LAB_PENDING_TEST_THRESHOLD_HOURS", 24)
        threshold_dt = utc_now() - timedelta(hours=threshold_hours)
        excluded_statuses = ["completed", "approved", "cancelled"]

        stmt = (
            select(TestOrder)
            .options(selectinload(TestOrder.lab_test))
            .where(
                TestOrder.is_deleted.is_(False),
                TestOrder.status.notin_(excluded_statuses),
                TestOrder.ordered_at <= threshold_dt,
            )
        )
        res = await self.db.execute(stmt)
        pending_orders = res.scalars().all()

        if not pending_orders:
            return 0

        tech_stmt = (
            select(User)
            .join(Role, User.role_id == Role.id)
            .where(
                User.is_active.is_(True),
                func.lower(Role.name).in_(["lab technician", "lab_technician"]),
            )
        )
        tech_res = await self.db.execute(tech_stmt)
        lab_techs = tech_res.scalars().all()

        if not lab_techs:
            logger.warning("No active Lab Technicians found to send pending test reminders.")
            return 0

        created_count = 0
        for order in pending_orders:
            patient_name = "Unknown Patient"
            if order.patient_id:
                pat_res = await self.db.execute(
                    select(Patient).where(Patient.id == order.patient_id, Patient.is_deleted.is_(False))
                )
                patient = pat_res.scalar_one_or_none()
                if patient:
                    patient_name = f"{patient.first_name} {patient.last_name}".strip()

            test_name = order.lab_test.test_name if order.lab_test else "Lab Test"
            title = "Pending Test Reminder"
            message = f"{test_name} for Patient {patient_name} is still pending."

            for tech in lab_techs:
                notif = await self.dispatch_notification(
                    user_id=tech.id,
                    title=title,
                    message=message,
                    notification_type="PENDING_TEST",
                    reference_type="TEST_ORDER",
                    reference_id=order.id,
                    priority="NORMAL",
                    email=tech.email,
                )
                if notif:
                    created_count += 1

        return created_count
