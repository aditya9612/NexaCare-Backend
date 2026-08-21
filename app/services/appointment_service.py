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
    ScheduledDoctorResponse,
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
                appointment_time = appt_dt_ist.time()

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
        appointment_type: str | None = None,
    ):
        skip = (page - 1) * size
        items = await self.repo.list_all(
            skip=skip, limit=size, patient_id=patient_id, doctor_id=doctor_id,
            department_id=department_id, status=status, appointment_date=appointment_date,
            appointment_type=appointment_type,
        )
        total = await self.repo.count_all(
            patient_id=patient_id, doctor_id=doctor_id,
            department_id=department_id, status=status, appointment_date=appointment_date,
            appointment_type=appointment_type,
        )

        # Calculate summary counts independently of pagination and status/date filters where appropriate
        from app.utils.helpers import utc_now
        today = utc_now().date()
        
        total_appointments = await self.repo.count_all(
            patient_id=patient_id, doctor_id=doctor_id, department_id=department_id
        )
        today_appointments = await self.repo.count_all(
            patient_id=patient_id, doctor_id=doctor_id, department_id=department_id,
            appointment_date=today
        )
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
            "total_scheduled": total_scheduled,
            "completed": completed,
            "cancelled": cancelled,
            "pending": pending,
            "confirmed": confirmed,
            "in_progress": in_progress,
            "checked_in": checked_in,
            "checked_out": checked_out,
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
        has_updated = False
        for a in appointments:
            if not a.queue_token:
                a.queue_token = await self.repo.get_next_queue_token(a.appointment_date)
                if not a.queue_status:
                    a.queue_status = "WAITING"
                has_updated = True
        if has_updated:
            await self.db.flush()
        return [AppointmentResponse.model_validate(a) for a in appointments]

    async def get_upcoming(self, limit: int = 20):
        appointments = await self.repo.get_upcoming(limit)
        return [AppointmentResponse.model_validate(a) for a in appointments]

    async def check_in(self, appointment_id: int, user_id: int) -> Appointment:
        appointment = await self.repo.get_by_id(appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
        if appointment.appointment_status not in (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED):
            if appointment.appointment_status in ("Checked-In", "Checked_In", "checked_in"):
                raise BadRequestException("Appointment already checked in")
            elif appointment.appointment_status in (AppointmentStatus.COMPLETED, "Checked-Out"):
                raise BadRequestException("Cannot check in a completed or checked-out appointment")
            else:
                raise BadRequestException(f"Cannot check in appointment with status: {appointment.appointment_status}")
        appointment.appointment_status = "Checked-In"
        appointment.check_in_time = datetime.now()
        if not appointment.queue_token:
            appointment.queue_token = await self.repo.get_next_queue_token(appointment.appointment_date)
        if not appointment.queue_status:
            appointment.queue_status = "WAITING"
        await self.db.flush()
        await self._create_queue_notification(appointment, f"Patient checked in for appointment {appointment.appointment_number}")
        return appointment

    async def check_out(self, appointment_id: int, user_id: int) -> Appointment:
        appointment = await self.repo.get_by_id(appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
        if appointment.appointment_status != "Checked-In":
            raise BadRequestException("Appointment must be checked in first")

        # Enforce that patient cannot check out before the appointment start time
        if appointment.appointment_date and appointment.appointment_time:
            from datetime import timezone, timedelta
            ist_tz = timezone(timedelta(hours=5, minutes=30))
            now_ist = datetime.now(ist_tz).replace(tzinfo=None)
            appt_start_datetime = datetime.combine(appointment.appointment_date, appointment.appointment_time)
            if now_ist < appt_start_datetime:
                raise BadRequestException("Patient cannot check out before the appointment start time")

        appointment.appointment_status = "Checked-Out"
        appointment.check_out_time = datetime.now()
        await self.db.flush()
        await self._create_queue_notification(appointment, f"Patient checked out for appointment {appointment.appointment_number}")
        return appointment

    async def generate_queue_token(self, appointment_id: int, user_id: int) -> Appointment:
        appointment = await self.repo.get_by_id(appointment_id)
        if not appointment:
            raise NotFoundException("Appointment not found")
        if appointment.queue_token:
            raise BadRequestException("Token already generated for this appointment")
        
        next_token = await self.repo.get_next_queue_token(appointment.appointment_date)
        
        appointment.queue_token = next_token
        appointment.queue_status = "WAITING"
        await self.db.flush()
        await self._create_queue_notification(appointment, f"Queue token {next_token} has been generated.")
        return appointment

    async def get_today_queue(self) -> list[Appointment]:
        from app.utils.helpers import get_today_ist
        from sqlalchemy import select
        today = get_today_ist()
        result = await self.db.execute(
            select(Appointment)
            .where(Appointment.appointment_date == today)
            .order_by(Appointment.id.asc())
        )
        appointments = list(result.scalars().all())
        has_updated = False
        for a in appointments:
            if not a.queue_token:
                a.queue_token = await self.repo.get_next_queue_token(a.appointment_date)
                if not a.queue_status:
                    a.queue_status = "WAITING"
                has_updated = True
        if has_updated:
            await self.db.flush()
        return appointments

    async def get_current_queue(self) -> Appointment | None:
        from datetime import timezone, timedelta
        from sqlalchemy import select
        ist_tz = timezone(timedelta(hours=5, minutes=30))
        today = datetime.now(ist_tz).date()
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

