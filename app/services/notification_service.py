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
        category: str | None = None,
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
            category=category,
        )
        total = await self.repo.count_user_notifications(
            user_id=user_id,
            is_read=is_read,
            notification_type=notification_type,
            category=category,
        )
        responses = [NotificationResponse.model_validate(item) for item in items]
        return build_paginated_result(responses, total, page, limit)

    async def get_unread_count(self, user_id: int) -> UnreadCountResponse:
        if not self.repo:
            raise ValueError("Database session required for NotificationService DB methods")

        count = await self.repo.get_unread_count(user_id)
        return UnreadCountResponse(unread_count=count)

    async def get_category_counts(self, user_id: int) -> dict[str, int]:
        if not self.repo:
            raise ValueError("Database session required for NotificationService DB methods")
        return await self.repo.get_category_counts(user_id)

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

        # 1. Preference Check for Critical Emergency Alerts
        if notification_type == "PATIENT_EMERGENCY_ALERT":
            from app.services.settings_service import SettingsService
            settings_service = SettingsService(self.db)
            prefs = await settings_service.get_user_preferences(user_id)
            if not prefs.get("critical_emergency_alerts", True):
                logger.info(
                    f"Skipping PATIENT_EMERGENCY_ALERT for user {user_id} "
                    f"due to critical_emergency_alerts preference."
                )
                return None

        # 2. DB Channel (with duplicate checking for same event)
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

        # 5. Browser Push Channel (Async & Fault-Tolerant via Celery)
        try:
            from app.services.settings_service import SettingsService
            settings_service = SettingsService(self.db)
            prefs = await settings_service.get_user_preferences(user_id)
            if prefs.get("push_notifications", True):
                from app.tasks.notification_tasks import send_browser_push_async
                send_browser_push_async.delay(user_id, title, message)
        except Exception as e:
            logger.warning(f"Failed to dispatch Browser Push for user {user_id}: {e}")

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

    async def create_critical_patient_alert(
        self,
        patient_id: int,
        message: str,
        reference_type: str = "PATIENT",
        reference_id: int | None = None,
    ) -> list[Notification]:
        if not self.db:
            return []

        from app.models.nurse_model import NursePatientAssignment, Nurse
        from app.models.user_model import User
        from sqlalchemy import select

        query = (
            select(User)
            .join(Nurse, Nurse.user_id == User.id)
            .join(NursePatientAssignment, NursePatientAssignment.nurse_id == Nurse.id)
            .where(
                NursePatientAssignment.patient_id == patient_id,
                NursePatientAssignment.status == "Active",
                User.is_active.is_(True)
            )
        )
        result = await self.db.execute(query)
        nurses = result.scalars().all()

        notifications = []
        for nurse_user in nurses:
            notif = await self.dispatch_notification(
                user_id=nurse_user.id,
                title="Critical Patient Alert",
                message=message,
                notification_type="CRITICAL_PATIENT_ALERT",
                reference_type=reference_type,
                reference_id=reference_id or patient_id,
                priority="HIGH",
                email=nurse_user.email,
                phone=nurse_user.phone,
            )
            if notif:
                notifications.append(notif)
        return notifications

    async def process_medication_reminders(self) -> int:
        if not self.db:
            return 0

        reminder_minutes = getattr(settings, "MEDICATION_REMINDER_MINUTES", 15)
        
        from datetime import timezone, timedelta, time
        ist_tz = timezone(timedelta(hours=5, minutes=30))
        now_ist = datetime.now(ist_tz)
        today_ist = now_ist.date()
        now_naive = now_ist.replace(tzinfo=None)

        from app.models.nurse_model import NursePrescription, NurseMedicationLog, Nurse, NursePatientAssignment
        from app.models.patient_model import Patient
        from app.models.user_model import User
        import json

        stmt = (
            select(NursePrescription)
            .options(selectinload(NursePrescription.patient))
            .where(
                NursePrescription.status == "active",
                NursePrescription.start_date <= today_ist,
                NursePrescription.end_date >= today_ist,
            )
        )
        res = await self.db.execute(stmt)
        prescriptions = res.scalars().all()

        if not prescriptions:
            return 0

        created_count = 0
        for presc in prescriptions:
            patient_name = f"{presc.patient.first_name} {presc.patient.last_name}".strip() if presc.patient else "Patient"

            time_of_day = json.loads(presc.time_of_day) if presc.time_of_day else ["Morning"]
            times = json.loads(presc.times) if presc.times else {}

            for slot in time_of_day:
                slot_time_str = times.get(slot, "08:00 AM")
                try:
                    t = datetime.strptime(slot_time_str, "%I:%M %p").time()
                except ValueError:
                    try:
                        t = datetime.strptime(slot_time_str, "%H:%M").time()
                    except ValueError:
                        continue

                scheduled_dt = datetime.combine(today_ist, t)
                time_diff_minutes = (scheduled_dt - now_naive).total_seconds() / 60.0

                if -5 <= time_diff_minutes <= reminder_minutes:
                    today_start = datetime.combine(today_ist, time.min)
                    today_end = datetime.combine(today_ist, time.max)

                    log_stmt = select(NurseMedicationLog).where(
                        NurseMedicationLog.prescription_id == presc.id,
                        NurseMedicationLog.time_of_day_slot == slot,
                        NurseMedicationLog.timestamp.between(today_start, today_end),
                        NurseMedicationLog.status.in_(["Administered", "Missed"])
                    )
                    log_res = await self.db.execute(log_stmt)
                    if log_res.scalars().all():
                        continue

                    nurse_stmt = (
                        select(User)
                        .join(Nurse, Nurse.user_id == User.id)
                        .join(NursePatientAssignment, NursePatientAssignment.nurse_id == Nurse.id)
                        .where(
                            NursePatientAssignment.patient_id == presc.patient_id,
                            NursePatientAssignment.status == "Active",
                            User.is_active.is_(True)
                        )
                    )
                    nurse_res = await self.db.execute(nurse_stmt)
                    assigned_nurses = nurse_res.scalars().all()

                    for nurse_user in assigned_nurses:
                        title = "Medication Reminder"
                        message = f"Medication reminder: Please administer {presc.medicine_name} ({presc.dosage}) to patient {patient_name} scheduled for {slot} ({slot_time_str})."

                        from sqlalchemy import func
                        dup_stmt = select(func.count(Notification.id)).where(
                            Notification.user_id == nurse_user.id,
                            Notification.notification_type == "MEDICATION_REMINDER",
                            Notification.reference_type == "MEDICATION",
                            Notification.reference_id == presc.id,
                            Notification.message == message,
                            Notification.created_at >= today_start
                        )
                        dup_res = await self.db.execute(dup_stmt)
                        if (dup_res.scalar() or 0) > 0:
                            continue

                        notif = await self.dispatch_notification(
                            user_id=nurse_user.id,
                            title=title,
                            message=message,
                            notification_type="MEDICATION_REMINDER",
                            reference_type="MEDICATION",
                            reference_id=presc.id,
                            priority="NORMAL",
                            email=nurse_user.email,
                            phone=nurse_user.phone
                        )
                        if notif:
                            created_count += 1

        return created_count

    async def notify_doctor_instruction(
        self,
        patient_id: int,
        message: str,
        reference_id: int | None = None,
    ) -> list[Notification]:
        if not self.db:
            return []

        from app.models.nurse_model import NursePatientAssignment, Nurse
        from app.models.user_model import User
        from sqlalchemy import select

        query = (
            select(User)
            .join(Nurse, Nurse.user_id == User.id)
            .join(NursePatientAssignment, NursePatientAssignment.nurse_id == Nurse.id)
            .where(
                NursePatientAssignment.patient_id == patient_id,
                NursePatientAssignment.status == "Active",
                User.is_active.is_(True)
            )
        )
        result = await self.db.execute(query)
        nurses = result.scalars().all()

        notifications = []
        for nurse_user in nurses:
            from sqlalchemy import func
            dup_stmt = select(func.count(Notification.id)).where(
                Notification.user_id == nurse_user.id,
                Notification.notification_type == "DOCTOR_INSTRUCTION",
                Notification.message == message,
                Notification.is_deleted.is_(False)
            )
            dup_res = await self.db.execute(dup_stmt)
            if (dup_res.scalar() or 0) > 0:
                continue

            notif = await self.dispatch_notification(
                user_id=nurse_user.id,
                title="Doctor's Instruction",
                message=message,
                notification_type="DOCTOR_INSTRUCTION",
                reference_type="PATIENT",
                reference_id=reference_id or patient_id,
                priority="NORMAL",
                email=nurse_user.email,
                phone=nurse_user.phone,
            )
            if notif:
                notifications.append(notif)
        return notifications
