from datetime import date, datetime, time, timedelta
from typing import List, Optional
import os

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AppointmentStatus, DayOfWeek
from app.core.exceptions import ConflictException, NotFoundException
from app.models.appointment_model import Appointment
from app.models.patient_model import Patient, PatientDocument
from app.models.department_model import Department
from app.models.doctor_model import Doctor, DoctorSchedule
from app.repositories.appointment_repository import AppointmentRepository
from app.repositories.audit_repository import AuditRepository
from app.repositories.doctor_repository import DoctorRepository
from app.repositories.patient_repository import PatientRepository
from app.schemas.appointment_schema import AppointmentResponse
from app.schemas.public_schema import (
    AdvancedBookingRequest,
    PublicDoctorResponse,
    PublicDoctorWorkingDay,
    QuickBookingRequest,
    ReportUploadResponse,
    SymptomAnalysisRequest,
    SymptomAnalysisResponse,
    SuggestedSlotPublic,
)
from app.utils.file_upload import save_upload_file
from app.utils.helpers import generate_appointment_number, generate_mrn
from app.ai.symptom_analysis.analyzer import SymptomAnalyzer
from app.ai.appointment_assistant.assistant import DEFAULT_SLOTS, SPECIALIST_ALIASES


class PublicService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AppointmentRepository(db)
        self.patient_repo = PatientRepository(db)
        self.doctor_repo = DoctorRepository(db)
        self.audit_repo = AuditRepository(db)

    async def get_doctor_available_slots(self, doctor_id: int, target_date: date) -> List[str]:
        day_of_week = target_date.weekday()
        
        result = await self.db.execute(
            select(DoctorSchedule).where(
                DoctorSchedule.doctor_id == doctor_id,
                DoctorSchedule.day_of_week == day_of_week,
                DoctorSchedule.is_active.is_(True)
            )
        )
        schedules = result.scalars().all()
        
        slots_time = []
        if not schedules:
            slots_time = DEFAULT_SLOTS[:]
        else:
            for sched in schedules:
                curr = datetime.combine(target_date, sched.start_time)
                end = datetime.combine(target_date, sched.end_time)
                duration = sched.slot_duration_minutes or 30
                while curr < end:
                    slots_time.append(curr.time())
                    curr += timedelta(minutes=duration)
        
        # Query active appointments
        result = await self.db.execute(
            select(Appointment.appointment_time).where(
                Appointment.doctor_id == doctor_id,
                Appointment.appointment_date == target_date,
                Appointment.appointment_status.in_(list(AppointmentStatus.ACTIVE))
            )
        )
        booked_times = {row[0] for row in result.all()}
        
        available = []
        for slot in slots_time:
            if slot not in booked_times:
                available.append(slot.strftime("%H:%M"))
                
        return available

    def _build_weekly_schedule(self, schedules: list[DoctorSchedule]) -> tuple[list[str], list[PublicDoctorWorkingDay]]:
        active = sorted(
            (s for s in schedules if s.is_active),
            key=lambda s: s.day_of_week,
        )
        working_days = [DayOfWeek.name_for(s.day_of_week) for s in active]
        weekly_schedule = [
            PublicDoctorWorkingDay(
                day_of_week=s.day_of_week,
                day_name=DayOfWeek.name_for(s.day_of_week),
                start_time=s.start_time,
                end_time=s.end_time,
                slot_duration_minutes=s.slot_duration_minutes or 30,
            )
            for s in active
        ]
        return working_days, weekly_schedule

    async def list_public_doctors(
        self,
        department_id: Optional[int] = None,
        department: Optional[str] = None,
        specialty: Optional[str] = None,
        appointment_date: Optional[date] = None,
    ) -> List[PublicDoctorResponse]:
        from sqlalchemy.orm import selectinload
        # Base query to get all non-deleted, available doctors with department eagerly loaded
        query = select(Doctor).options(
            selectinload(Doctor.department),
            selectinload(Doctor.schedules),
        ).where(
            Doctor.is_deleted.is_(False),
            Doctor.availability_status == "available"
        )

        resolved_department_id = department_id
        if resolved_department_id is None and department:
            if department.isdigit():
                resolved_department_id = int(department)
            else:
                query = query.join(Doctor.department).where(
                    func.lower(Department.department_name) == department.lower().strip()
                )

        if resolved_department_id is not None:
            query = query.where(Doctor.department_id == resolved_department_id)
        
        if specialty:
            query = query.where(Doctor.specialization.ilike(f"%{specialty}%"))
            
        result = await self.db.execute(query)
        doctors = result.scalars().all()
        
        target_date = appointment_date or (date.today() + timedelta(days=1))
        
        response_list = []
        for doc in doctors:
            dept_name = doc.department.department_name if doc.department else None
            if department:
                matched_dept = False
                if department.isdigit() and doc.department_id == int(department):
                    matched_dept = True
                elif dept_name:
                    import re
                    pattern = rf"\b{re.escape(department.lower())}\b"
                    if re.search(pattern, dept_name.lower()):
                        matched_dept = True
                if not matched_dept:
                    continue
            
            working_days, weekly_schedule = self._build_weekly_schedule(doc.schedules)
            is_available_on_date = target_date.weekday() in {s.day_of_week for s in doc.schedules if s.is_active}

            # Fetch slots
            slots = await self.get_doctor_available_slots(doc.id, target_date)
            
            # If explicit date was filtered, only return doctor if they have available slots
            if appointment_date and not slots:
                continue
                
            response_list.append(
                PublicDoctorResponse(
                    id=doc.id,
                    name=f"Dr. {doc.first_name} {doc.last_name}",
                    specialty=doc.specialization,
                    department=dept_name,
                    department_id=doc.department_id,
                    experience=doc.experience,
                    working_days=working_days,
                    weekly_schedule=weekly_schedule,
                    availability_slots=slots,
                    is_available_on_date=is_available_on_date,
                )
            )
            
        return response_list

    async def quick_book_appointment(self, data: QuickBookingRequest) -> AppointmentResponse:
        # 1. Lookup or create patient
        patient = await self.patient_repo.get_by_phone(data.patient_phone)
        if not patient:
            parts = data.patient_name.split(maxsplit=1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else ""
            patient = Patient(
                patient_code=generate_mrn(),
                first_name=first_name,
                last_name=last_name,
                phone=data.patient_phone,
                status="active"
            )
            patient = await self.patient_repo.create(patient)
            
        # 2. Check doctor availability and conflict
        doctor = await self.doctor_repo.get_by_id(data.doctor_id)
        if not doctor:
            raise NotFoundException("Doctor not found")
        if doctor.availability_status not in ("available", "busy"):
            raise ConflictException("Doctor is not available for appointments")
            
        conflict = await self.repo.exists_conflict(data.doctor_id, data.date, data.time_slot)
        if conflict:
            raise ConflictException("Doctor already has an appointment at this slot")
            
        # 3. Create appointment
        token = await self.repo.get_next_token(data.doctor_id, data.date)
        appointment = Appointment(
            appointment_number=generate_appointment_number(),
            patient_id=patient.id,
            doctor_id=data.doctor_id,
            department_id=doctor.department_id,
            appointment_date=data.date,
            appointment_time=data.time_slot,
            symptoms=data.symptoms,
            token_number=token,
            appointment_status=AppointmentStatus.PENDING,
        )
        appointment = await self.repo.create(appointment)
        await self.audit_repo.create("create", "appointments", user_id=None, resource_id=str(appointment.id))
        return AppointmentResponse.model_validate(appointment)

    async def analyze_symptoms(self, data: SymptomAnalysisRequest) -> SymptomAnalysisResponse:
        # Split symptoms text by comma
        symptoms_list = [s.strip() for s in data.symptoms.split(",") if s.strip()]
        if not symptoms_list:
            symptoms_list = [data.symptoms]
            
        analyzer = SymptomAnalyzer()
        analysis = await analyzer.analyze(symptoms_list)
        urgency = analysis.get("urgency", "low")
        specialist = analysis.get("recommended_specialist", "general_physician")
        
        # Match a suggested doctor
        aliases = SPECIALIST_ALIASES.get(specialist, [specialist.replace("_", " ")])
        from sqlalchemy.orm import selectinload
        doc_res = await self.db.execute(
            select(Doctor).options(selectinload(Doctor.department)).where(
                Doctor.is_deleted.is_(False),
                Doctor.availability_status == "available"
            )
        )
        all_doctors = doc_res.scalars().all()
        matched = [
            d for d in all_doctors
            if any(alias in (d.specialization or "").lower() or (d.department.department_name if d.department else "").lower() in aliases for alias in aliases)
        ]
        suggested_doctor = matched[0] if matched else (all_doctors[0] if all_doctors else None)
        
        slots = []
        suggested_doc_id = None
        suggested_doc_name = None
        dept_name = None
        dept_id = None
        
        if suggested_doctor:
            suggested_doc_id = suggested_doctor.id
            suggested_doc_name = f"Dr. {suggested_doctor.first_name} {suggested_doctor.last_name}"
            dept_name = suggested_doctor.department.department_name if suggested_doctor.department else None
            dept_id = suggested_doctor.department_id
            
            target_date = date.today() + timedelta(days=1)
            available_times = await self.get_doctor_available_slots(suggested_doctor.id, target_date)
            for t_str in available_times:
                t_val = time.fromisoformat(t_str)
                slots.append(SuggestedSlotPublic(appointment_date=target_date, appointment_time=t_val))
                
        insights = f"AI has analyzed your symptoms and recommends consulting a {specialist.replace('_', ' ')}. " \
                   f"We suggest booking an appointment with {suggested_doc_name or 'our general practitioner'}."
                   
        return SymptomAnalysisResponse(
            urgency_level=urgency,
            confidence_score=0.85,  # Placeholder score
            specialty=specialist,
            department=dept_name,
            department_id=dept_id,
            suggested_doctor_id=suggested_doc_id,
            suggested_doctor_name=suggested_doc_name,
            available_slots=slots,
            insights=insights
        )

    async def upload_public_report(self, file: UploadFile, patient_phone: str, patient_name: Optional[str] = None) -> ReportUploadResponse:
        # Find or create patient
        patient = await self.patient_repo.get_by_phone(patient_phone)
        if not patient:
            parts = (patient_name or "Public Patient").split(maxsplit=1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else ""
            patient = Patient(
                patient_code=generate_mrn(),
                first_name=first_name,
                last_name=last_name,
                phone=patient_phone,
                status="active"
            )
            patient = await self.patient_repo.create(patient)
            
        file_path = await save_upload_file(file, subfolder="patient_reports")
        
        doc = PatientDocument(
            patient_id=patient.id,
            document_name=file.filename or "report",
            document_type="Report",
            file_path=file_path,
            uploaded_by=None
        )
        doc = await self.patient_repo.add_document(doc)
        await self.audit_repo.create("upload", "patient_documents", user_id=None, resource_id=str(doc.id))
        
        # Build URL
        file_url = "/" + file_path.replace("app/", "") if file_path.startswith("app/") else f"/uploads/patient_reports/{os.path.basename(file_path)}"
        
        return ReportUploadResponse(
            document_id=doc.id,
            file_name=doc.document_name,
            file_url=file_url
        )

    async def advanced_book_appointment(self, data: AdvancedBookingRequest) -> AppointmentResponse:
        # 1. Lookup or create patient
        patient = await self.patient_repo.get_by_phone(data.patient_phone)
        if not patient:
            parts = data.patient_name.split(maxsplit=1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else ""
            patient = Patient(
                patient_code=generate_mrn(),
                first_name=first_name,
                last_name=last_name,
                phone=data.patient_phone,
                email=data.email,
                gender=data.gender,
                dob=data.dob,
                status="active"
            )
            patient = await self.patient_repo.create(patient)
        else:
            updated = False
            if not patient.email and data.email:
                patient.email = data.email
                updated = True
            if not patient.gender and data.gender:
                patient.gender = data.gender
                updated = True
            if not patient.dob and data.dob:
                patient.dob = data.dob
                updated = True
            if updated:
                await self.patient_repo.update(patient)
                
        # 2. Check doctor availability and conflict
        doctor = await self.doctor_repo.get_by_id(data.doctor_id)
        if not doctor:
            raise NotFoundException("Doctor not found")
        if doctor.availability_status not in ("available", "busy"):
            raise ConflictException("Doctor is not available for appointments")
            
        conflict = await self.repo.exists_conflict(data.doctor_id, data.booking_date, data.booking_time)
        if conflict:
            raise ConflictException("Doctor already has an appointment at this slot")
            
        # 3. Handle document linking if provided
        doc_details = ""
        if data.document_id:
            result = await self.db.execute(select(PatientDocument).where(PatientDocument.id == data.document_id))
            doc = result.scalar_one_or_none()
            if doc:
                doc.patient_id = patient.id
                await self.patient_repo.update(doc)
                file_url = "/" + doc.file_path.replace("app/", "") if doc.file_path.startswith("app/") else f"/uploads/patient_reports/{os.path.basename(doc.file_path)}"
                doc_details = f"\n- Attached Report: {doc.document_name} ({file_url})"
                
        # 4. Save AI insights in notes
        notes = f"AI Triage Urgency: {data.urgency_level}\n" \
                f"Referral Specialty: {data.specialty}\n" \
                f"Confidence Score: {data.confidence_score}\n" \
                f"AI Insights: {data.insights}{doc_details}"
                
        # 5. Create appointment
        token = await self.repo.get_next_token(data.doctor_id, data.booking_date)
        appointment = Appointment(
            appointment_number=generate_appointment_number(),
            patient_id=patient.id,
            doctor_id=data.doctor_id,
            department_id=doctor.department_id,
            appointment_date=data.booking_date,
            appointment_time=data.booking_time,
            symptoms=f"Symptom Specialty: {data.specialty}",
            notes=notes,
            token_number=token,
            appointment_status=AppointmentStatus.PENDING,
        )
        appointment = await self.repo.create(appointment)
        await self.audit_repo.create("create", "appointments", user_id=None, resource_id=str(appointment.id))
        return AppointmentResponse.model_validate(appointment)
