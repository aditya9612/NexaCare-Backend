from typing import Optional

from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import UserRole
from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.core.security import get_password_hash
from app.models.doctor_model import Doctor, DoctorSchedule
from app.models.user_model import User
from app.repositories.audit_repository import AuditRepository
from app.repositories.auth_repository import AuthRepository
from app.repositories.department_repository import DepartmentRepository
from app.repositories.doctor_repository import DoctorRepository
from app.repositories.rbac_repository import RBACRepository
from app.schemas.appointment_schema import AppointmentResponse
from app.schemas.doctor_schema import (
    DoctorCreate,
    DoctorOnboardCreate,
    DoctorOnboardResponse,
    DoctorOnboardUserSummary,
    DoctorResponse,
    DoctorScheduleCreate,
    DoctorScheduleResponse,
    DoctorScheduleUpdate,
    DoctorUpdate,
)
from app.utils.file_upload import save_upload
from app.utils.helpers import generate_doctor_code, generate_user_code
from app.utils.pagination import build_paginated_result


async def save_doctor_image(file: UploadFile) -> str:
    import os
    import uuid
    from pathlib import Path
    import aiofiles
    from fastapi import HTTPException
    from app.core.config import settings

    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    if ext not in {"jpg", "jpeg", "png", "webp"}:
        raise HTTPException(
            status_code=400,
            detail="File type not allowed. Only jpg, jpeg, png, and webp are allowed."
        )

    upload_dir = Path("app/uploads/doctors")
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    unique_filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = upload_dir / unique_filename

    content = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=400, detail="File too large")

    async with aiofiles.open(filepath, "wb") as f:
        await f.write(content)

    return str(filepath).replace(os.sep, "/")


class DoctorService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = DoctorRepository(db)
        self.auth_repo = AuthRepository(db)
        self.rbac_repo = RBACRepository(db)
        self.audit_repo = AuditRepository(db)
        self.dept_repo = DepartmentRepository(db)

    def _raise_doctor_integrity_error(self, exc: IntegrityError) -> None:
        err_msg = str(exc.orig).lower()
        if "license_number" in err_msg:
            raise ConflictException("A doctor with this license number already exists") from exc
        if "duplicate" in err_msg and "user_id" in err_msg:
            raise ConflictException("This user already has a doctor profile") from exc
        if "doctors_ibfk" in err_msg or "foreign key" in err_msg:
            raise ConflictException("The specified user_id does not exist") from exc
        raise ConflictException("Doctor could not be saved due to a database conflict") from exc

    async def _validate_department(self, department_id: int | None) -> None:
        """Raise 404 if department_id is given but doesn't exist."""
        if department_id is not None:
            dept = await self.dept_repo.get_by_id(department_id)
            if not dept:
                raise NotFoundException(f"Department with ID {department_id} not found")

    async def list_doctors(
        self,
        current_user: User,
        page: int = 1,
        size: int = 20,
        department_id: int | None = None,
        availability_status: str | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ):
        from app.schemas.doctor_schema import DoctorPaginatedResult
        import math

        counts = await self.repo.get_doctor_counts()

        if current_user.role and current_user.role.name == UserRole.LAB_TECHNICIAN:
            from app.models.staff_model import Staff
            from sqlalchemy import select
            result = await self.db.execute(
                select(Staff).where(Staff.email == current_user.email, Staff.is_deleted == False)
            )
            staff = result.scalar_one_or_none()
            if not staff:
                raise NotFoundException("Lab technician profile not found")
            if staff.department_id is None:
                raise BadRequestException("Lab technician department is not assigned")
            department_id = staff.department_id

        if current_user.role and current_user.role.name == UserRole.DOCTOR:
            doctor = await self.repo.get_by_user_id(current_user.id)
            if not doctor:
                raise NotFoundException("Doctor profile not found")
            items = [DoctorResponse.model_validate(doctor)] if page == 1 else []
            return DoctorPaginatedResult(
                items=items,
                total=1,
                page=page,
                size=size,
                pages=1 if page == 1 else 0,
                total_doctors=counts["total_doctors"],
                available_doctors=counts["available_doctors"],
                on_leave_doctors=counts["on_leave_doctors"]
            )

        skip = (page - 1) * size
        items = await self.repo.list_all(
            skip=skip, limit=size, department_id=department_id,
            availability_status=availability_status, sort_by=sort_by, sort_order=sort_order,
        )
        total = await self.repo.count_all(department_id=department_id, availability_status=availability_status)
        pages = math.ceil(total / size) if size else 0
        return DoctorPaginatedResult(
            items=[DoctorResponse.model_validate(d) for d in items],
            total=total,
            page=page,
            size=size,
            pages=pages,
            total_doctors=counts["total_doctors"],
            available_doctors=counts["available_doctors"],
            on_leave_doctors=counts["on_leave_doctors"]
        )

    async def get_by_id(self, doctor_id: int) -> DoctorResponse:
        doctor = await self.repo.get_by_id(doctor_id)
        if not doctor:
            raise NotFoundException("Doctor not found")
        return DoctorResponse.model_validate(doctor)

    async def create(
        self,
        data: DoctorCreate,
        user_id: int,
        image_file: Optional[UploadFile] = None,
    ) -> DoctorResponse:
        if data.email:
            existing_email = await self.repo.get_by_email(data.email)
            if existing_email:
                raise ConflictException("Email already exists")

        existing_license = await self.repo.get_by_license(data.license_number)
        if existing_license:
            raise ConflictException("A doctor with this license number already exists")

        if data.user_id:
            user = await self.auth_repo.get_by_id(data.user_id)
            if not user:
                raise NotFoundException(f"User with ID {data.user_id} not found")

        await self._validate_department(data.department_id)

        # Save uploaded image file if provided, otherwise use URL from data
        profile_image_path: Optional[str] = data.profile_image
        if image_file and image_file.filename:
            profile_image_path = await save_doctor_image(image_file)

        dump = data.model_dump()
        dump["profile_image"] = profile_image_path

        doctor = Doctor(doctor_code=generate_doctor_code(), **dump)
        try:
            doctor = await self.repo.create(doctor)
        except IntegrityError as exc:
            self._raise_doctor_integrity_error(exc)
        await self.audit_repo.create("create", "doctors", user_id=user_id, resource_id=str(doctor.id))
        return DoctorResponse.model_validate(doctor)

    async def onboard(
        self,
        data: DoctorOnboardCreate,
        actor: User,
        image_file: Optional[UploadFile] = None,
    ) -> DoctorOnboardResponse:
        email_norm = data.email.strip().lower()
        if await self.auth_repo.get_by_email(email_norm):
            raise ConflictException("Email already registered")
        if data.phone and await self.auth_repo.get_by_phone(data.phone):
            raise ConflictException("Phone number already registered")
        if await self.repo.get_by_email(email_norm):
            raise ConflictException("A doctor with this email already exists")
        existing_license = await self.repo.get_by_license(data.license_number)
        if existing_license:
            raise ConflictException("A doctor with this license number already exists")
        await self._validate_department(data.department_id)

        role = await self.rbac_repo.get_role_by_name(UserRole.DOCTOR)
        if not role:
            raise BadRequestException("Doctor role not seeded")

        profile_image_path: Optional[str] = data.profile_image
        if image_file and image_file.filename:
            profile_image_path = await save_upload(image_file, subfolder="doctors")

        full_name = f"{data.first_name} {data.last_name}".strip()
        hospital_id = actor.hospital_id

        user = User(
            user_code=generate_user_code(),
            email=email_norm,
            hashed_password=get_password_hash(data.password),
            full_name=full_name,
            phone=data.phone,
            role_id=role.id,
            hospital_id=hospital_id,
            profile_image=profile_image_path,
            gender=data.gender.value if data.gender else None,
            date_of_birth=data.date_of_birth,
            is_active=True,
            is_verified=True,
        )
        try:
            user = await self.auth_repo.create(user)
            doctor = Doctor(
                doctor_code=generate_doctor_code(),
                user_id=user.id,
                first_name=data.first_name,
                last_name=data.last_name,
                specialization=data.specialization,
                qualification=data.qualification,
                experience=data.experience,
                phone=data.phone,
                email=email_norm,
                department_id=data.department_id,
                consultation_fee=data.consultation_fee,
                license_number=data.license_number,
                availability_status=data.availability_status,
                profile_image=profile_image_path,
                bio=data.bio,
            )
            doctor = await self.repo.create(doctor)
        except IntegrityError as exc:
            self._raise_doctor_integrity_error(exc)

        user = await self.auth_repo.get_by_id(user.id)
        await self.audit_repo.create("create", "users", user_id=actor.id, resource_id=str(user.id))
        await self.audit_repo.create("create", "doctors", user_id=actor.id, resource_id=str(doctor.id))

        return DoctorOnboardResponse(
            doctor=DoctorResponse.model_validate(doctor),
            user=DoctorOnboardUserSummary(
                id=user.id,
                user_code=user.user_code,
                email=user.email,
                full_name=user.full_name,
                phone=user.phone,
                role_name=user.role.name if user.role else UserRole.DOCTOR,
                hospital_id=user.hospital_id,
                gender=user.gender,
                date_of_birth=user.date_of_birth,
                is_active=user.is_active,
            ),
        )

    async def update(
        self,
        doctor_id: int,
        data: DoctorUpdate,
        user_id: int,
        image_file: Optional[UploadFile] = None,
    ) -> DoctorResponse:
        doctor = await self.repo.get_by_id(doctor_id)
        if not doctor:
            raise NotFoundException("Doctor not found")

        if data.email and data.email != doctor.email:
            existing_email = await self.repo.get_by_email(data.email)
            if existing_email:
                raise ConflictException("Email already exists")
            existing_user_email = await self.auth_repo.get_by_email(data.email)
            if existing_user_email and existing_user_email.id != doctor.user_id:
                raise ConflictException("Email already registered to another user")

        if data.phone and data.phone != doctor.phone:
            existing_user_phone = await self.auth_repo.get_by_phone(data.phone)
            if existing_user_phone and existing_user_phone.id != doctor.user_id:
                raise ConflictException("Phone number already registered to another user")

        if data.license_number and data.license_number != doctor.license_number:
            existing_license = await self.repo.get_by_license(data.license_number)
            if existing_license:
                raise ConflictException("A doctor with this license number already exists")

        update_data = data.model_dump(exclude_unset=True)

        # If a new image file is uploaded, save it and override profile_image
        if image_file and image_file.filename:
            profile_image_path = await save_doctor_image(image_file)
            update_data["profile_image"] = profile_image_path
        else:
            # Remove profile_image from update if no file provided so existing value stays
            update_data.pop("profile_image", None)

        for key, value in update_data.items():
            setattr(doctor, key, value)

        try:
            doctor = await self.repo.update(doctor)
            
            # Synchronise the updated details with the associated User record
            if doctor.user_id:
                user = await self.auth_repo.get_by_id(doctor.user_id)
                if user:
                    user.full_name = f"{doctor.first_name} {doctor.last_name}".strip()
                    if data.email:
                        user.email = data.email.strip().lower()
                    if data.phone:
                        user.phone = data.phone
                    if "profile_image" in update_data:
                        user.profile_image = update_data["profile_image"]
                    await self.auth_repo.update(user)
                    
        except IntegrityError as exc:
            self._raise_doctor_integrity_error(exc)
        await self.audit_repo.create("update", "doctors", user_id=user_id, resource_id=str(doctor.id))
        return DoctorResponse.model_validate(doctor)


    async def delete(self, doctor_id: int, user_id: int) -> None:
        doctor = await self.repo.get_by_id(doctor_id)
        if not doctor:
            raise NotFoundException("Doctor not found")
        await self.repo.soft_delete(doctor)
        if doctor.user_id:
            from app.models.user_model import User
            user = await self.db.get(User, doctor.user_id)
            if user:
                user.is_active = False
        await self.audit_repo.create("delete", "doctors", user_id=user_id, resource_id=str(doctor.id))

    async def search(self, q: str, page: int = 1, size: int = 20):
        q_stripped = q.strip() if q else ""
        skip = (page - 1) * size
        items = await self.repo.search(q_stripped, skip=skip, limit=size)
        total = await self.repo.count_search(q_stripped)
        return build_paginated_result(
            [DoctorResponse.model_validate(d) for d in items], total, page, size
        )

    async def list_available(self) -> list[DoctorResponse]:
        doctors = await self.repo.list_available()
        return [DoctorResponse.model_validate(d) for d in doctors]

    async def get_appointments(self, doctor_id: int) -> list[AppointmentResponse]:
        await self.get_by_id(doctor_id)
        appointments = await self.repo.get_appointments(doctor_id)
        return [AppointmentResponse.model_validate(a) for a in appointments]

    async def get_schedule(self, doctor_id: int) -> list[DoctorScheduleResponse]:
        await self.get_by_id(doctor_id)
        schedules = await self.repo.get_schedule(doctor_id)
        return [DoctorScheduleResponse.model_validate(s) for s in schedules]

    async def add_schedule(self, doctor_id: int, data: DoctorScheduleCreate, user_id: int) -> DoctorScheduleResponse:
        await self.get_by_id(doctor_id)
        if data.start_time >= data.end_time:
            raise ConflictException("Start time must be before end time")

        # Check for overlaps
        existing_schedules = await self.repo.get_schedule(doctor_id)
        for sched in existing_schedules:
            if sched.day_of_week == data.day_of_week:
                if not (data.end_time <= sched.start_time or data.start_time >= sched.end_time):
                    raise ConflictException("Schedule overlaps with an existing slot")

        schedule = DoctorSchedule(doctor_id=doctor_id, **data.model_dump())
        schedule = await self.repo.add_schedule(schedule)
        await self.audit_repo.create("create", "doctor_schedules", user_id=user_id, resource_id=str(schedule.id))
        return DoctorScheduleResponse.model_validate(schedule)

    async def update_medical_record(
        self,
        record_id: int,
        report_title: str | None,
        report_type: str | None,
        diagnosis: str | None,
        notes: str | None,
        user_id: int,
    ):
        record = await self.repo.get_medical_record_by_id(record_id)
        if not record:
            raise NotFoundException("Medical record not found")

        if report_title is not None:
            record.report_title = report_title
        if report_type is not None:
            record.report_type = report_type
        if diagnosis is not None:
            record.diagnosis = diagnosis
        if notes is not None:
            record.notes = notes

        await self.repo.update_medical_record(record)
        await self.audit_repo.create("update", "doctor_medical_records", user_id=user_id, resource_id=str(record.id))
        
        from app.schemas.doctor_medical_record_schema import MedicalRecordResponse
        return MedicalRecordResponse.model_validate(record)

    async def delete_medical_record(self, record_id: int, user_id: int) -> None:
        record = await self.repo.get_medical_record_by_id(record_id)
        if not record:
            raise NotFoundException("Medical record not found")

        await self.repo.delete_medical_record(record)
        await self.audit_repo.create("delete", "doctor_medical_records", user_id=user_id, resource_id=str(record.id))

    async def delete_all_schedules(self, doctor_id: int, user_id: int) -> None:
        # Validate doctor exists
        await self.get_by_id(doctor_id)

        # Check if any schedules exist
        count = await self.repo.count_schedules(doctor_id)
        if count == 0:
            raise NotFoundException("No schedule slots found for this doctor")

        await self.repo.delete_all_schedules(doctor_id)
        await self.audit_repo.create("delete", "doctor_schedules", user_id=user_id, resource_id=str(doctor_id))

    async def delete_schedule_slot(self, doctor_id: int, slot_id: int, user_id: int) -> None:
        # Validate doctor exists
        await self.get_by_id(doctor_id)

        # Get the schedule slot
        slot = await self.repo.get_schedule_slot(doctor_id, slot_id)
        if not slot:
            raise NotFoundException("Schedule slot not found")

        await self.repo.delete_schedule_slot(slot)
        await self.audit_repo.create("delete", "doctor_schedules", user_id=user_id, resource_id=str(slot_id))

    async def update_schedule_slot(
        self, doctor_id: int, slot_id: int, data: DoctorScheduleUpdate, user_id: int
    ) -> DoctorScheduleResponse:
        await self.get_by_id(doctor_id)
        slot = await self.repo.get_schedule_slot(doctor_id, slot_id)
        if not slot:
            raise NotFoundException("Schedule slot not found")

        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            return DoctorScheduleResponse.model_validate(slot)

        new_day = update_data.get("day_of_week", slot.day_of_week)
        new_start = update_data.get("start_time", slot.start_time)
        new_end = update_data.get("end_time", slot.end_time)

        if new_start >= new_end:
            raise ConflictException("Start time must be before end time")

        existing_schedules = await self.repo.get_schedule(doctor_id)
        for sched in existing_schedules:
            if sched.id != slot_id and sched.day_of_week == new_day:
                if not (new_end <= sched.start_time or new_start >= sched.end_time):
                    raise ConflictException("Schedule overlaps with an existing slot")

        for key, val in update_data.items():
            setattr(slot, key, val)

        slot = await self.repo.update_schedule_slot(slot)
        await self.audit_repo.create("update", "doctor_schedules", user_id=user_id, resource_id=str(slot.id))
        return DoctorScheduleResponse.model_validate(slot)

    async def update_doctor_schedule(
        self, doctor_id: int, data_list: list[DoctorScheduleCreate], user_id: int
    ) -> list[DoctorScheduleResponse]:
        await self.get_by_id(doctor_id)
        await self.repo.delete_all_schedules(doctor_id)

        created_slots = []
        for slot_data in data_list:
            if slot_data.start_time >= slot_data.end_time:
                raise ConflictException(f"Start time must be before end time for day {slot_data.day_of_week + 1}")
            schedule = DoctorSchedule(doctor_id=doctor_id, **slot_data.model_dump())
            schedule = await self.repo.add_schedule(schedule)
            created_slots.append(schedule)

        await self.audit_repo.create("update", "doctor_schedules", user_id=user_id, resource_id=str(doctor_id))
        return [DoctorScheduleResponse.model_validate(s) for s in created_slots]

