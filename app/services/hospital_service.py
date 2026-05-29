from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import BadRequestException, NotFoundException
from app.models.hospital_model import Hospital
from app.models.user_model import User
from app.core.constants import UserRole
from app.repositories.hospital_repository import HospitalRepository
from app.repositories.audit_repository import AuditRepository
from app.repositories.rbac_repository import RBACRepository
from app.schemas.hospital_schema import (
    HospitalCreate,
    HospitalUpdate,
    HospitalResponse,
    HospitalStatsResponse,
)
from app.schemas.user_schema import UserCreate, UserUpdate, UserResponse
from app.core.security import get_password_hash
from app.utils.helpers import generate_user_code

class HospitalService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = HospitalRepository(db)
        self.rbac_repo = RBACRepository(db)
        self.audit_repo = AuditRepository(db)

    async def create_hospital(self, data: HospitalCreate, user_id: int) -> HospitalResponse:
        existing = await self.repo.get_by_email(data.email)
        if existing:
            raise BadRequestException("Hospital with this email already exists")
        hospital = Hospital(**data.model_dump())
        hospital = await self.repo.create(hospital)
        await self.audit_repo.create("create", "hospitals", user_id=user_id, resource_id=str(hospital.id))
        return HospitalResponse.model_validate(hospital)

    async def list_hospitals(self) -> list[HospitalResponse]:
        hospitals = await self.repo.list_hospitals()
        return [HospitalResponse.model_validate(h) for h in hospitals]

    async def get_hospital(self, id: int) -> HospitalResponse:
        hospital = await self.repo.get_by_id(id)
        if not hospital:
            raise NotFoundException("Hospital not found")
        return HospitalResponse.model_validate(hospital)

    async def update_hospital(self, id: int, data: HospitalUpdate, user_id: int) -> HospitalResponse:
        hospital = await self.repo.get_by_id(id)
        if not hospital:
            raise NotFoundException("Hospital not found")
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(hospital, key, value)
        hospital = await self.repo.update(hospital)
        await self.audit_repo.create("update", "hospitals", user_id=user_id, resource_id=str(hospital.id))
        return HospitalResponse.model_validate(hospital)

    async def delete_hospital(self, id: int, user_id: int) -> None:
        hospital = await self.repo.get_by_id(id)
        if not hospital:
            raise NotFoundException("Hospital not found")
        await self.repo.delete(hospital)
        await self.audit_repo.create("delete", "hospitals", user_id=user_id, resource_id=str(id))

    async def get_hospital_stats(self, id: int) -> HospitalStatsResponse:
        hospital = await self.repo.get_by_id(id)
        if not hospital:
            raise NotFoundException("Hospital not found")
        stats = await self.repo.get_stats(id)
        return HospitalStatsResponse.model_validate(stats)

    # Hospital Admin Management
    async def create_hospital_admin(self, data: UserCreate, user_id: int) -> UserResponse:
        # Resolve role
        role = await self.rbac_repo.get_role_by_name(UserRole.HOSPITAL_ADMIN)
        if not role:
            raise BadRequestException("Hospital Admin role not seeded")

        # Validate hospital
        if not data.hospital_id:
            raise BadRequestException("hospital_id is required for hospital admin")
        hospital = await self.repo.get_by_id(data.hospital_id)
        if not hospital:
            raise NotFoundException("Hospital not found")

        # Create user
        user = User(
            user_code=generate_user_code(),
            email=data.email.strip().lower(),
            hashed_password=get_password_hash(data.password),
            full_name=data.full_name,
            phone=data.phone,
            role_id=role.id,
            hospital_id=data.hospital_id,
            gender=data.gender,
            date_of_birth=data.date_of_birth,
            is_active=True,
            is_verified=True,
        )
        user = await self.repo.create_admin_user(user)
        await self.audit_repo.create("create", "users", user_id=user_id, resource_id=str(user.id))
        return UserResponse(
            id=user.id,
            user_code=user.user_code,
            email=user.email,
            full_name=user.full_name,
            phone=user.phone,
            role_id=user.role_id,
            role_name=UserRole.HOSPITAL_ADMIN,
            hospital_id=user.hospital_id,
            profile_image=user.profile_image,
            gender=user.gender,
            date_of_birth=user.date_of_birth,
            is_active=user.is_active,
            is_verified=user.is_verified,
            last_login=user.last_login,
            created_at=user.created_at,
            updated_at=user.updated_at
        )

    async def list_hospital_admins(self) -> list[UserResponse]:
        admins = await self.repo.list_admins()
        return [
            UserResponse(
                id=u.id,
                user_code=u.user_code,
                email=u.email,
                full_name=u.full_name,
                phone=u.phone,
                role_id=u.role_id,
                role_name=UserRole.HOSPITAL_ADMIN,
                hospital_id=u.hospital_id,
                profile_image=u.profile_image,
                gender=u.gender,
                date_of_birth=u.date_of_birth,
                is_active=u.is_active,
                is_verified=u.is_verified,
                last_login=u.last_login,
                created_at=u.created_at,
                updated_at=u.updated_at
            )
            for u in admins
        ]

    async def update_hospital_admin(self, admin_id: int, data: UserUpdate, user_id: int) -> UserResponse:
        admin = await self.repo.get_admin_by_id(admin_id)
        if not admin:
            raise NotFoundException("Hospital Admin user not found")
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(admin, key, value)
        await self.db.flush()
        await self.db.refresh(admin)
        await self.audit_repo.create("update", "users", user_id=user_id, resource_id=str(admin.id))
        return UserResponse(
            id=admin.id,
            user_code=admin.user_code,
            email=admin.email,
            full_name=admin.full_name,
            phone=admin.phone,
            role_id=admin.role_id,
            role_name=UserRole.HOSPITAL_ADMIN,
            hospital_id=admin.hospital_id,
            profile_image=admin.profile_image,
            gender=admin.gender,
            date_of_birth=admin.date_of_birth,
            is_active=admin.is_active,
            is_verified=admin.is_verified,
            last_login=admin.last_login,
            created_at=admin.created_at,
            updated_at=admin.updated_at
        )

    async def delete_hospital_admin(self, admin_id: int, user_id: int) -> None:
        admin = await self.repo.get_admin_by_id(admin_id)
        if not admin:
            raise NotFoundException("Hospital Admin user not found")
        admin.is_active = False
        await self.db.flush()
        await self.audit_repo.create("deactivate", "users", user_id=user_id, resource_id=str(admin_id))
