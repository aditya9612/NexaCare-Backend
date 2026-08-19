from datetime import date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import LabOrderStatus
from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.models.lab_model import TestOrder
from app.models.nurse_model import Nurse, NurseAttendance, NurseHandoverNote, NurseShift, PatientVital
from app.models.user_model import User
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
    PatientVitalUpdate,
    NurseTaskResponse,
    NurseTaskStatusUpdate,
    NursePatientLabTestResponse,
    NurseTaskCreate,
    NursePatientAssignmentCreate,
    NursePatientAssignmentResponse,
    NurseDashboardResponse,
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
    ) -> NurseShiftResponse | list[NurseShiftResponse]:
        from datetime import date, datetime, timedelta
        from app.models.nurse_model import NurseShift
        from sqlalchemy import select

        await self._get_nurse_or_raise(nurse_id)

        # Normalize start_time and end_time to be timezone-naive
        if data.start_time.tzinfo is not None:
            data.start_time = data.start_time.replace(tzinfo=None)
        if data.end_time.tzinfo is not None:
            data.end_time = data.end_time.replace(tzinfo=None)

        # 2. Start Time Should not be Greater Than End Time
        if data.start_time == data.end_time:
            raise BadRequestException("Start time cannot be equal to end time")

        # 3. It Should be Possible to Create Shift Schedule For Particular Date Range.
        target_dates = []
        is_range = False
        if data.shift_date is not None:
            target_dates = [data.shift_date]
        elif data.start_date is not None and data.end_date is not None:
            if data.start_date > data.end_date:
                raise BadRequestException("Start date must be before or equal to end date")
            is_range = True
            current_date = data.start_date
            while current_date <= data.end_date:
                target_dates.append(current_date)
                current_date += timedelta(days=1)
        else:
            raise BadRequestException("Either shift_date or both start_date and end_date must be provided")

        created_shifts = []

        def get_shift_interval(s_date, s_time, e_time):
            start_dt = datetime.combine(s_date, s_time)
            if s_time < e_time:
                end_dt = datetime.combine(s_date, e_time)
            else:
                end_dt = datetime.combine(s_date + timedelta(days=1), e_time)
            return start_dt, end_dt

        # Validate all dates and check overlaps before inserting any records
        for target_date in target_dates:
            # 1. It Should Not be Possible to Create Nurse Shift For Past Dates.
            if target_date < date.today():
                raise BadRequestException(f"Cannot create shift for past date {target_date}")

            # 4. It Should not be Possible to Create Shift For Same Time Slot Twice.
            overlap_query = select(NurseShift).where(
                NurseShift.nurse_id == nurse_id,
                NurseShift.shift_date.in_([
                    target_date - timedelta(days=1),
                    target_date,
                    target_date + timedelta(days=1)
                ])
            )
            res = await self.db.execute(overlap_query)
            existing_shifts = res.scalars().all()
            
            new_start_dt, new_end_dt = get_shift_interval(target_date, data.start_time, data.end_time)
            
            for existing in existing_shifts:
                ex_start_dt, ex_end_dt = get_shift_interval(existing.shift_date, existing.start_time, existing.end_time)
                if new_start_dt < ex_end_dt and ex_start_dt < new_end_dt:
                    raise BadRequestException(
                        f"Shift overlaps with an existing shift on {target_date}"
                    )

        # Create all shifts
        for target_date in target_dates:
            # Calculate dynamic status automatically using datetime comparison
            now_dt = datetime.now()
            shift_start_dt, shift_end_dt = get_shift_interval(target_date, data.start_time, data.end_time)
            
            if now_dt < shift_start_dt:
                status = "Scheduled"
            elif shift_start_dt <= now_dt <= shift_end_dt:
                status = "Active"
            else:
                status = "Completed"

            shift = NurseShift(
                nurse_id=nurse_id,
                shift_name=data.shift_name,
                shift_date=target_date,
                start_time=data.start_time,
                end_time=data.end_time,
                status=status,
                notes=data.notes
            )
            shift = await self.shift_repo.create(shift)
            await self.audit_repo.create(
                "create", "nurses", user_id=user_id, resource_id=str(shift.id)
            )
            created_shifts.append(shift)

        if is_range:
            return [NurseShiftResponse.model_validate(s) for s in created_shifts]
        return NurseShiftResponse.model_validate(created_shifts[0])

    async def update_shift(
        self,
        nurse_id: int,
        shift_id: int,
        data: NurseShiftUpdate,
        user_id: int,
    ) -> NurseShiftResponse:
        from datetime import date, datetime
        from app.models.nurse_model import NurseShift
        from sqlalchemy import select

        await self._get_nurse_or_raise(nurse_id)
        shift = await self.shift_repo.get_by_id_for_nurse(shift_id, nurse_id)
        if not shift:
            raise NotFoundException("Shift not found")

        # Normalize start_time and end_time to be timezone-naive
        if data.start_time is not None and data.start_time.tzinfo is not None:
            data.start_time = data.start_time.replace(tzinfo=None)
        if data.end_time is not None and data.end_time.tzinfo is not None:
            data.end_time = data.end_time.replace(tzinfo=None)

        # Create copies of values to check updated constraints
        dump = data.model_dump(exclude_unset=True)
        new_start_time = dump.get("start_time", shift.start_time)
        new_end_time = dump.get("end_time", shift.end_time)
        new_shift_date = dump.get("shift_date", shift.shift_date)

        # Ensure any retrieved existing database/model times are also naive
        if hasattr(new_start_time, "tzinfo") and new_start_time.tzinfo is not None:
            new_start_time = new_start_time.replace(tzinfo=None)
        if hasattr(new_end_time, "tzinfo") and new_end_time.tzinfo is not None:
            new_end_time = new_end_time.replace(tzinfo=None)

        # 1. Past Date Validation
        if new_shift_date < date.today():
            raise BadRequestException("Cannot update shift to a past date")

        # 2. Time Ordering
        if new_start_time == new_end_time:
            raise BadRequestException("Start time cannot be equal to end time")

        # 4. Overlap Check
        overlap_query = select(NurseShift).where(
            NurseShift.nurse_id == nurse_id,
            NurseShift.shift_date.in_([
                new_shift_date - timedelta(days=1),
                new_shift_date,
                new_shift_date + timedelta(days=1)
            ]),
            NurseShift.id != shift_id
        )
        res = await self.db.execute(overlap_query)
        existing_shifts = res.scalars().all()

        def get_shift_interval(s_date, s_time, e_time):
            start_dt = datetime.combine(s_date, s_time)
            if s_time < e_time:
                end_dt = datetime.combine(s_date, e_time)
            else:
                end_dt = datetime.combine(s_date + timedelta(days=1), e_time)
            return start_dt, end_dt

        new_start_dt, new_end_dt = get_shift_interval(new_shift_date, new_start_time, new_end_time)

        for existing in existing_shifts:
            ex_start_dt, ex_end_dt = get_shift_interval(existing.shift_date, existing.start_time, existing.end_time)
            if new_start_dt < ex_end_dt and ex_start_dt < new_end_dt:
                raise BadRequestException("Shift overlaps with another existing shift")

        # Apply update
        for key, value in dump.items():
            setattr(shift, key, value)

        # 5. Status updates automatically
        now_dt = datetime.now()
        shift_start_dt, shift_end_dt = get_shift_interval(new_shift_date, new_start_time, new_end_time)

        if now_dt < shift_start_dt:
            shift.status = "Scheduled"
        elif shift_start_dt <= now_dt <= shift_end_dt:
            shift.status = "Active"
        else:
            shift.status = "Completed"

        shift = await self.shift_repo.update(shift)
        await self.audit_repo.create(
            "update", "nurses", user_id=user_id, resource_id=str(shift.id)
        )
        return NurseShiftResponse.model_validate(shift)

    async def create_attendance(
        self, nurse_id: int, data: NurseAttendanceCreate, user_id: int
    ) -> NurseAttendanceResponse:
        from datetime import datetime, date, time
        from app.models.nurse_model import NurseShift, NurseAttendance
        from sqlalchemy import select

        await self._get_nurse_or_raise(nurse_id)

        # 1. Use server-side current date and time
        today = date.today()
        current_time = datetime.now().time()

        # 3. Fetch NurseShift for today
        shift_query = select(NurseShift).where(
            NurseShift.nurse_id == nurse_id,
            NurseShift.shift_date == today
        )
        res = await self.db.execute(shift_query)
        shift = res.scalar_one_or_none()
        if not shift:
            raise BadRequestException("No shift scheduled for today")

        # Status Helper Logic
        def calculate_status(check_in: time | None, check_out: time | None) -> str:
            if check_out is not None:
                if check_out < shift.end_time:
                    return "Early Departure"
                elif check_out > shift.end_time:
                    return "Late Departure"
                else:
                    return "On Time"
            if check_in is not None:
                if check_in < shift.start_time:
                    return "Early Arrival"
                elif check_in > shift.start_time:
                    return "Late"
                else:
                    return "On Time"
            return "Absent"

        # Fetch today's attendance record
        existing = await self.attendance_repo.get_by_date(nurse_id, today)

        if data.action == "check_in":
            # Check-in flow
            if existing and existing.check_in_time is not None:
                raise BadRequestException("Check-in has already been marked for today")
            
            status = calculate_status(current_time, None)
            
            if existing:
                existing.check_in_time = current_time
                existing.status = status
                if data.notes is not None:
                    existing.notes = data.notes
                attendance = await self.attendance_repo.update(existing)
                action = "update"
            else:
                attendance = NurseAttendance(
                    nurse_id=nurse_id,
                    attendance_date=today,
                    check_in_time=current_time,
                    check_out_time=None,
                    status=status,
                    notes=data.notes
                )
                attendance = await self.attendance_repo.create(attendance)
                action = "create"
        elif data.action == "check_out":
            # Check-out flow
            if not existing or existing.check_in_time is None:
                raise BadRequestException("Check-in must be marked before check-out")
            if existing.check_out_time is not None:
                raise BadRequestException("Check-out has already been marked for today")

            # Validate check-out time is greater than check-in time
            if current_time <= existing.check_in_time:
                raise BadRequestException("Check-out time must be greater than check-in time")

            status = calculate_status(existing.check_in_time, current_time)
            existing.check_out_time = current_time
            existing.status = status
            if data.notes is not None:
                existing.notes = data.notes

            attendance = await self.attendance_repo.update(existing)
            action = "update"
        else:
            raise BadRequestException("Invalid action")

        await self.audit_repo.create(
            action, "nurses", user_id=user_id, resource_id=str(attendance.id)
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
        from datetime import date
        await self._get_nurse_or_raise(nurse_id)
        await self._validate_shift(nurse_id, data.shift_id)

        # 1. Handover Date should not be a past date
        if data.handover_date < date.today():
            raise BadRequestException("Handover date cannot be in the past")

        # 2. Handover Note should be possible to create only after check-out for that handover date
        attendance = await self.attendance_repo.get_by_date(nurse_id, data.handover_date)
        if not attendance or attendance.check_out_time is None:
            raise BadRequestException("Handover note can only be created after check-out")

        note = NurseHandoverNote(
            nurse_id=nurse_id,
            status="Active",
            **data.model_dump()
        )
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

        # Check vital thresholds and trigger critical alert if breached
        await self._check_vital_thresholds_and_notify(
            patient_id=patient_id,
            temperature=vital.temperature,
            blood_pressure=vital.blood_pressure,
            pulse_rate=vital.pulse_rate,
            oxygen_saturation=vital.oxygen_saturation,
        )

        return PatientVitalResponse.model_validate(vital)

    async def _check_vital_thresholds_and_notify(
        self,
        patient_id: int,
        temperature: float,
        blood_pressure: str,
        pulse_rate: int,
        oxygen_saturation: float,
    ) -> None:
        from app.core.constants import VITAL_THRESHOLDS, VitalType
        breaches = []
        
        # Parse BP systolic/diastolic
        systolic, diastolic = None, None
        if "/" in blood_pressure:
            parts = blood_pressure.split("/")
            if len(parts) == 2:
                try:
                    systolic = float(parts[0].strip())
                    diastolic = float(parts[1].strip())
                except ValueError:
                    pass

        # Check Temperature
        temp_rules = VITAL_THRESHOLDS.get(VitalType.TEMPERATURE)
        if temp_rules:
            val = temperature
            if val < temp_rules.get("min") or val > temp_rules.get("max"):
                breaches.append(f"Temperature abnormal: {val}°C (Normal: {temp_rules.get('min')}-{temp_rules.get('max')})")

        # Check Pulse Rate (HEART_RATE)
        pulse_rules = VITAL_THRESHOLDS.get(VitalType.HEART_RATE)
        if pulse_rules:
            val = pulse_rate
            if val < pulse_rules.get("min") or val > pulse_rules.get("max"):
                breaches.append(f"Pulse rate abnormal: {val} bpm (Normal: {pulse_rules.get('min')}-{pulse_rules.get('max')})")

        # Check SPO2
        spo2_rules = VITAL_THRESHOLDS.get(VitalType.SPO2)
        if spo2_rules:
            val = oxygen_saturation
            if val < spo2_rules.get("min"):
                breaches.append(f"Oxygen saturation abnormal: {val}% (Normal: >= {spo2_rules.get('min')})")

        # Check BP Systolic
        if systolic is not None:
            sys_rules = VITAL_THRESHOLDS.get(VitalType.SYSTOLIC_BP)
            if sys_rules and (systolic < sys_rules.get("min") or systolic > sys_rules.get("max")):
                breaches.append(f"Systolic BP abnormal: {systolic} mmHg (Normal: {sys_rules.get('min')}-{sys_rules.get('max')})")

        # Check BP Diastolic
        if diastolic is not None:
            dia_rules = VITAL_THRESHOLDS.get(VitalType.DIASTOLIC_BP)
            if dia_rules and (diastolic < dia_rules.get("min") or diastolic > dia_rules.get("max")):
                breaches.append(f"Diastolic BP abnormal: {diastolic} mmHg (Normal: {dia_rules.get('min')}-{dia_rules.get('max')})")

        if breaches:
            from app.services.notification_service import NotificationService
            await NotificationService(self.db).create_critical_patient_alert(
                patient_id=patient_id,
                message=f"Abnormal vitals recorded: {', '.join(breaches)}",
                reference_id=patient_id,
            )

    async def list_patient_vitals(
        self, patient_id: int, page: int = 1, size: int = 20
    ):
        patient = await self.assignment_repo.get_patient_by_id(patient_id)
        if not patient:
            raise NotFoundException("Patient not found")
        skip = (page - 1) * size
        items = await self.vital_repo.list_by_patient_id(patient_id, skip=skip, limit=size)
        total = await self.vital_repo.count_by_patient_id(patient_id)
        return build_paginated_result(
            [PatientVitalResponse.model_validate(item) for item in items],
            total,
            page,
            size,
        )

    async def get_patient_vital(self, vital_id: int) -> PatientVitalResponse:
        vital = await self.vital_repo.get_by_id(vital_id)
        if not vital:
            raise NotFoundException("Vital record not found")
        return PatientVitalResponse.model_validate(vital)

    async def update_patient_vital(
        self, vital_id: int, data: PatientVitalUpdate, user_id: int
    ) -> PatientVitalResponse:
        vital = await self.vital_repo.get_by_id(vital_id)
        if not vital:
            raise NotFoundException("Vital record not found")

        if data.temperature is not None:
            vital.temperature = data.temperature
        if data.pulse_rate is not None:
            vital.pulse_rate = data.pulse_rate
        if data.oxygen_level is not None:
            vital.oxygen_saturation = data.oxygen_level
        if data.notes is not None:
            vital.notes = data.notes

        if data.systolic_bp is not None or data.diastolic_bp is not None:
            current_systolic, current_diastolic = 120, 80
            if "/" in vital.blood_pressure:
                parts = vital.blood_pressure.split("/")
                if len(parts) == 2:
                    try:
                        current_systolic = int(float(parts[0].strip()))
                        current_diastolic = int(float(parts[1].strip()))
                    except ValueError:
                        pass
            
            new_systolic = data.systolic_bp if data.systolic_bp is not None else current_systolic
            new_diastolic = data.diastolic_bp if data.diastolic_bp is not None else current_diastolic
            vital.blood_pressure = f"{new_systolic}/{new_diastolic}"

        vital = await self.vital_repo.update(vital)
        await self.audit_repo.create(
            "update", "nurses", user_id=user_id, resource_id=str(vital.id)
        )

        await self._check_vital_thresholds_and_notify(
            patient_id=vital.patient_id,
            temperature=vital.temperature,
            blood_pressure=vital.blood_pressure,
            pulse_rate=vital.pulse_rate,
            oxygen_saturation=vital.oxygen_saturation,
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

        # Calculate overall daily counts for the nurse/patient
        total_tasks = await self.task_repo.count_by_nurse(
            nurse_id=nurse_id,
            due_date=due_date,
            patient_id=patient_id,
        )
        pending_tasks = await self.task_repo.count_by_nurse(
            nurse_id=nurse_id,
            due_date=due_date,
            patient_id=patient_id,
            status="Pending",
        )
        completed_tasks = await self.task_repo.count_by_nurse(
            nurse_id=nurse_id,
            due_date=due_date,
            patient_id=patient_id,
            status="Completed",
        )
        delayed_tasks = await self.task_repo.count_by_nurse(
            nurse_id=nurse_id,
            due_date=due_date,
            patient_id=patient_id,
            status="Delayed",
        )

        paginated = build_paginated_result(
            [NurseTaskResponse.model_validate(item) for item in items],
            total,
            page,
            size,
        )
        return {
            "items": paginated.items,
            "total": paginated.total,
            "page": paginated.page,
            "size": paginated.size,
            "pages": paginated.pages,
            "total_tasks": total_tasks,
            "pending_tasks": pending_tasks,
            "completed_tasks": completed_tasks,
            "delayed_tasks": delayed_tasks,
        }

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

        # Fetch nurse's user to assign nurse_name for serialization
        from app.models.user_model import User
        user = await self.db.get(User, user_id)
        log.nurse_name = user.full_name if user else None

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

    async def get_dashboard_overview(self, current_user: "User") -> "NurseDashboardResponse":
        from datetime import timezone, timedelta, time, datetime
        from sqlalchemy import select, func, or_, cast, Date
        from app.models.nurse_model import Nurse, NursePatientAssignment
        from app.models.notification_model import Notification
        from app.models.bed_allocation_model import Bed
        from app.models.patient_model import Patient
        from app.models.audit_log_model import AuditLog
        from app.schemas.nurse_schema import (
            UpcomingMedicationResponse,
            CriticalAlertResponse,
            RecentActivityResponse,
            NurseAssignedPatientStatusResponse,
            NurseShiftResponse,
        )

        # Get nurse matching logged-in user_id
        res = await self.db.execute(select(Nurse).where(Nurse.user_id == current_user.id))
        nurse = res.scalar_one_or_none()

        # Fetch active & occupied beds (non-nurse specific)
        occupied_beds = (await self.db.scalar(
            select(func.count(Bed.id)).where(func.lower(Bed.status) == "occupied")
        )) or 0
        available_beds = (await self.db.scalar(
            select(func.count(Bed.id)).where(func.lower(Bed.status) == "available")
        )) or 0

        if not nurse:
            return NurseDashboardResponse(
                assigned_patients=0,
                today_patients=0,
                pending_medications=0,
                critical_patients=0,
                doctor_instructions=0,
                occupied_beds=occupied_beds,
                available_beds=available_beds,
                upcoming_medications=[],
                critical_alerts=[],
                recent_activities=[],
                assigned_patients_list=[],
                shift_details=[],
                alerts=[]
            )

        # Timezones
        ist_tz = timezone(timedelta(hours=5, minutes=30))
        now_ist = datetime.now(ist_tz)
        today_start = datetime.combine(now_ist.date(), time.min)
        tomorrow_start = today_start + timedelta(days=1)

        # 1. Assigned Patients (Active status)
        assigned_patients = await self.assignment_repo.list_patients_by_nurse(nurse.id, status="Active")
        assigned_pids = {p.id for p in assigned_patients}
        assigned_patients_count = len(assigned_pids)

        # 2. Today's Patients (admitted today or assigned today)
        today_patients_count = (await self.db.scalar(
            select(func.count(NursePatientAssignment.id)).where(
                NursePatientAssignment.nurse_id == nurse.id,
                NursePatientAssignment.status == "Active",
                NursePatientAssignment.created_at >= today_start,
                NursePatientAssignment.created_at < tomorrow_start
            )
        )) or 0
        if today_patients_count == 0:
            today_patients_count = assigned_patients_count

        # 3. Pending & Upcoming Medications
        schedules = await self.list_medication_schedules()
        pending_meds_count = 0
        upcoming_medications_list = []
        for s in schedules:
            try:
                pid = int(s["patient_id"].replace("P-100", ""))
            except ValueError:
                continue
            if pid in assigned_pids:
                if s["status"] == "Due":
                    pending_meds_count += 1
                    upcoming_medications_list.append(
                        UpcomingMedicationResponse(
                            patient_id=pid,
                            patient_name=s["patientName"],
                            medicine_name=s["medicine_name"],
                            scheduled_time=s["scheduledTime"]
                        )
                    )
        upcoming_medications = upcoming_medications_list[:10]

        # 4. Critical Patients (Unique patients with active critical alert notifications)
        critical_patients_count = (await self.db.scalar(
            select(func.count(func.distinct(Notification.reference_id)))
            .join(NursePatientAssignment, NursePatientAssignment.patient_id == Notification.reference_id)
            .where(
                NursePatientAssignment.nurse_id == nurse.id,
                NursePatientAssignment.status == "Active",
                Notification.user_id == current_user.id,
                Notification.notification_type == "CRITICAL_ALERT",
                Notification.is_read.is_(False),
                Notification.is_deleted.is_(False)
            )
        )) or 0

        # 5. Doctor Instructions (Active notifications)
        doctor_instructions_count = (await self.db.scalar(
            select(func.count(Notification.id))
            .where(
                Notification.user_id == current_user.id,
                Notification.notification_type == "DOCTOR_INSTRUCTION",
                Notification.is_read.is_(False),
                Notification.is_deleted.is_(False)
            )
        )) or 0

        # 6. Critical Alerts List (Latest 10)
        critical_alerts_query = (
            select(Notification, Patient)
            .join(Patient, Patient.id == Notification.reference_id)
            .where(
                Notification.user_id == current_user.id,
                Notification.notification_type == "CRITICAL_ALERT",
                Notification.is_deleted.is_(False)
            )
            .order_by(Notification.created_at.desc())
            .limit(10)
        )
        critical_alerts_res = await self.db.execute(critical_alerts_query)
        critical_alerts = [
            CriticalAlertResponse(
                patient_id=pat.id,
                patient_name=f"{pat.first_name} {pat.last_name}",
                alert_type=notif.title or "Critical Patient Alert",
                priority=notif.priority or "HIGH",
                created_at=notif.created_at
            )
            for notif, pat in critical_alerts_res.all()
        ]

        # 7. Recent Activities (Latest 10)
        activities_query = (
            select(AuditLog)
            .where(AuditLog.user_id == current_user.id)
            .order_by(AuditLog.created_at.desc())
            .limit(10)
        )
        activities_res = await self.db.execute(activities_query)
        recent_activities = [
            RecentActivityResponse(
                id=log.id,
                action=log.action,
                resource=log.resource,
                details=log.details,
                created_at=log.created_at
            )
            for log in activities_res.scalars().all()
        ]

        # 8. Assigned Patients List (Detailed)
        assigned_rows = await self.assignment_repo.list_patient_statuses_by_nurse(
            nurse_id=nurse.id,
            skip=0,
            limit=100
        )
        assigned_patients_list = [
            NurseAssignedPatientStatusResponse(
                patient_id=pat.id,
                patient_code=pat.patient_code,
                first_name=pat.first_name,
                last_name=pat.last_name,
                patient_status=assignment.patient_status,
                assignment_status=assignment.status,
                notes=assignment.notes,
                updated_at=assignment.updated_at,
            )
            for pat, assignment in assigned_rows
        ]

        # 9. Shift Details List (Latest 10)
        shift_items = await self.shift_repo.list_by_nurse(
            nurse_id=nurse.id,
            skip=0,
            limit=10,
            sort_by="shift_date",
            sort_order="desc"
        )
        shift_details = [
            NurseShiftResponse.model_validate(item)
            for item in shift_items
        ]

        # 10. Alerts (alias of critical_alerts)
        alerts = critical_alerts

        return NurseDashboardResponse(
            assigned_patients=assigned_patients_count,
            today_patients=today_patients_count,
            pending_medications=pending_meds_count,
            critical_patients=critical_patients_count,
            doctor_instructions=doctor_instructions_count,
            occupied_beds=occupied_beds,
            available_beds=available_beds,
            upcoming_medications=upcoming_medications,
            critical_alerts=critical_alerts,
            recent_activities=recent_activities,
            assigned_patients_list=assigned_patients_list,
            shift_details=shift_details,
            alerts=alerts
        )

    async def assign_patient(
        self, nurse_id: int, data: NursePatientAssignmentCreate, user_id: int
    ) -> NursePatientAssignmentResponse:
        from app.models.patient_model import Patient
        from app.models.nurse_model import NursePatientAssignment

        await self._get_nurse_or_raise(nurse_id)
        
        patient = await self.db.get(Patient, data.patient_id)
        if not patient or patient.is_deleted:
            raise NotFoundException("Patient not found")

        # Check if patient currently has an active bed allocation
        from sqlalchemy import select
        from app.models.bed_allocation_model import Bed

        bed_stmt = select(Bed).where(Bed.patient_id == data.patient_id, Bed.status == "Occupied")
        bed_result = await self.db.execute(bed_stmt)
        active_bed = bed_result.scalar_one_or_none()
        if not active_bed:
            raise BadRequestException("Patient does not have an active bed allocation")

        # Check if already assigned actively
        existing = await self.assignment_repo.get_active_assignment(nurse_id, data.patient_id)
        if existing:
            raise BadRequestException("Patient is already actively assigned to this nurse")

        assignment = NursePatientAssignment(
            nurse_id=nurse_id,
            patient_id=data.patient_id,
            patient_status=data.patient_status,
            notes=data.notes,
            status="Active"
        )
        assignment = await self.assignment_repo.create(assignment)
        await self.audit_repo.create(
            "create", "nurses", user_id=user_id, resource_id=str(assignment.id)
        )
        return NursePatientAssignmentResponse.model_validate(assignment)

    async def create_task(
        self, nurse_id: int, data: NurseTaskCreate, user_id: int
    ) -> NurseTaskResponse:
        from app.models.patient_model import Patient
        from app.models.nurse_model import NurseTask

        await self._get_nurse_or_raise(nurse_id)
        
        patient = await self.db.get(Patient, data.patient_id)
        if not patient or patient.is_deleted:
            raise NotFoundException("Patient not found")

        task = NurseTask(
            nurse_id=nurse_id,
            patient_id=data.patient_id,
            title=data.title,
            description=data.description,
            due_date=data.due_date,
            priority=data.priority,
            status="Pending"
        )
        task = await self.task_repo.create(task)
        await self.audit_repo.create(
            "create", "nurses", user_id=user_id, resource_id=str(task.id)
        )
        return NurseTaskResponse.model_validate(task)

    async def delete_task(
        self, nurse_id: int, task_id: int, user_id: int
    ) -> None:
        await self._get_nurse_or_raise(nurse_id)
        task = await self.task_repo.get_by_id(task_id, nurse_id)
        if not task:
            raise NotFoundException("Nurse task not found")
        await self.db.delete(task)
        await self.db.commit()
        await self.audit_repo.create(
            "delete", "nurses", user_id=user_id, resource_id=str(task_id)
        )

