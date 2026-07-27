from datetime import date, datetime, time

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AppointmentStatus
from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.models.appointment_model import Appointment
from app.repositories.appointment_repository import AppointmentRepository
from app.repositories.audit_repository import AuditRepository
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

    def _validate_future_datetime(self, appointment_date: date, appointment_time: time) -> None:
        from datetime import timezone, timedelta

        ist_tz = timezone(timedelta(hours=5, minutes=30))
        now_ist = datetime.now(ist_tz)
        today_ist = now_ist.date()

        if appointment_date < today_ist:
            raise BadRequestException("Cannot book or reschedule an appointment for a past date")

        if appointment_date == today_ist and appointment_time is not None:
            now_time_ist = now_ist.time()
            if appointment_time < now_time_ist:
                raise BadRequestException(
                    "Cannot book or reschedule an appointment for a past time slot today"
                )

    async def _validate_entities(self, patient_id: int, doctor_id: int) -> None:
        if not await self.patient_repo.get_by_id(patient_id):
            raise NotFoundException("Patient not found")
        doctor = await self.doctor_repo.get_by_id(doctor_id)
        if not doctor:
            raise NotFoundException("Doctor not found")
        if doctor.availability_status not in ("available", "busy"):
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
    ):
        skip = (page - 1) * size
        items = await self.repo.list_all(
            skip=skip, limit=size, patient_id=patient_id, doctor_id=doctor_id,
            department_id=department_id, status=status, appointment_date=appointment_date,
        )
        total = await self.repo.count_all(
            patient_id=patient_id, doctor_id=doctor_id,
            department_id=department_id, status=status, appointment_date=appointment_date,
        )
        return build_paginated_result(
            [AppointmentResponse.model_validate(a) for a in items], total, page, size
        )

    async def get_by_id(self, appointment_id: int) -> AppointmentResponse:
        appointment = await self.repo.get_by_id(appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
        return AppointmentResponse.model_validate(appointment)

    async def get_token(self, appointment_id: int) -> TokenResponse:
        appointment = await self.repo.get_by_id(appointment_id)

        if not appointment:
           raise NotFoundException("Appointment not found")

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
        self._validate_future_datetime(data.appointment_date, data.appointment_time)
        await self._validate_entities(data.patient_id, data.doctor_id)
        rules = await self.validation_service.validate(data.doctor_id, data.appointment_date, data.appointment_time)

        token = await self.repo.get_next_token(data.doctor_id, data.appointment_date)
        appointment = Appointment(
            appointment_number=generate_appointment_number(),
            token_number=token,
            appointment_status=AppointmentStatus.PENDING,
            **data.model_dump(),
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
        new_date = update_data.get("appointment_date", appointment.appointment_date)
        new_time = update_data.get("appointment_time", appointment.appointment_time)
        
        if "appointment_date" in update_data or "appointment_time" in update_data:
            self._validate_future_datetime(new_date, new_time)

        if "appointment_date" in update_data or "appointment_time" in update_data:
            rules = await self.validation_service.validate(appointment.doctor_id, new_date, new_time, exclude_id=appointment_id)

        for key, value in update_data.items():
            setattr(appointment, key, value)
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
        self._validate_future_datetime(data.appointment_date, data.appointment_time)
        rules = await self.validation_service.validate(
            appointment.doctor_id, data.appointment_date, data.appointment_time, exclude_id=appointment.id
        )
        appointment.appointment_date = data.appointment_date
        appointment.appointment_time = data.appointment_time
        appointment.appointment_status = AppointmentStatus.PENDING
        if data.notes:
            appointment.notes = data.notes
        appointment = await self.repo.update(appointment)
        await self.audit_repo.create("reschedule", "appointments", user_id=user_id, resource_id=str(appointment.id))
        return AppointmentResponse.model_validate(appointment)

    async def cancel(self, data: CancelRequest, user_id: int) -> AppointmentResponse:
        appointment = await self.repo.get_by_id(data.appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
        appointment.appointment_status = AppointmentStatus.CANCELLED
        if data.reason:
            appointment.notes = data.reason
        appointment = await self.repo.update(appointment)
        await self.audit_repo.create("cancel", "appointments", user_id=user_id, resource_id=str(appointment.id))
        return AppointmentResponse.model_validate(appointment)

    async def confirm(self, data: ConfirmRequest, user_id: int) -> AppointmentResponse:
        appointment = await self.repo.get_by_id(data.appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
        appointment.appointment_status = AppointmentStatus.CONFIRMED
        appointment = await self.repo.update(appointment)
        await self.audit_repo.create("confirm", "appointments", user_id=user_id, resource_id=str(appointment.id))
        await self._notify_confirmation_safely(appointment, user_id)
        return AppointmentResponse.model_validate(appointment)

    async def get_calendar(self, start_date: date, end_date: date, doctor_id: int | None = None):
        appointments = await self.repo.get_calendar(start_date, end_date, doctor_id)
        return [AppointmentResponse.model_validate(a) for a in appointments]

    async def get_today(self):
        appointments = await self.repo.get_today()
        return [AppointmentResponse.model_validate(a) for a in appointments]

    async def get_upcoming(self, limit: int = 20):
        appointments = await self.repo.get_upcoming(limit)
        return [AppointmentResponse.model_validate(a) for a in appointments]

    async def check_in(self, appointment_id: int, user_id: int) -> Appointment:
        appointment = await self.repo.get_by_id(appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
        if appointment.appointment_status in ("Checked-In", "Checked_In", "checked_in"):
            raise BadRequestException("Appointment already checked in")
        appointment.appointment_status = "Checked-In"
        appointment.check_in_time = datetime.now()
        await self.db.flush()
        await self._create_queue_notification(appointment, f"Patient checked in for appointment {appointment.appointment_number}")
        return appointment

    async def check_out(self, appointment_id: int, user_id: int) -> Appointment:
        appointment = await self.repo.get_by_id(appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
        if appointment.appointment_status != "Checked-In":
            raise BadRequestException("Appointment must be checked in first")
        appointment.appointment_status = "Checked-Out"
        appointment.check_out_time = datetime.now()
        await self.db.flush()
        await self._create_queue_notification(appointment, f"Patient checked out for appointment {appointment.appointment_number}")
        return appointment

    async def generate_queue_token(self, appointment_id: int, user_id: int) -> Appointment:
        from sqlalchemy import select
        appointment = await self.repo.get_by_id(appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
        if appointment.queue_token:
            raise BadRequestException("Token already generated for this appointment")
        
        # Calculate next token for today
        today = date.today()
        result = await self.db.execute(
            select(Appointment.queue_token)
            .where(Appointment.appointment_date == today, Appointment.queue_token.isnot(None))
        )
        tokens = result.scalars().all()
        max_num = 0
        for t in tokens:
            if t.startswith("T-"):
                try:
                    num = int(t[2:])
                    if num > max_num:
                        max_num = num
                except ValueError:
                    pass
        next_token = f"T-{max_num + 1}"
        
        appointment.queue_token = next_token
        appointment.queue_status = "WAITING"
        await self.db.flush()
        await self._create_queue_notification(appointment, f"Queue token {next_token} has been generated.")
        return appointment

    async def get_today_queue(self) -> list[Appointment]:
        from sqlalchemy import select
        today = date.today()
        result = await self.db.execute(
            select(Appointment)
            .where(Appointment.appointment_date == today, Appointment.queue_token.isnot(None))
            .order_by(Appointment.id.asc())
        )
        return list(result.scalars().all())

    async def get_current_queue(self) -> Appointment | None:
        from sqlalchemy import select
        today = date.today()
        result = await self.db.execute(
            select(Appointment)
            .where(
                Appointment.appointment_date == today,
                Appointment.queue_status.in_(["CALLED", "IN_PROGRESS"])
            )
            .order_by(Appointment.updated_at.desc(), Appointment.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def call_next_token(self, appointment_id: int, user_id: int) -> Appointment:
        appointment = await self.repo.get_by_id(appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
        appointment.queue_status = "CALLED"
        await self.db.flush()
        await self._create_queue_notification(appointment, f"Doctor is calling patient (Token {appointment.queue_token})")
        return appointment

    async def complete_token(self, appointment_id: int, user_id: int) -> Appointment:
        appointment = await self.repo.get_by_id(appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
        appointment.queue_status = "COMPLETED"
        await self.db.flush()
        return appointment

    async def skip_token(self, appointment_id: int, user_id: int) -> Appointment:
        appointment = await self.repo.get_by_id(appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
        appointment.queue_status = "SKIPPED"
        await self.db.flush()
        return appointment

    async def _create_queue_notification(self, appointment: Appointment, message: str) -> None:
        from app.models.notification_model import Notification
        from app.models.doctor_model import Doctor
        from app.models.patient_model import Patient
        from sqlalchemy import select
        
        # Find doctor user_id
        doc_user_id = await self.db.scalar(
            select(Doctor.user_id).where(Doctor.id == appointment.doctor_id)
        )
        # Find patient user_id
        pat_user_id = await self.db.scalar(
            select(Patient.user_id).where(Patient.id == appointment.patient_id)
        )
        
        if doc_user_id:
            doc_notif = Notification(
                user_id=doc_user_id,
                title="Appointment Queue Alert",
                message=message,
                notification_type="QUEUE_ALERT",
                reference_type="APPOINTMENT",
                reference_id=appointment.id,
                priority="NORMAL",
                is_read=False
            )
            self.db.add(doc_notif)
            
        if pat_user_id:
            pat_notif = Notification(
                user_id=pat_user_id,
                title="Appointment Queue Alert",
                message=message,
                notification_type="QUEUE_ALERT",
                reference_type="APPOINTMENT",
                reference_id=appointment.id,
                priority="NORMAL",
                is_read=False
            )
            self.db.add(pat_notif)
        await self.db.flush()

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
