from datetime import date, datetime, time

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AppointmentStatus, BookingSource
from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.models.appointment_model import Appointment
from app.repositories.appointment_repository import AppointmentRepository
from app.repositories.audit_repository import AuditRepository
from app.repositories.discharge_repository import DischargeRepository
from app.repositories.doctor_repository import DoctorRepository
from app.repositories.patient_repository import PatientRepository
from app.schemas.appointment_schema import (
    AppointmentCreate,
    AppointmentResponse,
    AppointmentUpdate,
    CancelRequest,
    ConfirmRequest,
    RescheduleRequest,
    TokenResponse,
    ConfirmedVisitResponse,
    ScheduledDoctorResponse,
    AdmitRecommendationRequest,
    AdmitRecommendationResponse,
    PendingAdmissionItem,
    PendingAdmissionPatientInfo,
    PendingAdmissionDoctorInfo,
    EmergencyTriageRequest,
    EmergencyDispositionRequest,
)
from app.utils.helpers import generate_appointment_number
from app.utils.pagination import build_paginated_result


class AppointmentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AppointmentRepository(db)
        self.patient_repo = PatientRepository(db)
        self.audit_repo = AuditRepository(db)
        from app.services.booking_validation_service import BookingValidationService
        self.validation_service = BookingValidationService(db)
        self.audit_repo = AuditRepository(db)
        self.doctor_repo = DoctorRepository(db)
        self.discharge_repo = DischargeRepository(db)

    def _validate_future_datetime(self, appointment_date: date, appointment_time: time) -> tuple[date, time]:
        from datetime import timezone, timedelta

        ist_tz = timezone(timedelta(hours=5, minutes=30))
        now_ist = datetime.now(ist_tz)
        today_ist = now_ist.date()

        if appointment_time is not None:
            if appointment_time.tzinfo is not None:
                import datetime as dt_module
                appt_dt = dt_module.datetime.combine(appointment_date, appointment_time)
                appt_dt_ist = appt_dt.astimezone(ist_tz)
                appointment_date = appt_dt_ist.date()
                appointment_time = appt_dt_ist.time().replace(tzinfo=None)

        if appointment_date < today_ist:
            raise BadRequestException("Cannot book or reschedule an appointment for a past date")

        if appointment_date == today_ist and appointment_time is not None:
            appointment_time_naive = appointment_time.replace(tzinfo=None)
            now_time_ist_naive = now_ist.time().replace(tzinfo=None)
            if appointment_time_naive < now_time_ist_naive:
                raise BadRequestException(
                    "Cannot book or reschedule an appointment for a past time slot today"
                )

        return appointment_date, appointment_time

    async def _validate_entities(self, patient_id: int, doctor_id: int) -> None:
        patient = await self.patient_repo.get_by_id(patient_id)
        if not patient:
            raise NotFoundException("Patient not found")

        from app.core.constants import PatientStatus
        if patient.status == PatientStatus.INACTIVE:
            raise BadRequestException(
                "Cannot create an appointment for an inactive patient. Please activate the patient before booking an appointment."
            )
        doctor = await self.doctor_repo.get_by_id(doctor_id)
        if not doctor:
            raise NotFoundException("Doctor not found")
        status = (doctor.availability_status or "available").lower().strip()
        if status not in ("available", "busy"):
            raise ConflictException("Doctor is not available for appointments")



    async def list_appointments(
        self,
        page: int = 1,
        size: int = 20,
        patient_id: int | None = None,
        doctor_id: int | None = None,
        department_id: int | None = None,
        status: str | None = None,
        appointment_date: date | None = None,
        date_filter: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        appointment_type: str | None = None,
        booking_source: BookingSource | str | None = None,
        admission_status: str | None = None,
        triage_level: int | None = None,
        disposition: str | None = None,
    ):
        if date_filter is not None:
            valid_filters = {"today", "yesterday", "last_7_days", "last_30_days", "last_3_months", "overall", "custom"}
            if date_filter not in valid_filters:
                raise BadRequestException(f"Invalid date_filter. Must be one of: {', '.join(sorted(valid_filters))}")
            
            if date_filter == "custom":
                if not start_date or not end_date:
                    raise BadRequestException("Both start_date and end_date are required when date_filter is 'custom'")
                if start_date > end_date:
                    raise BadRequestException("start_date cannot be greater than end_date")

        filter_start = None
        filter_end = None

        if date_filter:
            from datetime import timezone, timedelta
            ist_tz = timezone(timedelta(hours=5, minutes=30))
            today = datetime.now(ist_tz).date()

            if date_filter == "today":
                filter_start = today
                filter_end = today
            elif date_filter == "yesterday":
                yesterday = today - timedelta(days=1)
                filter_start = yesterday
                filter_end = yesterday
            elif date_filter == "last_7_days":
                filter_start = today - timedelta(days=7)
                filter_end = today
            elif date_filter == "last_30_days":
                filter_start = today - timedelta(days=30)
                filter_end = today
            elif date_filter == "last_3_months":
                import calendar
                month = today.month - 3
                year = today.year
                if month <= 0:
                    year -= 1
                    month += 12
                day = min(today.day, calendar.monthrange(year, month)[1])
                filter_start = date(year, month, day)
                filter_end = today
            elif date_filter == "custom":
                filter_start = start_date
                filter_end = end_date
            # For "overall", filter_start and filter_end remain None

        skip = (page - 1) * size
        source = booking_source.value if isinstance(booking_source, BookingSource) else booking_source
        items = await self.repo.list_all(
            skip=skip, limit=size, patient_id=patient_id, doctor_id=doctor_id,
            department_id=department_id, status=status, appointment_date=appointment_date,
            start_date=filter_start, end_date=filter_end,
            appointment_type=appointment_type, booking_source=source,
            admission_status=admission_status, triage_level=triage_level, disposition=disposition,
        )
        total = await self.repo.count_all(
            patient_id=patient_id, doctor_id=doctor_id,
            department_id=department_id, status=status, appointment_date=appointment_date,
            start_date=filter_start, end_date=filter_end,
            appointment_type=appointment_type, booking_source=source,
            admission_status=admission_status, triage_level=triage_level, disposition=disposition,
        )

        # --- Optimized summary counts via grouped SQL (replaces 10 sequential count_all calls) ---
        from app.utils.helpers import utc_now
        from sqlalchemy import and_, case, func, or_, select, text
        # Calculate summary counts independently of pagination and status/date filters where appropriate
        from app.utils.helpers import get_today_ist, utc_now
        today = utc_now().date()

        def _base_filter(q):
            """Apply patient/doctor/dept scope filters — no status/date filter."""
            if patient_id:
                q = q.where(Appointment.patient_id == patient_id)
            if doctor_id:
                q = q.where(Appointment.doctor_id == doctor_id)
            if department_id:
                q = q.where(Appointment.department_id == department_id)
            return q

        # Query 1: aggregate over all appointments (no date/status filter) — total + today
        q_all = _base_filter(
            select(
                func.count().label("total"),
                func.sum(case((Appointment.appointment_date == today, 1), else_=0)).label("today"),
            ).select_from(Appointment)
        )
        all_row = (await self.db.execute(q_all)).one()
        total_appointments = all_row.total or 0
        today_appointments = all_row.today or 0

        # Query 2: aggregate status breakdown scoped by date & other optional filters
        q_status = _base_filter(
            select(
                Appointment.appointment_status,
                Appointment.queue_status,
                Appointment.admission_status,
                Appointment.admission_recommended,
                func.count().label("cnt"),
            ).select_from(Appointment)
        )
        if appointment_date:
            q_status = q_status.where(Appointment.appointment_date == appointment_date)

        rows = (await self.db.execute(q_status.group_by(
            Appointment.appointment_status,
            Appointment.queue_status,
            Appointment.admission_status,
            Appointment.admission_recommended,
        ))).all()

        # Python-side bucketing — matches the semantics of the original count_all filter branches
        _CONFIRMED_SET = {"Confirmed", "confirmed", "CONFIRMED"}
        _PENDING_SET = {"Pending", "pending", "PENDING"}
        _COMPLETED_SET = {"Completed", "completed", "COMPLETED"}
        _CANCELLED_SET = {"Cancelled", "cancelled", "CANCELLED", "Canceled", "canceled", "No Show", "no show", "NO SHOW", "No-Show", "no-show"}
        _CHECKED_IN_SET = {"Checked-In", "Check-in", "checked-in", "checked_in", "Check-In"}
        _CHECKED_OUT_SET = {"Checked-Out", "Checked-out", "checked-out", "Check-out", "Check-Out"}
        _IN_PROGRESS_STATUS = {"In-Progress", "in-progress", "In-progress", "in_progress", "In_Progress"}
        _IN_PROGRESS_QUEUE = {"IN_CONSULTATION", "in_consultation", "IN-PROGRESS", "in-progress"}
        _WAITING_QUEUE = {"WAITING"}
        _ADMIT_REC_STATUS = {"Admit Recommended", "admit recommended", "Admit-Recommended", "admit-recommended", "admit_recommended"}
        _ADMITTED_STATUS = {"Admitted", "admitted", "ADMITTED"}

        completed = pending = confirmed = in_progress = checked_in = checked_out = 0
        waiting = admit_recommended = admitted = 0
        total_scheduled = 0

        for row in rows:
            appt_status = row.appointment_status or ""
            queue_status = row.queue_status or ""
            adm_status = row.admission_status or ""
            adm_rec = bool(row.admission_recommended)
            cnt = row.cnt

            if appt_status in _COMPLETED_SET:
                completed += cnt
            elif appt_status in _PENDING_SET:
                pending += cnt
                total_scheduled += cnt
            elif appt_status in _CONFIRMED_SET:
                confirmed += cnt
                total_scheduled += cnt
            elif appt_status in _CHECKED_IN_SET:
                checked_in += cnt
            elif appt_status in _CHECKED_OUT_SET:
                checked_out += cnt
            elif appt_status in _CANCELLED_SET:
                cancelled_no_show_cnt = cnt  # counted below in total
                pass
            elif appt_status in _IN_PROGRESS_STATUS or queue_status in _IN_PROGRESS_QUEUE:
                in_progress += cnt
            elif queue_status.upper() in _WAITING_QUEUE:
                waiting += cnt
            if appt_status in _ADMIT_REC_STATUS or adm_status in _ADMIT_REC_STATUS or adm_rec:
                admit_recommended += cnt
            if appt_status in _ADMITTED_STATUS or adm_status in _ADMITTED_STATUS:
                admitted += cnt

        # cancelled = CANCELLED + NO_SHOW statuses combined
        cancelled = sum(
            row.cnt for row in rows
            if (row.appointment_status or "") in _CANCELLED_SET
        today_ist = get_today_ist()
        
        total_appointments = await self.repo.count_all(
            patient_id=patient_id, doctor_id=doctor_id, department_id=department_id
        )
        today_appointments = await self.repo.count_all(
            patient_id=patient_id, doctor_id=doctor_id, department_id=department_id,
            appointment_date=today
        )
        total_today_discharged = await self.discharge_repo.count_today_discharged(on_date=today_ist)
        total_scheduled = await self.repo.count_all(
            patient_id=patient_id, doctor_id=doctor_id, department_id=department_id,
            status=[AppointmentStatus.CONFIRMED, AppointmentStatus.PENDING], appointment_date=appointment_date
        )
        completed = await self.repo.count_all(
            patient_id=patient_id, doctor_id=doctor_id, department_id=department_id,
            status=AppointmentStatus.COMPLETED, appointment_date=appointment_date
        )
        cancelled = await self.repo.count_all(
            patient_id=patient_id, doctor_id=doctor_id, department_id=department_id,
            status=[AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW], appointment_date=appointment_date
        )
        pending = await self.repo.count_all(
            patient_id=patient_id, doctor_id=doctor_id, department_id=department_id,
            status=AppointmentStatus.PENDING, appointment_date=appointment_date
        )
        confirmed = await self.repo.count_all(
            patient_id=patient_id, doctor_id=doctor_id, department_id=department_id,
            status=AppointmentStatus.CONFIRMED, appointment_date=appointment_date
        )

        in_progress = await self.repo.count_all(
            patient_id=patient_id, doctor_id=doctor_id, department_id=department_id,
            status="In-Progress", appointment_date=appointment_date
        )
        checked_in = await self.repo.count_all(
            patient_id=patient_id, doctor_id=doctor_id, department_id=department_id,
            status="Check-in", appointment_date=appointment_date
        )
        checked_out = await self.repo.count_all(
            patient_id=patient_id, doctor_id=doctor_id, department_id=department_id,
            status="Checked-Out", appointment_date=appointment_date
        )
        admit_recommended = await self.repo.count_all(
            patient_id=patient_id, doctor_id=doctor_id, department_id=department_id,
            status="admit-recommended", appointment_date=appointment_date
        )
        admitted = await self.repo.count_all(
            patient_id=patient_id, doctor_id=doctor_id, department_id=department_id,
            status="admitted", appointment_date=appointment_date
        )
        waiting = await self.repo.count_all(
            patient_id=patient_id, doctor_id=doctor_id, department_id=department_id,
            status="waiting", appointment_date=appointment_date
        )

        paginated = build_paginated_result(
            [AppointmentResponse.model_validate(a) for a in items], total, page, size
        )
        return {
            "items": paginated.items,
            "total": paginated.total,
            "page": paginated.page,
            "size": paginated.size,
            "pages": paginated.pages,
            "total_appointments": total_appointments,
            "today_appointments": today_appointments,
            "total_today_appointments": today_appointments,
            "total_today_tokens": today_appointments,
            "total_today_discharged": total_today_discharged,
            "total_scheduled": total_scheduled,
            "completed": completed,
            "cancelled": cancelled,
            "pending": pending,
            "confirmed": confirmed,
            "in_progress": in_progress,
            "checked_in": checked_in,
            "checked_out": checked_out,
            "waiting": waiting,
            "admit_recommended": admit_recommended,
            "admitted": admitted,
        }

    async def get_by_id(self, appointment_id: int) -> AppointmentResponse:
        appointment = await self.repo.get_by_id(appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
        return AppointmentResponse.model_validate(appointment)

    async def get_token(self, appointment_id: int) -> TokenResponse:
        appointment = await self.repo.get_by_id(appointment_id)

        if not appointment:
            raise NotFoundException("Appointment not found")

        if not appointment.token_number:
            raise BadRequestException("Token not generated for this appointment")

        return TokenResponse(
            appointment_id=appointment.id,
            token_number=appointment.token_number,
        )

    async def _notify_confirmation_safely(self, appointment: Appointment, target_user_id: int):
        try:
            patient = await self.patient_repo.get_by_id(appointment.patient_id)
            doctor = await self.doctor_repo.get_by_id(appointment.doctor_id)
            patient_name = f"{patient.first_name} {patient.last_name}".strip() if patient else "Patient"
            doctor_name = f"{doctor.first_name} {doctor.last_name}".strip() if doctor else "Doctor"
            email = patient.email if patient else None
            phone = patient.phone if patient else None
            user_target = (patient.user_id if patient and patient.user_id else None) or target_user_id

            from app.services.notification_service import NotificationService
            await NotificationService(self.db).notify_appointment_confirmation(
                user_id=user_target,
                appointment_number=appointment.appointment_number,
                patient_name=patient_name,
                doctor_name=doctor_name,
                appointment_date=str(appointment.appointment_date),
                appointment_time=str(appointment.appointment_time),
                email=email,
                phone=phone,
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Failed to dispatch appointment notification: %s", exc)

    async def create(self, data: AppointmentCreate, user_id: int) -> AppointmentResponse:
        data.appointment_date, data.appointment_time = self._validate_future_datetime(data.appointment_date, data.appointment_time)
        await self._validate_entities(data.patient_id, data.doctor_id)
        rules = await self.validation_service.validate(data.doctor_id, data.appointment_date, data.appointment_time)

        token = await self.repo.get_next_token(data.doctor_id, data.appointment_date)
        queue_tok = await self.repo.get_next_queue_token(data.appointment_date)
        appointment_data = data.model_dump(exclude={"patient_name", "age", "patient_mobile_number"})
        if not appointment_data.get("booking_source"):
            appointment_data["booking_source"] = BookingSource.STAFF
        appointment = Appointment(
            appointment_number=generate_appointment_number(),
            token_number=token,
            queue_token=queue_tok,
            queue_status="WAITING",
            appointment_status=AppointmentStatus.PENDING,
            **appointment_data,
        )
        appointment = await self.repo.create(appointment)
        await self.audit_repo.create("create", "appointments", user_id=user_id, resource_id=str(appointment.id))
        await self._notify_confirmation_safely(appointment, user_id)
        return AppointmentResponse.model_validate(appointment)


    async def update(self, appointment_id: int, data: AppointmentUpdate, user_id: int) -> AppointmentResponse:
        appointment = await self.repo.get_by_id(appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")

        update_data = data.model_dump(exclude_unset=True)
        if "appointment_status" in update_data:
            new_status = update_data["appointment_status"]
            if new_status == AppointmentStatus.CONFIRMED:
                from app.models.user_model import User
                from sqlalchemy import select
                from sqlalchemy.orm import selectinload
                from app.core.constants import UserRole
                from app.core.exceptions import ForbiddenException
                
                user_res = await self.db.execute(
                    select(User)
                    .where(User.id == user_id)
                    .options(selectinload(User.role))
                )
                user_obj = user_res.scalar_one_or_none()
                if not user_obj:
                    raise ForbiddenException("User not found")
                role_name = user_obj.role.name if user_obj.role else ""
                if role_name not in UserRole.ADMIN_ROLES:
                    from app.repositories.rbac_repository import RBACRepository
                    rbac_repo = RBACRepository(self.db)
                    permissions = await rbac_repo.get_user_permissions(user_obj.role_id)
                    if "appointments:approve" not in permissions:
                        raise ForbiddenException("Missing permission: appointments:approve")
                        
                if appointment.appointment_status == "Checked-In":
                    raise BadRequestException("Cannot confirm an appointment that is already checked in")
                elif appointment.appointment_status == AppointmentStatus.COMPLETED:
                    raise BadRequestException("Cannot confirm a completed appointment")
                elif appointment.appointment_status == "Checked-Out":
                    raise BadRequestException("Cannot confirm a checked-out appointment")
                elif appointment.appointment_status == AppointmentStatus.CANCELLED:
                    raise BadRequestException("Cannot confirm a cancelled appointment")
                elif appointment.appointment_status == AppointmentStatus.NO_SHOW:
                    raise BadRequestException("Cannot confirm a no-show appointment")
            elif new_status in (AppointmentStatus.COMPLETED, "Checked-Out"):
                raise BadRequestException(f"Direct update to '{new_status}' status is not allowed. Please use the dedicated lifecycle endpoints.")


        if appointment.appointment_status in AppointmentStatus.TERMINAL:
            # allow purely notes update if status isn't changing to a non-terminal state
            if "appointment_status" in update_data and update_data["appointment_status"] != appointment.appointment_status:
                raise BadRequestException("Cannot change status of a terminal appointment")
        # Prevent updating status directly to Completed without Check-In and Check-Out
        if update_data.get("appointment_status") == AppointmentStatus.COMPLETED:
            if not appointment.check_in_time or not appointment.check_out_time:
                raise BadRequestException(
                    "Cannot set appointment status to Completed without both Check-In and Check-Out being marked."
                )

        new_date = update_data.get("appointment_date", appointment.appointment_date)
        new_time = update_data.get("appointment_time", appointment.appointment_time)

        if "appointment_date" in update_data or "appointment_time" in update_data:
            new_date, new_time = self._validate_future_datetime(new_date, new_time)
            if "appointment_date" in update_data:
                update_data["appointment_date"] = new_date
            if "appointment_time" in update_data:
                update_data["appointment_time"] = new_time

        if "appointment_date" in update_data or "appointment_time" in update_data:
            rules = await self.validation_service.validate(appointment.doctor_id, new_date, new_time, exclude_id=appointment_id)

        for key, value in update_data.items():
            setattr(appointment, key, value)
        if appointment.appointment_status in (AppointmentStatus.CANCELLED, "Cancelled", "cancelled"):
            appointment.queue_status = "CANCELLED"
        elif appointment.appointment_status in (AppointmentStatus.COMPLETED, "Completed", "completed", "Checked-Out", "checked-out"):
            if not appointment.queue_status or appointment.queue_status in ("WAITING", "CALLED"):
                appointment.queue_status = "COMPLETED"
        elif appointment.appointment_status in (AppointmentStatus.NO_SHOW, "No Show", "no-show", "no_show"):
            appointment.queue_status = "SKIPPED"
        appointment = await self.repo.update(appointment)
        await self.audit_repo.create("update", "appointments", user_id=user_id, resource_id=str(appointment.id))
        return AppointmentResponse.model_validate(appointment)

    async def delete(self, appointment_id: int, user_id: int) -> None:
        appointment = await self.repo.get_by_id(appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
        await self.repo.delete(appointment)
        await self.audit_repo.create("delete", "appointments", user_id=user_id, resource_id=str(appointment.id))

    async def reschedule(self, data: RescheduleRequest, user_id: int) -> AppointmentResponse:
        appointment = await self.repo.get_by_id(data.appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
        if appointment.appointment_status in AppointmentStatus.TERMINAL:
            raise BadRequestException("Cannot reschedule a terminal appointment")
        new_date, new_time = self._validate_future_datetime(data.appointment_date, data.appointment_time)
        rules = await self.validation_service.validate(
            appointment.doctor_id, new_date, new_time, exclude_id=appointment.id
        )
        appointment.appointment_date = new_date
        appointment.appointment_time = new_time
        appointment.appointment_status = AppointmentStatus.PENDING
        if data.notes:
            appointment.notes = data.notes
        appointment = await self.repo.update(appointment)
        await self.audit_repo.create("reschedule", "appointments", user_id=user_id, resource_id=str(appointment.id))

        try:
            patient = await self.patient_repo.get_by_id(appointment.patient_id)
            doctor = await self.doctor_repo.get_by_id(appointment.doctor_id)
            doctor_name = f"{doctor.first_name} {doctor.last_name}".strip() if doctor else "Doctor"
            user_target = (patient.user_id if patient and patient.user_id else None) or user_id

            from app.services.notification_service import NotificationService
            await NotificationService(self.db).dispatch_notification(
                user_id=user_target,
                title="Appointment Rescheduled",
                message=f"Your appointment {appointment.appointment_number} with Dr. {doctor_name} has been rescheduled to {new_date} at {new_time}.",
                notification_type="APPOINTMENT_RESCHEDULE",
                reference_type="APPOINTMENT",
                reference_id=appointment.id,
                priority="NORMAL",
                email=patient.email if patient else None,
                phone=patient.phone if patient else None,
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Failed to dispatch reschedule notification: %s", exc)

        return AppointmentResponse.model_validate(appointment)

    async def cancel(self, data: CancelRequest, user_id: int) -> AppointmentResponse:
        appointment = await self.repo.get_by_id(data.appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
        if appointment.appointment_status in AppointmentStatus.TERMINAL:
            raise BadRequestException("Cannot cancel a terminal appointment")
        appointment.appointment_status = AppointmentStatus.CANCELLED
        appointment.queue_status = "CANCELLED"
        if data.reason:
            appointment.notes = data.reason
        appointment = await self.repo.update(appointment)
        await self.audit_repo.create("cancel", "appointments", user_id=user_id, resource_id=str(appointment.id))

        try:
            patient = await self.patient_repo.get_by_id(appointment.patient_id)
            doctor = await self.doctor_repo.get_by_id(appointment.doctor_id)
            doctor_name = f"{doctor.first_name} {doctor.last_name}".strip() if doctor else "Doctor"
            user_target = (patient.user_id if patient and patient.user_id else None) or user_id

            from app.services.notification_service import NotificationService
            await NotificationService(self.db).dispatch_notification(
                user_id=user_target,
                title="Appointment Cancelled",
                message=f"Your appointment {appointment.appointment_number} with Dr. {doctor_name} has been cancelled.",
                notification_type="APPOINTMENT_CANCELLATION",
                reference_type="APPOINTMENT",
                reference_id=appointment.id,
                priority="NORMAL",
                email=patient.email if patient else None,
                phone=patient.phone if patient else None,
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Failed to dispatch cancellation notification: %s", exc)

        return AppointmentResponse.model_validate(appointment)

    async def confirm(self, data: ConfirmRequest, user_id: int) -> AppointmentResponse:
        appointment = await self.repo.get_by_id(data.appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
            
        if appointment.appointment_status == AppointmentStatus.COMPLETED:
            raise BadRequestException("Cannot confirm a completed appointment")
        elif appointment.appointment_status == "Checked-Out":
            raise BadRequestException("Cannot confirm a checked-out appointment")
        elif appointment.appointment_status == AppointmentStatus.CANCELLED:
            raise BadRequestException("Cannot confirm a cancelled appointment")
        elif appointment.appointment_status == AppointmentStatus.NO_SHOW:
            raise BadRequestException("Cannot confirm a no-show appointment")
            
        appointment.appointment_status = AppointmentStatus.CONFIRMED
        appointment = await self.repo.update(appointment)
        await self.audit_repo.create("confirm", "appointments", user_id=user_id, resource_id=str(appointment.id))
        await self._notify_confirmation_safely(appointment, user_id)
        return AppointmentResponse.model_validate(appointment)

    async def get_calendar(self, start_date: date, end_date: date, doctor_id: int | None = None):
        appointments = await self.repo.get_calendar(start_date, end_date, doctor_id)
        return [AppointmentResponse.model_validate(a) for a in appointments]

    async def get_today(self, on_date: date | None = None) -> dict:
        from app.utils.helpers import get_today_ist
        if on_date is None:
            on_date = get_today_ist()
        appointments = await self.repo.get_today(on_date)
        has_updated = False
        today = on_date
        next_num = None
        for a in appointments:
            if not a.queue_token:
                if next_num is None:
                    next_tok = await self.repo.get_next_queue_token(a.appointment_date or today)
                    try:
                        next_num = int(next_tok.replace("T-", ""))
                    except (ValueError, AttributeError):
                        next_num = 1
                a.queue_token = f"T-{next_num}"
                if not a.token_number:
                    a.token_number = next_num
                next_num += 1
                if not a.queue_status:
                    a.queue_status = "CANCELLED" if a.appointment_status in (AppointmentStatus.CANCELLED, "Cancelled", "cancelled") else "WAITING"
                has_updated = True
        if has_updated:
            await self.db.flush()

        items = [AppointmentResponse.model_validate(a) for a in appointments]
        total_today = len(items)
        cancelled_count = sum(1 for a in items if (a.appointment_status or "").lower() in ("cancelled", "canceled", "no show", "no-show") or (a.queue_status or "").upper() == "CANCELLED")
        waiting_count = sum(1 for a in items if (a.queue_status or "").upper() == "WAITING")
        completed_count = sum(1 for a in items if (a.appointment_status or "").lower() == "completed" or (a.queue_status or "").upper() == "COMPLETED")
        checked_in_count = sum(1 for a in items if a.check_in_time is not None or (a.appointment_status or "").lower() in ("checked-in", "checked_in", "check-in"))
        checked_out_count = sum(1 for a in items if a.check_out_time is not None or (a.appointment_status or "").lower() in ("checked-out", "checked_out", "check-out"))
        pending_count = sum(1 for a in items if (a.appointment_status or "").lower() == "pending")
        confirmed_count = sum(1 for a in items if (a.appointment_status or "").lower() == "confirmed")
        in_progress_count = sum(1 for a in items if (a.appointment_status or "").lower() in ("in-progress", "in_progress") or (a.queue_status or "").upper() in ("CALLED", "IN_PROGRESS", "IN_CONSULTATION"))
        admitted_count = sum(1 for a in items if (a.admission_status or "").lower() in ("admitted", "admit recommended", "admit-recommended"))

        return {
            "items": items,
            "total": total_today,
            "total_appointments": total_today,
            "total_today_appointments": total_today,
            "total_today_tokens": total_today,
            "today_appointments": total_today,
            "cancelled": cancelled_count,
            "waiting": waiting_count,
            "completed": completed_count,
            "checked_in": checked_in_count,
            "checked_out": checked_out_count,
            "pending": pending_count,
            "confirmed": confirmed_count,
            "in_progress": in_progress_count,
            "admitted": admitted_count,
        }

    async def get_upcoming(self, limit: int = 20):
        appointments = await self.repo.get_upcoming(limit)
        return [AppointmentResponse.model_validate(a) for a in appointments]

    async def check_in(self, appointment_id: int, user_id: int) -> Appointment:
        appointment = await self.repo.get_by_id(appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
        if appointment.appointment_status in ("Checked-In", "Checked_In", "checked_in"):
            raise BadRequestException("Appointment already checked in")
        if appointment.appointment_status not in (AppointmentStatus.CONFIRMED, "Confirmed", "confirmed"):
            raise BadRequestException("Appointment must be confirmed before check-in.")
        appointment.appointment_status = "Checked-In"
        appointment.check_in_time = datetime.now()
        if not appointment.queue_token:
            appointment.queue_token = await self.repo.get_next_queue_token(appointment.appointment_date)
            if not appointment.token_number:
                try:
                    appointment.token_number = int(appointment.queue_token.replace("T-", ""))
                except (ValueError, AttributeError):
                    pass
        if not appointment.queue_status or appointment.queue_status == "CANCELLED":
            appointment.queue_status = "WAITING"
        await self.db.flush()
        await self._create_queue_notification(appointment, f"Patient checked in for appointment {appointment.appointment_number}")
        return appointment

    async def check_out(self, appointment_id: int, user_id: int) -> Appointment:
        appointment = await self.repo.get_by_id(appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
        
        if appointment.appointment_status == "Checked-Out":
            raise BadRequestException("Appointment already checked out")
        elif appointment.appointment_status == AppointmentStatus.CANCELLED:
            raise BadRequestException("Cannot check out a cancelled appointment")
        elif appointment.appointment_status == AppointmentStatus.NO_SHOW:
            raise BadRequestException("Cannot check out a no-show appointment")
            
        if appointment.appointment_status != AppointmentStatus.COMPLETED or appointment.queue_status != "COMPLETED":
            raise BadRequestException("Appointment must be completed before check-out")
            

        # 1. Reject if already checked out
        if appointment.check_out_time is not None or appointment.appointment_status in ("Checked-Out", "Checked_Out", "checked-out", "checked_out"):
            raise BadRequestException("Appointment already checked out")

        # 2. Reject if cancelled
        if appointment.appointment_status in (AppointmentStatus.CANCELLED, "Cancelled", "cancelled"):
            raise BadRequestException("Cannot check out a cancelled appointment")

        # 3. Verify that appointment was checked in
        is_checked_in = (
            appointment.check_in_time is not None
            or appointment.appointment_status in ("Checked-In", "Checked_In", "checked_in", "checked-in", "In-Progress", "in-progress", "Completed", "completed", AppointmentStatus.COMPLETED)
        )
        if not is_checked_in:
            raise BadRequestException("Appointment must be checked in first")

        # Enforce that patient cannot check out before the appointment start time (unless already completed by doctor)
        if (
            appointment.appointment_date 
            and appointment.appointment_time 
            and appointment.queue_status != "COMPLETED" 
            and appointment.appointment_status not in ("Completed", "completed")
        ):
            from datetime import timezone, timedelta
            ist_tz = timezone(timedelta(hours=5, minutes=30))
            now_ist = datetime.now(ist_tz).replace(tzinfo=None)
            appt_start_datetime = datetime.combine(appointment.appointment_date, appointment.appointment_time)
            if now_ist < appt_start_datetime:
                raise BadRequestException("Patient cannot check out before the appointment start time")

        appointment.appointment_status = "Checked-Out"
        appointment.check_out_time = datetime.now()
        if not appointment.queue_status or appointment.queue_status in ("WAITING", "CALLED", "IN_PROGRESS"):
            appointment.queue_status = "COMPLETED"

        await self.db.flush()
        await self._create_queue_notification(appointment, f"Patient checked out for appointment {appointment.appointment_number}")
        return appointment

    async def generate_queue_token(self, appointment_id: int, user_id: int) -> Appointment:
        appointment = await self.repo.get_by_id(appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
        if appointment.appointment_status in (AppointmentStatus.CANCELLED, "Cancelled", "cancelled"):
            raise BadRequestException("Cannot generate queue token for a cancelled appointment")
        if appointment.queue_token:
            raise BadRequestException("Token already generated for this appointment")

        next_token = await self.repo.get_next_queue_token(appointment.appointment_date)

        appointment.queue_token = next_token
        if not appointment.token_number:
            try:
                appointment.token_number = int(next_token.replace("T-", ""))
            except (ValueError, AttributeError):
                pass
        appointment.queue_status = "WAITING"
        await self.db.flush()
        await self._create_queue_notification(appointment, f"Queue token {next_token} has been generated.")
        return appointment

    async def get_today_queue(self) -> list[Appointment]:
        from app.utils.helpers import get_today_ist
        from sqlalchemy import select, case
        from sqlalchemy.orm import joinedload
        today = get_today_ist()
        result = await self.db.execute(
            select(Appointment)
            .options(joinedload(Appointment.patient))
            .where(Appointment.appointment_date == today)
            .order_by(
                case(
                    (Appointment.triage_level.isnot(None), Appointment.triage_level),
                    else_=999,
                ).asc(),
                Appointment.id.asc(),
            )
        )
        appointments = list(result.scalars().unique().all())
        has_updated = False
        next_num = None
        for a in appointments:
            if not a.queue_token:
                if next_num is None:
                    next_tok = await self.repo.get_next_queue_token(a.appointment_date or today)
                    try:
                        next_num = int(next_tok.replace("T-", ""))
                    except (ValueError, AttributeError):
                        next_num = 1
                a.queue_token = f"T-{next_num}"
                if not a.token_number:
                    a.token_number = next_num
                next_num += 1
                if not a.queue_status:
                    a.queue_status = "CANCELLED" if a.appointment_status in (AppointmentStatus.CANCELLED, "Cancelled", "cancelled") else "WAITING"
                has_updated = True
        if has_updated:
            await self.db.flush()
        return appointments

    async def get_current_queue(self) -> Appointment | None:
        from app.utils.helpers import get_today_ist
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload
        today = get_today_ist()
        result = await self.db.execute(
            select(Appointment)
            .options(joinedload(Appointment.patient))
            .where(
                Appointment.appointment_date == today,
                Appointment.queue_status.in_(["CALLED", "IN_PROGRESS"])
            )
            .order_by(Appointment.updated_at.desc(), Appointment.id.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def call_next_token(self, appointment_id: int, user_id: int) -> Appointment:
        appointment = await self.repo.get_by_id(appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")

        status = str(appointment.appointment_status or "").strip()
        if status in (AppointmentStatus.CANCELLED, "Cancelled", "cancelled"):
            raise BadRequestException("Cannot call token for a cancelled appointment.")

        if status in ("Checked-Out", "Checked_Out", "checked-out", "checked_out") or appointment.check_out_time is not None:
            raise BadRequestException("Cannot call token for an appointment that has already checked out.")

        if status in (AppointmentStatus.COMPLETED, "Completed", "completed") or appointment.queue_status == "COMPLETED":
            raise BadRequestException("Cannot call token for an appointment that is already completed.")

        # Require Confirmed & Checked-In
        if status in (AppointmentStatus.PENDING, "Pending", "pending"):
            raise BadRequestException("Appointment must be confirmed and checked in before calling token.")

        if not appointment.check_in_time or not appointment.queue_token:
            raise BadRequestException("Appointment must be checked in before calling token.")

        appointment.queue_status = "CALLED"
        await self.db.flush()
        await self._create_queue_notification(appointment, f"Doctor is calling patient (Token {appointment.queue_token})")
        return appointment

    async def complete_token(self, appointment_id: int, user_id: int) -> Appointment:
        appointment = await self.repo.get_by_id(appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
            
        if appointment.appointment_status == AppointmentStatus.CANCELLED:
            raise BadRequestException("Cannot complete token for a cancelled appointment")
        elif appointment.appointment_status == AppointmentStatus.NO_SHOW:
            raise BadRequestException("Cannot complete token for a no-show appointment")
        elif appointment.appointment_status == "Checked-Out":
            raise BadRequestException("Cannot complete token for a checked-out appointment")
        elif appointment.appointment_status == AppointmentStatus.COMPLETED or appointment.queue_status == "COMPLETED":
            raise BadRequestException("Cannot complete token for an already completed appointment")
        elif appointment.appointment_status == "Checked-In":
            raise BadRequestException("Appointment visit must be confirmed before completing the token")
        elif appointment.appointment_status != AppointmentStatus.CONFIRMED or not appointment.check_in_time:
            raise BadRequestException("Appointment must be checked in first")
            

        status = str(appointment.appointment_status or "").strip()
        if status in (AppointmentStatus.CANCELLED, "Cancelled", "cancelled"):
            raise BadRequestException("Cannot complete token for a cancelled appointment.")

        if not appointment.check_in_time or not appointment.queue_token:
            raise BadRequestException("Appointment must be checked in before completing token.")

        appointment.queue_status = "COMPLETED"
        appointment.appointment_status = AppointmentStatus.COMPLETED
            
        await self.db.flush()
        return appointment

    async def skip_token(self, appointment_id: int, user_id: int) -> Appointment:
        appointment = await self.repo.get_by_id(appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")

        status = str(appointment.appointment_status or "").strip()
        if status in (AppointmentStatus.CANCELLED, "Cancelled", "cancelled"):
            raise BadRequestException("Cannot skip token for a cancelled appointment.")

        if not appointment.check_in_time or not appointment.queue_token:
            raise BadRequestException("Appointment must be checked in before skipping token.")

        appointment.queue_status = "SKIPPED"
        await self.db.flush()
        return appointment

    async def _create_queue_notification(self, appointment: Appointment, message: str) -> None:
        from app.models.doctor_model import Doctor
        from app.models.patient_model import Patient
        from app.services.notification_service import NotificationService
        from sqlalchemy import select

        doc_user_id = await self.db.scalar(
            select(Doctor.user_id).where(Doctor.id == appointment.doctor_id)
        )
        pat_user_id = await self.db.scalar(
            select(Patient.user_id).where(Patient.id == appointment.patient_id)
        )

        notif_service = NotificationService(self.db)
        if doc_user_id:
            await notif_service.dispatch_notification(
                user_id=doc_user_id,
                title="Appointment Queue Alert",
                message=message,
                notification_type="QUEUE_ALERT",
                reference_type="APPOINTMENT",
                reference_id=appointment.id,
                priority="NORMAL"
            )

        if pat_user_id:
            await notif_service.dispatch_notification(
                user_id=pat_user_id,
                title="Appointment Queue Alert",
                message=message,
                notification_type="QUEUE_ALERT",
                reference_type="APPOINTMENT",
                reference_id=appointment.id,
                priority="NORMAL"
            )

    async def get_confirmed_visit_list(
            self,
            page: int = 1,
            limit: int = 20,
            search: str | None = None,
            doctor_id: int | None = None,
            department_id: int | None = None,
            appointment_date: date | None = None,
        ):
            skip = (page - 1) * limit
            items = await self.repo.get_confirmed_appointments(
                skip=skip, limit=limit, search=search, doctor_id=doctor_id,
                department_id=department_id, appointment_date=appointment_date,
            )
            total = await self.repo.count_confirmed_appointments(
                search=search, doctor_id=doctor_id,
                department_id=department_id, appointment_date=appointment_date,
            )

            responses = []
            for appt in items:
                p_name = f"{appt.patient.first_name} {appt.patient.last_name}" if appt.patient else ""
                doc_name = f"Dr. {appt.doctor.first_name} {appt.doctor.last_name}" if appt.doctor else ""
                dept_name = appt.department.department_name if appt.department else None

                responses.append(
                    ConfirmedVisitResponse(
                        appointment_id=appt.id,
                        appointment_number=appt.appointment_number,
                        patient_id=appt.patient_id,
                        patient_name=p_name,
                        doctor_id=appt.doctor_id,
                        doctor_name=doc_name,
                        department_name=dept_name,
                        appointment_date=appt.appointment_date,
                        appointment_time=appt.appointment_time,
                        status=appt.appointment_status,
                        check_in_time=appt.check_in_time,
                        queue_token=appt.queue_token,
                        queue_status=appt.queue_status
                    )
                )

            return build_paginated_result(responses, total, page, limit)

    async def download_appointment_pdf(self, appointment_id: int) -> bytes:
        import io
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.models.clinical_record_model import ClinicalRecord
        from app.models.pharmacy_model import Prescription, PrescriptionItem

        appointment = await self.repo.get_by_id(appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")

        status_lower = appointment.appointment_status.lower().strip() if appointment.appointment_status else ""
        if status_lower not in ("completed", "checked-out"):
            raise BadRequestException("Only completed appointments can be downloaded")

        # Explicitly fetch related entities to avoid lazy-loading on async SQLAlchemy session
        from app.models.patient_model import Patient
        from app.models.doctor_model import Doctor
        from app.models.department_model import Department

        patient = None
        if appointment.patient_id:
            try:
                p_res = await self.db.execute(select(Patient).where(Patient.id == appointment.patient_id))
                patient = p_res.scalar_one_or_none()
            except Exception:
                pass
            if not patient:
                patient = getattr(appointment, "patient", None)

        doctor = None
        if appointment.doctor_id:
            try:
                d_res = await self.db.execute(select(Doctor).where(Doctor.id == appointment.doctor_id))
                doctor = d_res.scalar_one_or_none()
            except Exception:
                pass
            if not doctor:
                doctor = getattr(appointment, "doctor", None)

        department = None
        if appointment.department_id:
            try:
                dp_res = await self.db.execute(select(Department).where(Department.department_id == appointment.department_id))
                department = dp_res.scalar_one_or_none()
            except Exception:
                pass
            if not department:
                department = getattr(appointment, "department", None)

        # Fetch clinical record
        cr_stmt = select(ClinicalRecord).where(
            ClinicalRecord.appointment_id == appointment_id,
            ClinicalRecord.is_deleted == False
        )
        cr_res = await self.db.execute(cr_stmt)
        clinical_record = cr_res.scalar_one_or_none()

        # Fetch prescription with items and medicines
        pr_stmt = select(Prescription).where(
            Prescription.appointment_id == appointment_id,
            Prescription.is_deleted == False
        ).options(
            selectinload(Prescription.items).selectinload(PrescriptionItem.medicine)
        )
        pr_res = await self.db.execute(pr_stmt)
        prescription = pr_res.scalar_one_or_none()

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=40,
            leftMargin=40,
            topMargin=40,
            bottomMargin=40
        )
        elements = []

        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            'DocTitle',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=20,
            leading=24,
            textColor=colors.HexColor('#2C3E50'),
            spaceAfter=15,
            alignment=1
        )

        section_heading = ParagraphStyle(
            'SectionHeading',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=14,
            leading=18,
            textColor=colors.HexColor('#2C3E50'),
            spaceBefore=15,
            spaceAfter=8,
            keepWithNext=True
        )

        label_style = ParagraphStyle(
            'LabelStyle',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=10,
            leading=12,
            textColor=colors.HexColor('#34495E')
        )

        value_style = ParagraphStyle(
            'ValueStyle',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=10,
            leading=12,
            textColor=colors.HexColor('#2C3E50')
        )

        rx_header_style = ParagraphStyle(
            'RxHeader',
            parent=label_style,
            textColor=colors.whitesmoke
        )

        header_table_style = TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#ECF0F1')),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('TOPPADDING', (0,0), (-1,-1), 8),
            ('BOTTOMPADDING', (0,0), (-1,-1), 8),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('RIGHTPADDING', (0,0), (-1,-1), 10),
            ('LINEBELOW', (0,-1), (-1,-1), 2, colors.HexColor('#BDC3C7')),
        ])

        # Header branding
        branding = Paragraph("<b>NexaCare Hospital</b>", ParagraphStyle('HospBranding', parent=title_style, fontSize=24, leading=28, textColor=colors.HexColor('#16A085')))
        elements.append(branding)
        elements.append(Paragraph("Visit Summary & Consultation Report", title_style))
        elements.append(Spacer(1, 10))

        # Metadata Table formatting
        p_name = f"{patient.first_name} {patient.last_name}" if patient else "N/A"
        gender = patient.gender if patient else "N/A"
        age_str = "N/A"
        if patient and patient.dob:
            today = date.today()
            dob = patient.dob
            calc_age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            age_str = f"{calc_age}"

        doc_name = f"Dr. {doctor.first_name} {doctor.last_name}" if doctor else "N/A"
        dept_name = department.department_name if department else "N/A"

        meta_data = [
            [
                Paragraph("Appointment No:", label_style), Paragraph(appointment.appointment_number, value_style),
                Paragraph("Visit Date:", label_style), Paragraph(str(appointment.appointment_date), value_style)
            ],
            [
                Paragraph("Patient Name:", label_style), Paragraph(p_name, value_style),
                Paragraph("Gender / Age:", label_style), Paragraph(f"{gender} / {age_str} yrs", value_style)
            ],
            [
                Paragraph("Doctor:", label_style), Paragraph(doc_name, value_style),
                Paragraph("Department:", label_style), Paragraph(dept_name, value_style)
            ]
        ]
        meta_table = Table(meta_data, colWidths=[100, 160, 100, 160])
        meta_table.setStyle(header_table_style)
        elements.append(meta_table)
        elements.append(Spacer(1, 15))

        # Clinical Findings
        elements.append(Paragraph("Clinical Findings", section_heading))
        findings_data = []

        symptoms_text = clinical_record.symptoms if clinical_record else appointment.symptoms
        findings_data.append([Paragraph("Symptoms:", label_style), Paragraph(symptoms_text or "No symptoms recorded", value_style)])

        diagnosis_text = clinical_record.diagnosis if clinical_record else None
        findings_data.append([Paragraph("Diagnosis:", label_style), Paragraph(diagnosis_text or "No diagnosis recorded", value_style)])

        plan_text = clinical_record.treatment_plan if clinical_record else None
        findings_data.append([Paragraph("Treatment Plan:", label_style), Paragraph(plan_text or "No treatment plan recorded", value_style)])

        notes_text = clinical_record.notes if clinical_record else appointment.notes
        findings_data.append([Paragraph("Doctor Notes:", label_style), Paragraph(notes_text or "No additional notes", value_style)])

        findings_table = Table(findings_data, colWidths=[100, 420])
        findings_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('LINEBELOW', (0,0), (-1,-1), 0.5, colors.HexColor('#BDC3C7')),
        ]))
        elements.append(findings_table)

        # Prescription (Rx) if exists
        if prescription:
            elements.append(Spacer(1, 15))
            elements.append(Paragraph("Rx (Prescribed Medicines)", section_heading))

            rx_data = [[
                Paragraph("<b>Medicine Name</b>", rx_header_style),
                Paragraph("<b>Dosage</b>", rx_header_style),
                Paragraph("<b>Frequency</b>", rx_header_style),
                Paragraph("<b>Duration</b>", rx_header_style),
                Paragraph("<b>Instructions</b>", rx_header_style)
            ]]

            for item in prescription.items:
                med_name = item.medicine.name if item.medicine else "N/A"
                rx_data.append([
                    Paragraph(med_name, value_style),
                    Paragraph(item.dosage, value_style),
                    Paragraph(item.frequency, value_style),
                    Paragraph(f"{item.duration_days} days", value_style),
                    Paragraph(item.instructions or "-", value_style)
                ])

            rx_table = Table(rx_data, colWidths=[130, 80, 80, 70, 160])
            rx_table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#2C3E50')),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                ('TOPPADDING', (0,0), (-1,-1), 6),
                ('LEFTPADDING', (0,0), (-1,-1), 6),
                ('RIGHTPADDING', (0,0), (-1,-1), 6),
                ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#BDC3C7')),
            ]))
            elements.append(rx_table)

        # Signatures
        elements.append(Spacer(1, 40))
        sig_data = [
            [Paragraph("____________________________", value_style), Paragraph("____________________________", value_style)],
            [Paragraph("Patient Signature", label_style), Paragraph("Doctor's Signature / Seal", label_style)]
        ]
        sig_table = Table(sig_data, colWidths=[260, 260])
        sig_table.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        elements.append(sig_table)

        # Disclaimer
        elements.append(Spacer(1, 25))
        disclaimer = Paragraph(
            "<i>This is a computer-generated document. For any queries or emergencies, please contact NexaCare Hospital.</i>",
            ParagraphStyle('Disclaimer', parent=styles['Normal'], fontSize=8, alignment=1, textColor=colors.HexColor('#7F8C8D'))
        )
        elements.append(disclaimer)

        doc.build(elements)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        return pdf_bytes

    async def search_scheduled_doctors(
        self,
        appointment_date: date,
        appointment_time: time | None = None,
        department_id: int | None = None,
        specialization: str | None = None,
    ) -> list[ScheduledDoctorResponse]:
        from app.models.doctor_model import Doctor, DoctorSchedule
        from sqlalchemy import select
        from datetime import time as dt_time

        # 1. Convert appointment_date to weekday (0 = Monday, 6 = Sunday)
        day_of_week = appointment_date.weekday()

        # 2. Base query: Join DoctorSchedule with Doctor
        query = (
            select(Doctor, DoctorSchedule)
            .join(DoctorSchedule, DoctorSchedule.doctor_id == Doctor.id)
            .where(
                Doctor.is_deleted.is_(False),
                DoctorSchedule.day_of_week == day_of_week,
                DoctorSchedule.is_active.is_(True)
            )
        )

        # Apply filters
        if department_id is not None:
            query = query.where(Doctor.department_id == department_id)
        if specialization is not None and specialization.strip() != "":
            query = query.where(Doctor.specialization.ilike(f"%{specialization.strip()}%"))

        result = await self.db.execute(query)
        rows = result.all()

        response_list = []
        for doctor, sched in rows:
            is_available = True

            # If appointment_time is provided, evaluate availability for the exact slot
            if appointment_time is not None:
                if doctor.availability_status in ("onleave", "on_leave"):
                    is_available = False
                else:
                    try:
                        from app.services.booking_validation_service import BookingValidationService
                        val_service = BookingValidationService(self.db)
                        await val_service.validate(
                            doctor_id=doctor.id,
                            appointment_date=appointment_date,
                            appointment_time=appointment_time
                        )
                        is_available = True
                    except Exception:
                        is_available = False

            response_list.append(
                ScheduledDoctorResponse(
                    doctor_id=doctor.id,
                    first_name=doctor.first_name,
                    last_name=doctor.last_name,
                    specialization=doctor.specialization,
                    department_id=doctor.department_id,
                    consultation_fee=doctor.consultation_fee,
                    day_of_week=sched.day_of_week,
                    start_time=sched.start_time,
                    end_time=sched.end_time,
                    slot_duration_minutes=sched.slot_duration_minutes,
                    is_available=is_available
                )
            )

        return response_list

    async def recommend_admission(
        self,
        appointment_id: int,
        data: AdmitRecommendationRequest,
        user_id: int,
    ) -> AdmitRecommendationResponse:
        appointment = await self.repo.get_by_id(appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")

        doctor = await self.doctor_repo.get_by_user_id(user_id)
        if doctor and appointment.doctor_id != doctor.id:
            from app.models.user_model import User
            from app.core.constants import UserRole
            from sqlalchemy import select
            user_res = await self.db.execute(select(User).where(User.id == user_id))
            user = user_res.scalar_one_or_none()
            if user and user.role and user.role.name not in UserRole.ADMIN_ROLES:
                raise BadRequestException("You can only recommend admission for your own appointments")

        if appointment.appointment_status in (AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW, "Cancelled", "No Show"):
            raise BadRequestException(f"Cannot recommend admission for an appointment with status: {appointment.appointment_status}")

        if appointment.appointment_status in (AppointmentStatus.PENDING, "Pending"):
            raise BadRequestException("Cannot recommend admission for an appointment that is pending. Please confirm and check in the patient first.")

        if not appointment.check_in_time and appointment.appointment_status not in (AppointmentStatus.COMPLETED, "Checked-In", "In-Progress") and (appointment.queue_status or "").upper() not in ("CHECKED_IN", "IN_CONSULTATION", "COMPLETED"):
            raise BadRequestException("Cannot recommend admission for a patient who has not checked in. Please check in the patient first.")

        from app.core.constants import AdmissionStatus, EmergencyDisposition
        from app.utils.helpers import generate_admission_number
        appointment.appointment_type = "IPD"
        appointment.appointment_status = AppointmentStatus.COMPLETED
        appointment.queue_status = "COMPLETED"
        appointment.admission_status = AdmissionStatus.ADMIT_RECOMMENDED
        appointment.admission_number = appointment.admission_number or generate_admission_number()
        appointment.admission_recommended = True
        appointment.admission_reason = data.admission_reason
        appointment.expected_los = data.expected_los
        appointment.recommended_ward = data.recommended_ward
        appointment.disposition = EmergencyDisposition.ADMIT.value
        if data.notes:
            appointment.notes = f"{appointment.notes or ''}\n[Admission Notes]: {data.notes}".strip()

        diagnosis_val = data.diagnosis
        if diagnosis_val:
            from app.models.clinical_record_model import ClinicalRecord
            from sqlalchemy import select
            cr_res = await self.db.execute(
                select(ClinicalRecord).where(ClinicalRecord.appointment_id == appointment.id)
            )
            clinical_record = cr_res.scalar_one_or_none()
            if isinstance(clinical_record, ClinicalRecord):
                clinical_record.diagnosis = diagnosis_val
                if data.notes:
                    clinical_record.notes = f"{clinical_record.notes or ''}\n[Admission Notes]: {data.notes}".strip()
            else:
                clinical_record = ClinicalRecord(
                    patient_id=appointment.patient_id,
                    doctor_id=appointment.doctor_id,
                    appointment_id=appointment.id,
                    diagnosis=diagnosis_val,
                    notes=data.notes,
                )
                self.db.add(clinical_record)

            if appointment.patient:
                appointment.patient.diagnosis = diagnosis_val

        await self.db.flush()

        patient_name = appointment.patient_name or f"Patient ID {appointment.patient_id}"
        await self._create_queue_notification(
            appointment,
            f"Admission recommended for {patient_name} (Admission No: {appointment.admission_number}). Please allocate a bed."
        )

        return AdmitRecommendationResponse(
            appointment_id=appointment.id,
            admission_number=appointment.admission_number,
            patient_id=appointment.patient_id,
            doctor_id=appointment.doctor_id,
            appointment_status=appointment.appointment_status,
            admission_status=appointment.admission_status,
            admission_recommended=appointment.admission_recommended,
            admission_reason=appointment.admission_reason,
            expected_los=appointment.expected_los,
            recommended_ward=appointment.recommended_ward,
            diagnosis=diagnosis_val or (appointment.patient.diagnosis if appointment.patient else None),
            notes=data.notes,
            disposition=appointment.disposition,
        )

    async def update_triage(
        self,
        appointment_id: int,
        data: EmergencyTriageRequest,
        user_id: int,
    ) -> AppointmentResponse:
        appointment = await self.repo.get_by_id(appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
        appointment.triage_level = data.triage_level
        if data.triage_notes is not None:
            appointment.triage_notes = data.triage_notes
        appointment = await self.repo.update(appointment)
        await self.audit_repo.create("update_triage", "appointments", user_id=user_id, resource_id=str(appointment.id))
        return AppointmentResponse.model_validate(appointment)

    async def update_disposition(
        self,
        appointment_id: int,
        data: EmergencyDispositionRequest,
        user_id: int,
    ) -> AppointmentResponse:
        appointment = await self.repo.get_by_id(appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
        disp_clean = data.disposition.strip().upper()
        appointment.disposition = disp_clean
        if data.referred_to is not None:
            appointment.referred_to = data.referred_to
        if data.referral_reason is not None:
            appointment.referral_reason = data.referral_reason
        if data.notes:
            appointment.notes = f"{appointment.notes or ''}\n[Disposition Notes]: {data.notes}".strip()
        appointment = await self.repo.update(appointment)
        await self.audit_repo.create("update_disposition", "appointments", user_id=user_id, resource_id=str(appointment.id))
        return AppointmentResponse.model_validate(appointment)

    async def get_pending_admissions(self) -> list[PendingAdmissionItem]:
        from app.models.bed_allocation_model import Bed
        from app.models.doctor_model import Doctor
        from app.models.patient_model import Patient
        from app.core.constants import AdmissionStatus
        from sqlalchemy import select, and_, not_, exists, or_
        from sqlalchemy.orm import selectinload

        admit_rec_variants = [
            "Admit Recommended",
            "admit recommended",
            "Admit-Recommended",
            "admit-recommended",
            "admit_recommended",
            "ADMIT_RECOMMENDED",
        ]

        excluded_adm_variants = [
            "Admitted",
            "admitted",
            "ADMITTED",
            "Discharged",
            "discharged",
            "DISCHARGED",
            "Cancelled",
            "cancelled",
            "CANCELLED",
        ]

        excluded_appt_variants = [
            "Admitted",
            "admitted",
            "ADMITTED",
            "Cancelled",
            "cancelled",
            "CANCELLED",
        ]

        stmt = (
            select(Appointment)
            .options(
                selectinload(Appointment.patient),
                selectinload(Appointment.doctor).selectinload(Doctor.department),
                selectinload(Appointment.department),
                selectinload(Appointment.clinical_record),
            )
            .where(
                or_(
                    Appointment.admission_status.in_(admit_rec_variants),
                    and_(
                        Appointment.admission_recommended.is_(True),
                        or_(
                            Appointment.admission_status.is_(None),
                            Appointment.admission_status.in_(admit_rec_variants),
                        ),
                    ),
                ),
                or_(
                    Appointment.admission_status.is_(None),
                    Appointment.admission_status.notin_(excluded_adm_variants),
                ),
                or_(
                    Appointment.appointment_status.is_(None),
                    Appointment.appointment_status.notin_(excluded_appt_variants),
                ),
                not_(
                    exists().where(
                        and_(
                            Bed.patient_id == Appointment.patient_id,
                            Bed.status == "Occupied",
                        )
                    )
                ),
            )
            .order_by(Appointment.updated_at.desc(), Appointment.id.desc())
        )
        res = await self.db.execute(stmt)
        appointments = list(res.scalars().all())

        items: list[PendingAdmissionItem] = []
        for a in appointments:
            p = None
            if hasattr(a, "__dict__") and "patient" in a.__dict__:
                p = a.__dict__["patient"]
            elif hasattr(a, "patient") and not hasattr(a, "__table__"):
                p = a.patient
            if not p and a.patient_id:
                p = await self.db.get(Patient, a.patient_id)

            d = None
            if hasattr(a, "__dict__") and "doctor" in a.__dict__:
                d = a.__dict__["doctor"]
            elif hasattr(a, "doctor") and not hasattr(a, "__table__"):
                d = a.doctor
            if not d and a.doctor_id:
                d = await self.db.get(Doctor, a.doctor_id)

            dept_name = None
            if d:
                dept_obj = None
                if hasattr(d, "__dict__") and "department" in d.__dict__:
                    dept_obj = d.__dict__["department"]
                elif hasattr(d, "department") and not hasattr(d, "__table__"):
                    dept_obj = d.department
                if dept_obj and hasattr(dept_obj, "name") and isinstance(getattr(dept_obj, "name", None), str):
                    dept_name = dept_obj.name
                elif dept_obj and hasattr(dept_obj, "department_name") and isinstance(getattr(dept_obj, "department_name", None), str):
                    dept_name = dept_obj.department_name

            if not dept_name:
                appt_dept = None
                if hasattr(a, "__dict__") and "department" in a.__dict__:
                    appt_dept = a.__dict__["department"]
                elif hasattr(a, "department") and not hasattr(a, "__table__"):
                    appt_dept = a.department
                if appt_dept and hasattr(appt_dept, "name") and isinstance(getattr(appt_dept, "name", None), str):
                    dept_name = appt_dept.name
                elif appt_dept and hasattr(appt_dept, "department_name") and isinstance(getattr(appt_dept, "department_name", None), str):
                    dept_name = appt_dept.department_name

            cr_obj = None
            if hasattr(a, "__dict__") and "clinical_record" in a.__dict__:
                cr_obj = a.__dict__["clinical_record"]
            elif hasattr(a, "clinical_record") and not hasattr(a, "__table__"):
                cr_obj = a.clinical_record

            p_age = None
            if p and getattr(p, "dob", None) and hasattr(p.dob, "year"):
                today = date.today()
                dob = p.dob
                p_age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

            p_info = PendingAdmissionPatientInfo(
                id=p.id if p else a.patient_id,
                patient_code=p.patient_code if p else "",
                first_name=p.first_name if p else "",
                last_name=p.last_name if p else "",
                gender=p.gender if p else None,
                age=p_age,
                phone=p.phone if p else None,
            )
            d_info = PendingAdmissionDoctorInfo(
                id=d.id if d else a.doctor_id,
                first_name=d.first_name if d else "",
                last_name=d.last_name if d else "",
                specialization=d.specialization if d else None,
                department_name=dept_name,
            )
            diagnosis_val = (p.diagnosis if p else None) or (cr_obj.diagnosis if cr_obj else None)
            items.append(
                PendingAdmissionItem(
                    appointment_id=a.id,
                    admission_number=a.admission_number,
                    patient_id=a.patient_id,
                    appointment_number=a.appointment_number,
                    appointment_date=a.appointment_date,
                    appointment_status=a.appointment_status,
                    admission_status=a.admission_status or (AdmissionStatus.ADMIT_RECOMMENDED if a.admission_recommended else None),
                    admission_recommended=a.admission_recommended,
                    admission_reason=a.admission_reason,
                    expected_los=a.expected_los,
                    recommended_ward=a.recommended_ward,
                    diagnosis=diagnosis_val,
                    patient=p_info,
                    doctor=d_info,
                    created_at=a.created_at,
                )
            )

        return items

