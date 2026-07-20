from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import LabOrderStatus
from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.models.lab_model import TestOrder
from app.models.nurse_model import Nurse, NurseAttendance, NurseHandoverNote, NurseShift, PatientVital
from app.repositories.nurse_repository import (
    NurseAttendanceRepository,
    NurseHandoverNoteRepository,
    NurseNotificationRepository,
    NursePatientAssignmentRepository,
    NursePatientLabTestRepository,
    NursePatientVitalRepository,
    NurseRepository,
    NurseShiftRepository,
    NurseTaskRepository,
)
from app.repositories.audit_repository import AuditRepository
from app.repositories.department_repository import DepartmentRepository
from app.repositories.auth_repository import AuthRepository
from app.schemas.patient_schema import PatientResponse
from app.schemas.nurse_schema import (
    NurseAssignedPatientProfileResponse,
    NurseAssignedPatientStatusResponse,
    NurseAttendanceCreate,
    NurseAttendanceResponse,
    NurseCreate,
    NurseHandoverNoteCreate,
    NurseHandoverNoteResponse,
    NurseHandoverNoteUpdate,
    NurseNotificationResponse,
    NurseResponse,
    NurseShiftCreate,
    NurseShiftDetailsResponse,
    NurseShiftResponse,
    NurseShiftUpdate,
    NurseUpdate,
    PatientVitalCreate,
    PatientVitalResponse,
    NurseTaskResponse,
    NurseTaskStatusUpdate,
    NursePatientLabTestResponse,
)
from app.utils.helpers import generate_nurse_code, utc_now
from app.utils.pagination import build_paginated_result


class NurseService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = NurseRepository(db)
        self.shift_repo = NurseShiftRepository(db)
        self.attendance_repo = NurseAttendanceRepository(db)
        self.handover_repo = NurseHandoverNoteRepository(db)
        self.assignment_repo = NursePatientAssignmentRepository(db)
        self.lab_test_repo = NursePatientLabTestRepository(db)
        self.vital_repo = NursePatientVitalRepository(db)
        self.task_repo = NurseTaskRepository(db)
        self.notification_repo = NurseNotificationRepository(db)
        self.audit_repo = AuditRepository(db)
        self.dept_repo = DepartmentRepository(db)
        self.auth_repo = AuthRepository(db)

    async def _validate_department(self, department_id: int | None) -> None:
        if department_id is not None:
            dept = await self.dept_repo.get_by_id(department_id)
            if not dept:
                raise NotFoundException(f"Department with ID {department_id} not found")

    async def _get_nurse_or_raise(self, nurse_id: int) -> Nurse:
        nurse = await self.repo.get_by_id(nurse_id)
        if not nurse:
            raise NotFoundException("Nurse not found")
        return nurse

    async def list_nurses(
        self,
        page: int = 1,
        size: int = 20,
        department_id: int | None = None,
        shift: str | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ):
        skip = (page - 1) * size
        items = await self.repo.list_all(
            skip=skip,
            limit=size,
            department_id=department_id,
            shift=shift,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        total = await self.repo.count_all(department_id=department_id, shift=shift)
        return build_paginated_result(
            [NurseResponse.model_validate(n) for n in items], total, page, size
        )

    async def get_by_id(self, nurse_id: int) -> NurseResponse:
        nurse = await self._get_nurse_or_raise(nurse_id)
        return NurseResponse.model_validate(nurse)

    async def create(self, data: NurseCreate, user_id: int) -> NurseResponse:
        # Validate that the user exists
        user = await self.auth_repo.get_by_id(data.user_id)
        if not user:
            raise NotFoundException("User not found")

        # Validate that the user is not already registered as a nurse
        existing_nurse = await self.repo.get_by_user_id(data.user_id)
        if existing_nurse:
            raise ConflictException("User is already registered as a nurse")

        existing = await self.repo.get_by_license(data.license_number)
        if existing:
            raise ConflictException("License number already registered")
        await self._validate_department(data.department_id)
        nurse = Nurse(nurse_code=generate_nurse_code(), **data.model_dump())
        nurse = await self.repo.create(nurse)
        await self.audit_repo.create("create", "nurses", user_id=user_id, resource_id=str(nurse.id))
        return NurseResponse.model_validate(nurse)

    async def update(self, nurse_id: int, data: NurseUpdate, user_id: int) -> NurseResponse:
        nurse = await self._get_nurse_or_raise(nurse_id)
        if data.license_number and data.license_number != nurse.license_number:
            existing = await self.repo.get_by_license(data.license_number)
            if existing:
                raise ConflictException("License number already registered")
        await self._validate_department(data.department_id)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(nurse, key, value)
        nurse = await self.repo.update(nurse)
        await self.audit_repo.create("update", "nurses", user_id=user_id, resource_id=str(nurse.id))
        return NurseResponse.model_validate(nurse)

    async def delete(self, nurse_id: int, user_id: int) -> None:
        nurse = await self._get_nurse_or_raise(nurse_id)
        if nurse.user_id:
            from app.models.user_model import User
            user = await self.db.get(User, nurse.user_id)
            if user:
                user.is_active = False
        await self.repo.delete(nurse)
        await self.audit_repo.create("delete", "nurses", user_id=user_id, resource_id=str(nurse_id))

    async def search(self, q: str, page: int = 1, size: int = 20):
        skip = (page - 1) * size
        items = await self.repo.search(q, skip=skip, limit=size)
        total = await self.repo.count_search(q)
        return build_paginated_result(
            [NurseResponse.model_validate(n) for n in items], total, page, size
        )

    async def list_shifts(
        self,
        nurse_id: int,
        page: int = 1,
        size: int = 20,
        start_date: date | None = None,
        end_date: date | None = None,
        shift_name: str | None = None,
        sort_by: str = "shift_date",
        sort_order: str = "desc",
    ):
        await self._get_nurse_or_raise(nurse_id)
        skip = (page - 1) * size
        items = await self.shift_repo.list_by_nurse(
            nurse_id=nurse_id,
            skip=skip,
            limit=size,
            start_date=start_date,
            end_date=end_date,
            shift_name=shift_name,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        total = await self.shift_repo.count_by_nurse(
            nurse_id=nurse_id,
            start_date=start_date,
            end_date=end_date,
            shift_name=shift_name,
        )
        return build_paginated_result(
            [NurseShiftResponse.model_validate(item) for item in items],
            total,
            page,
            size,
        )

    async def get_shift_details(self, nurse_id: int) -> NurseShiftDetailsResponse:
        await self._get_nurse_or_raise(nurse_id)
        shift = await self.shift_repo.get_latest_by_nurse(nurse_id)
        if not shift:
            raise NotFoundException("No shift found for this nurse")
        return NurseShiftDetailsResponse(
            shift_name=shift.shift_name,
            shift_date=shift.shift_date,
            start_time=shift.start_time,
            end_time=shift.end_time,
            status=shift.status,
            notes=shift.notes,
        )

    async def create_shift(
        self, nurse_id: int, data: NurseShiftCreate, user_id: int
    ) -> NurseShiftResponse:
        await self._get_nurse_or_raise(nurse_id)
        shift = NurseShift(nurse_id=nurse_id, **data.model_dump())
        shift = await self.shift_repo.create(shift)
        await self.audit_repo.create(
            "create", "nurses", user_id=user_id, resource_id=str(shift.id)
        )
        return NurseShiftResponse.model_validate(shift)

    async def update_shift(
        self,
        nurse_id: int,
        shift_id: int,
        data: NurseShiftUpdate,
        user_id: int,
    ) -> NurseShiftResponse:
        await self._get_nurse_or_raise(nurse_id)
        shift = await self.shift_repo.get_by_id_for_nurse(shift_id, nurse_id)
        if not shift:
            raise NotFoundException("Shift not found")
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(shift, key, value)
        shift = await self.shift_repo.update(shift)
        await self.audit_repo.create(
            "update", "nurses", user_id=user_id, resource_id=str(shift.id)
        )
        return NurseShiftResponse.model_validate(shift)

    async def create_attendance(
        self, nurse_id: int, data: NurseAttendanceCreate, user_id: int
    ) -> NurseAttendanceResponse:
        await self._get_nurse_or_raise(nurse_id)
        attendance = NurseAttendance(nurse_id=nurse_id, **data.model_dump())
        attendance = await self.attendance_repo.create(attendance)
        await self.audit_repo.create(
            "create", "nurses", user_id=user_id, resource_id=str(attendance.id)
        )
        return NurseAttendanceResponse.model_validate(attendance)

    async def list_attendance(
        self,
        nurse_id: int,
        page: int = 1,
        size: int = 20,
        start_date: date | None = None,
        end_date: date | None = None,
        status: str | None = None,
        sort_by: str = "attendance_date",
        sort_order: str = "desc",
    ):
        await self._get_nurse_or_raise(nurse_id)
        skip = (page - 1) * size
        items = await self.attendance_repo.list_by_nurse(
            nurse_id=nurse_id,
            skip=skip,
            limit=size,
            start_date=start_date,
            end_date=end_date,
            status=status,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        total = await self.attendance_repo.count_by_nurse(
            nurse_id=nurse_id,
            start_date=start_date,
            end_date=end_date,
            status=status,
        )
        return build_paginated_result(
            [NurseAttendanceResponse.model_validate(item) for item in items],
            total,
            page,
            size,
        )

    async def _validate_shift(self, nurse_id: int, shift_id: int | None) -> None:
        if shift_id is None:
            return
        shift = await self.shift_repo.get_by_id(shift_id)
        if not shift or shift.nurse_id != nurse_id:
            raise NotFoundException(f"Shift with ID {shift_id} not found for this nurse")

    async def create_handover_note(
        self, nurse_id: int, data: NurseHandoverNoteCreate, user_id: int
    ) -> NurseHandoverNoteResponse:
        await self._get_nurse_or_raise(nurse_id)
        await self._validate_shift(nurse_id, data.shift_id)
        note = NurseHandoverNote(nurse_id=nurse_id, **data.model_dump())
        note = await self.handover_repo.create(note)
        await self.audit_repo.create(
            "create", "nurses", user_id=user_id, resource_id=str(note.id)
        )
        return NurseHandoverNoteResponse.model_validate(note)

    async def list_handover_notes(
        self,
        nurse_id: int,
        page: int = 1,
        size: int = 20,
        start_date: date | None = None,
        end_date: date | None = None,
        status: str | None = None,
        shift_id: int | None = None,
        sort_by: str = "handover_date",
        sort_order: str = "desc",
    ):
        await self._get_nurse_or_raise(nurse_id)
        skip = (page - 1) * size
        items = await self.handover_repo.list_by_nurse(
            nurse_id=nurse_id,
            skip=skip,
            limit=size,
            start_date=start_date,
            end_date=end_date,
            status=status,
            shift_id=shift_id,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        total = await self.handover_repo.count_by_nurse(
            nurse_id=nurse_id,
            start_date=start_date,
            end_date=end_date,
            status=status,
            shift_id=shift_id,
        )
        return build_paginated_result(
            [NurseHandoverNoteResponse.model_validate(item) for item in items],
            total,
            page,
            size,
        )

    async def update_handover_note(
        self,
        nurse_id: int,
        note_id: int,
        data: NurseHandoverNoteUpdate,
        user_id: int,
    ) -> NurseHandoverNoteResponse:
        await self._get_nurse_or_raise(nurse_id)
        note = await self.handover_repo.get_by_id(note_id, nurse_id)
        if not note:
            raise NotFoundException("Handover note not found")
        update_data = data.model_dump(exclude_unset=True)
        if "shift_id" in update_data:
            await self._validate_shift(nurse_id, update_data["shift_id"])
        for key, value in update_data.items():
            setattr(note, key, value)
        note = await self.handover_repo.update(note)
        await self.audit_repo.create(
            "update", "nurses", user_id=user_id, resource_id=str(note.id)
        )
        return NurseHandoverNoteResponse.model_validate(note)

    async def list_assigned_patients(
        self,
        nurse_id: int,
        page: int = 1,
        size: int = 20,
        status: str | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ):
        await self._get_nurse_or_raise(nurse_id)
        skip = (page - 1) * size
        items = await self.assignment_repo.list_patients_by_nurse(
            nurse_id=nurse_id,
            skip=skip,
            limit=size,
            status=status,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        total = await self.assignment_repo.count_patients_by_nurse(
            nurse_id=nurse_id,
            status=status,
        )
        return build_paginated_result(
            [PatientResponse.model_validate(p) for p in items],
            total,
            page,
            size,
        )

    async def get_assigned_patient_profile(
        self, nurse_id: int, patient_id: int
    ) -> NurseAssignedPatientProfileResponse:
        await self._get_nurse_or_raise(nurse_id)
        patient = await self.assignment_repo.get_patient_by_id(patient_id)
        if not patient:
            raise NotFoundException("Patient not found")
        row = await self.assignment_repo.get_assigned_patient(nurse_id, patient_id)
        if not row:
            raise NotFoundException("Patient is not assigned to this nurse")
        patient, assignment = row
        return NurseAssignedPatientProfileResponse(
            id=patient.id,
            patient_code=patient.patient_code,
            first_name=patient.first_name,
            last_name=patient.last_name,
            gender=patient.gender,
            dob=patient.dob,
            blood_group=patient.blood_group,
            marital_status=patient.marital_status,
            phone=patient.phone,
            email=patient.email,
            address=patient.address,
            city=patient.city,
            state=patient.state,
            pincode=patient.pincode,
            emergency_contact_name=patient.emergency_contact_name,
            emergency_contact_number=patient.emergency_contact_number,
            medical_history=patient.medical_history,
            allergies=patient.allergies,
            diagnosis=patient.chronic_disease,
            patient_status=assignment.patient_status,
            assignment_status=assignment.status,
            status=patient.status,
            assignment_notes=assignment.notes,
            insurance_provider=patient.insurance_provider,
            insurance_number=patient.insurance_number,
            created_at=patient.created_at,
            updated_at=patient.updated_at,
        )

    async def record_patient_vitals(
        self,
        nurse_id: int,
        patient_id: int,
        data: PatientVitalCreate,
        user_id: int,
    ) -> PatientVitalResponse:
        await self._get_nurse_or_raise(nurse_id)
        patient = await self.assignment_repo.get_patient_by_id(patient_id)
        if not patient:
            raise NotFoundException("Patient not found")
        assignment = await self.assignment_repo.get_assigned_patient(nurse_id, patient_id)
        if not assignment:
            raise NotFoundException("Patient is not assigned to this nurse")
        vital = PatientVital(
            nurse_id=nurse_id,
            patient_id=patient_id,
            **data.model_dump(),
        )
        vital = await self.vital_repo.create(vital)
        await self.audit_repo.create(
            "create", "nurses", user_id=user_id, resource_id=str(vital.id)
        )
        return PatientVitalResponse.model_validate(vital)

    def _nurse_lab_test_status(self, order_status: str) -> str:
        if order_status == LabOrderStatus.COMPLETED:
            return "Completed"
        return "Pending"

    def _lab_test_result_summary(self, order: TestOrder) -> str | None:
        if order.reports:
            summaries = [report.summary for report in order.reports if report.summary]
            if summaries:
                return summaries[-1]
        if order.results:
            parts = [
                f"{result.parameter_name}: {result.result_value}"
                for result in order.results
                if result.result_value
            ]
            if parts:
                return "; ".join(parts)
        return None

    def _lab_test_response(self, order: TestOrder) -> NursePatientLabTestResponse:
        lab_test = order.lab_test
        return NursePatientLabTestResponse(
            id=order.id,
            order_number=order.order_number,
            test_name=lab_test.test_name if lab_test else "Unknown",
            test_code=lab_test.test_code if lab_test else None,
            category=lab_test.category if lab_test else None,
            sample_type=lab_test.sample_type if lab_test else None,
            request_date=order.ordered_at,
            status=self._nurse_lab_test_status(order.status),
            priority=order.priority,
            notes=order.notes,
            completed_at=order.completed_at,
            result_summary=self._lab_test_result_summary(order),
            created_at=order.created_at,
        )

    async def list_patient_lab_tests(
        self,
        nurse_id: int,
        patient_id: int,
        page: int = 1,
        size: int = 20,
        status: str | None = None,
        sort_by: str = "ordered_at",
        sort_order: str = "desc",
    ):
        await self._get_nurse_or_raise(nurse_id)
        patient = await self.assignment_repo.get_patient_by_id(patient_id)
        if not patient:
            raise NotFoundException("Patient not found")
        assignment = await self.assignment_repo.get_assigned_patient(nurse_id, patient_id)
        if not assignment:
            raise NotFoundException("Patient is not assigned to this nurse")
        if status is not None and status not in ("Pending", "Completed"):
            raise BadRequestException("Status filter must be Pending or Completed")
        skip = (page - 1) * size
        items = await self.lab_test_repo.list_by_patient(
            patient_id=patient_id,
            skip=skip,
            limit=size,
            status=status,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        total = await self.lab_test_repo.count_by_patient(
            patient_id=patient_id,
            status=status,
        )
        return build_paginated_result(
            [self._lab_test_response(item) for item in items],
            total,
            page,
            size,
        )

    async def list_daily_tasks(
        self,
        nurse_id: int,
        page: int = 1,
        size: int = 20,
        patient_id: int | None = None,
        status: str | None = None,
        priority: str | None = None,
        sort_by: str = "priority",
        sort_order: str = "desc",
    ):
        await self._get_nurse_or_raise(nurse_id)
        due_date = utc_now().date()
        skip = (page - 1) * size
        items = await self.task_repo.list_by_nurse(
            nurse_id=nurse_id,
            due_date=due_date,
            skip=skip,
            limit=size,
            patient_id=patient_id,
            status=status,
            priority=priority,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        total = await self.task_repo.count_by_nurse(
            nurse_id=nurse_id,
            due_date=due_date,
            patient_id=patient_id,
            status=status,
            priority=priority,
        )
        return build_paginated_result(
            [NurseTaskResponse.model_validate(item) for item in items],
            total,
            page,
            size,
        )

    async def update_task_status(
        self,
        nurse_id: int,
        task_id: int,
        data: NurseTaskStatusUpdate,
        user_id: int,
    ) -> NurseTaskResponse:
        await self._get_nurse_or_raise(nurse_id)
        task = await self.task_repo.get_by_id(task_id, nurse_id)
        if not task:
            raise NotFoundException("Task not found")
        task.status = data.status
        task = await self.task_repo.update(task)
        await self.audit_repo.create(
            "update", "nurses", user_id=user_id, resource_id=str(task.id)
        )
        return NurseTaskResponse.model_validate(task)

    async def list_assigned_patient_statuses(
        self,
        nurse_id: int,
        page: int = 1,
        size: int = 20,
        assignment_status: str | None = None,
        patient_status: str | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
    ):
        await self._get_nurse_or_raise(nurse_id)
        skip = (page - 1) * size
        rows = await self.assignment_repo.list_patient_statuses_by_nurse(
            nurse_id=nurse_id,
            skip=skip,
            limit=size,
            assignment_status=assignment_status,
            patient_status=patient_status,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        total = await self.assignment_repo.count_patient_statuses_by_nurse(
            nurse_id=nurse_id,
            assignment_status=assignment_status,
            patient_status=patient_status,
        )
        return build_paginated_result(
            [
                NurseAssignedPatientStatusResponse(
                    patient_id=patient.id,
                    patient_code=patient.patient_code,
                    first_name=patient.first_name,
                    last_name=patient.last_name,
                    patient_status=assignment.patient_status,
                    assignment_status=assignment.status,
                    notes=assignment.notes,
                    updated_at=assignment.updated_at,
                )
                for patient, assignment in rows
            ],
            total,
            page,
            size,
        )

    async def list_notifications(
        self,
        nurse_id: int,
        page: int = 1,
        size: int = 20,
        status: str = "Active",
        notification_type: str | None = None,
        priority: str | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ):
        await self._get_nurse_or_raise(nurse_id)
        skip = (page - 1) * size
        items = await self.notification_repo.list_by_nurse(
            nurse_id=nurse_id,
            skip=skip,
            limit=size,
            status=status,
            notification_type=notification_type,
            priority=priority,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        total = await self.notification_repo.count_by_nurse(
            nurse_id=nurse_id,
            status=status,
            notification_type=notification_type,
            priority=priority,
        )
        return build_paginated_result(
            [NurseNotificationResponse.model_validate(item) for item in items],
            total,
            page,
            size,
        )

    async def list_prescriptions(self, patient_id: int | None = None):
        from sqlalchemy import select
        from app.models.nurse_model import NursePrescription
        from app.models.patient_model import Patient
        from app.models.doctor_model import Doctor
        import json

        query = select(NursePrescription, Patient, Doctor).join(
            Patient, NursePrescription.patient_id == Patient.id
        ).join(
            Doctor, NursePrescription.doctor_id == Doctor.id
        )
        if patient_id is not None:
            query = query.where(NursePrescription.patient_id == patient_id)
        
        result = await self.db.execute(query)
        rows = result.all()
        
        prescriptions = []
        for presc, patient, doctor in rows:
            time_of_day = json.loads(presc.time_of_day) if presc.time_of_day else []
            times = json.loads(presc.times) if presc.times else {}
            prescriptions.append({
                "medication_id": f"MED-10{presc.id}",
                "id": presc.id,
                "patient_id": f"P-100{patient.id}",
                "patient_db_id": patient.id,
                "patient_name": f"{patient.first_name} {patient.last_name}",
                "doctor_id": f"DOC-20{doctor.id}",
                "doctor_db_id": doctor.id,
                "doctor_name": f"{doctor.first_name} {doctor.last_name}",
                "medicine_name": presc.medicine_name,
                "dosage": presc.dosage,
                "frequency": presc.frequency,
                "start_date": presc.start_date.isoformat(),
                "end_date": presc.end_date.isoformat(),
                "meal_timing": presc.meal_timing,
                "time_of_day": time_of_day,
                "exact_times": times,
                "duration": f"{presc.duration_value} {presc.duration_unit}" if presc.duration_value else "",
                "special_instructions": presc.special_instructions or "",
                "status": presc.status
            })
        return prescriptions

    async def create_prescription(self, data, user_id: int):
        from app.models.nurse_model import NursePrescription
        from app.models.patient_model import Patient
        from app.models.doctor_model import Doctor
        from sqlalchemy import select, or_
        import json

        patient = await self.db.get(Patient, data.patient_id)
        if not patient:
            raise NotFoundException("Patient not found")

        # Resolve doctor by name if possible
        doctor = None
        if hasattr(data, "doctor_name") and data.doctor_name:
            doc_name = data.doctor_name.replace("Dr. ", "").replace("Dr.", "").strip()
            parts = doc_name.split()
            if len(parts) >= 2:
                first, last = parts[0], parts[-1]
                q = select(Doctor).where(
                    or_(
                        Doctor.first_name.ilike(f"%{first}%"),
                        Doctor.last_name.ilike(f"%{last}%")
                    )
                )
                res = await self.db.execute(q)
                doctor = res.scalar_one_or_none()
            elif len(parts) == 1:
                q = select(Doctor).where(
                    or_(
                        Doctor.first_name.ilike(f"%{parts[0]}%"),
                        Doctor.last_name.ilike(f"%{parts[0]}%")
                    )
                )
                res = await self.db.execute(q)
                doctor = res.scalar_one_or_none()

        if not doctor:
            doctor = await self.db.get(Doctor, data.doctor_id)
            
        if not doctor:
            res = await self.db.execute(select(Doctor).limit(1))
            doctor = res.scalar_one_or_none()

        if not doctor:
            raise NotFoundException("No doctors found in the database. Please seed doctors first.")

        presc = NursePrescription(
            patient_id=data.patient_id,
            doctor_id=doctor.id,
            medicine_name=data.medicine_name,
            dosage=data.dosage,
            frequency=data.frequency,
            start_date=data.start_date,
            end_date=data.end_date,
            meal_timing=data.meal_timing,
            time_of_day=json.dumps(data.time_of_day) if data.time_of_day else "[]",
            times=json.dumps(data.times) if data.times else "{}",
            duration_value=data.duration_value,
            duration_unit=data.duration_unit,
            special_instructions=data.special_instructions,
            status="active"
        )
        self.db.add(presc)
        await self.db.flush()
        await self.db.commit()

        return await self.list_prescriptions(patient_id=data.patient_id)

    async def delete_prescription(self, prescription_id: int, user_id: int):
        from app.models.nurse_model import NursePrescription
        presc = await self.db.get(NursePrescription, prescription_id)
        if not presc:
            raise NotFoundException("Prescription not found")
        await self.db.delete(presc)
        await self.db.commit()

    async def log_medication(self, prescription_id: int, data, user_id: int):
        from app.models.nurse_model import NursePrescription, NurseMedicationLog, Nurse
        from sqlalchemy import select
        import datetime

        presc = await self.db.get(NursePrescription, prescription_id)
        if not presc:
            raise NotFoundException("Prescription not found")

        res = await self.db.execute(select(Nurse).where(Nurse.user_id == user_id))
        nurse = res.scalar_one_or_none()
        nurse_id = nurse.id if nurse else None

        log = NurseMedicationLog(
            prescription_id=prescription_id,
            nurse_id=nurse_id,
            status=data.status,
            time_of_day_slot=data.time_of_day_slot,
            notes=data.notes,
            timestamp=data.timestamp or datetime.datetime.now()
        )
        self.db.add(log)
        await self.db.flush()
        await self.db.commit()
        return log

    async def delete_medication_log(self, prescription_id: int, log_id: int, user_id: int):
        from app.models.nurse_model import NurseMedicationLog
        log = await self.db.get(NurseMedicationLog, log_id)
        if not log:
            raise NotFoundException("Log not found")
        await self.db.delete(log)
        await self.db.commit()

    async def list_medication_schedules(self):
        from sqlalchemy import select
        from app.models.nurse_model import NursePrescription, NurseMedicationLog
        from app.models.patient_model import Patient
        from app.models.doctor_model import Doctor
        from app.models.user_model import User
        from app.models.nurse_model import Nurse
        import json
        import datetime

        query = select(NursePrescription, Patient, Doctor).join(
            Patient, NursePrescription.patient_id == Patient.id
        ).join(
            Doctor, NursePrescription.doctor_id == Doctor.id
        ).where(NursePrescription.status == "active")
        
        result = await self.db.execute(query)
        rows = result.all()

        today_start = datetime.datetime.combine(datetime.date.today(), datetime.time.min)
        today_end = datetime.datetime.combine(datetime.date.today(), datetime.time.max)
        
        logs_query = select(NurseMedicationLog, User).outerjoin(
            Nurse, NurseMedicationLog.nurse_id == Nurse.id
        ).outerjoin(
            User, Nurse.user_id == User.id
        ).where(
            NurseMedicationLog.timestamp.between(today_start, today_end)
        )
        
        logs_result = await self.db.execute(logs_query)
        logs_rows = logs_result.all()
        
        logs_map = {}
        for log, user in logs_rows:
            key = (log.prescription_id, log.time_of_day_slot)
            logs_map[key] = {
                "id": log.id,
                "status": log.status,
                "nurse_id": f"NUR-00{log.nurse_id}" if log.nurse_id else "—",
                "nurse_name": user.full_name if user else "—",
                "notes": log.notes or "",
                "time": log.timestamp.strftime("%I:%M %p Today")
            }

        schedules = []
        for presc, patient, doctor in rows:
            time_of_day = json.loads(presc.time_of_day) if presc.time_of_day else ["Morning"]
            times = json.loads(presc.times) if presc.times else {}
            
            for slot in time_of_day:
                slot_time = times.get(slot, "08:00 AM")
                slot_log = logs_map.get((presc.id, slot))
                
                status = "Due"
                administered = False
                missed = False
                log_id = ""
                nurse_id = "—"
                nurse_name = "—"
                admin_time = "—"
                
                if slot_log:
                    status = slot_log["status"]
                    if status == "Administered":
                        administered = True
                    elif status == "Missed":
                        missed = True
                    log_id = str(slot_log["id"])
                    nurse_id = slot_log["nurse_id"]
                    nurse_name = slot_log["nurse_name"]
                    admin_time = slot_log["time"]
                
                schedules.append({
                    "id": f"sched_{presc.id}_{slot}",
                    "prescription_db_id": presc.id,
                    "log_id": log_id,
                    "admin_id": f"ADM-400{log_id}" if log_id else "—",
                    "patientId": f"P-100{patient.id}",
                    "patient_id": f"P-100{patient.id}",
                    "patientName": f"{patient.first_name} {patient.last_name}",
                    "room": "Ward-101",
                    "medicine": presc.medicine_name,
                    "medicine_name": presc.medicine_name,
                    "dosage": presc.dosage,
                    "scheduledTime": slot_time,
                    "administered": administered,
                    "missed": missed,
                    "status": status,
                    "nurse_id": nurse_id,
                    "nurse_name": nurse_name,
                    "administered_time": admin_time,
                    "time_of_day_slot": slot,
                    "medication_id": f"MED-10{presc.id}",
                    "frequency": presc.frequency,
                    "start_date": presc.start_date.isoformat(),
                    "end_date": presc.end_date.isoformat(),
                    "doctor_id": f"DOC-20{doctor.id}",
                    "doctor_name": f"Dr. {doctor.first_name} {doctor.last_name}",
                    "notes": slot_log["notes"] if slot_log else "",
                })
        return schedules
