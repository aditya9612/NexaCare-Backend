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
        page: int = 1,
        size: int = 20,
        department_id: int | None = None,
        availability_status: str | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ):
        skip = (page - 1) * size
        items = await self.repo.list_all(
            skip=skip, limit=size, department_id=department_id,
            availability_status=availability_status, sort_by=sort_by, sort_order=sort_order,
        )
        total = await self.repo.count_all(department_id=department_id, availability_status=availability_status)
        return build_paginated_result(
            [DoctorResponse.model_validate(d) for d in items], total, page, size
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
        except IntegrityError as exc:
            self._raise_doctor_integrity_error(exc)
        await self.audit_repo.create("update", "doctors", user_id=user_id, resource_id=str(doctor.id))
        return DoctorResponse.model_validate(doctor)


    async def delete(self, doctor_id: int, user_id: int) -> None:
        doctor = await self.repo.get_by_id(doctor_id)
        if not doctor:
            raise NotFoundException("Doctor not found")
        await self.repo.soft_delete(doctor)
        await self.audit_repo.create("delete", "doctors", user_id=user_id, resource_id=str(doctor.id))

    async def search(self, q: str, page: int = 1, size: int = 20):
        skip = (page - 1) * size
        items = await self.repo.search(q, skip=skip, limit=size)
        total = await self.repo.count_search(q)
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
        schedule = DoctorSchedule(doctor_id=doctor_id, **data.model_dump())
        schedule = await self.repo.add_schedule(schedule)
        await self.audit_repo.create("create", "doctor_schedules", user_id=user_id, resource_id=str(schedule.id))
        return DoctorScheduleResponse.model_validate(schedule)
