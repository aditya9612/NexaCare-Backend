from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.constants import UserRole
from app.models.user_model import User
from app.models.role_model import Role

class AdminManagementRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _base_query(self):
        return select(User).join(User.role).options(
            joinedload(User.role),
            joinedload(User.hospital)
        ).where(Role.name == UserRole.HOSPITAL_ADMIN)

    async def get_by_id(self, admin_id: int) -> User | None:
        result = await self.db.execute(
            self._base_query().where(User.id == admin_id)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        # Check across ALL users to prevent duplicate email globally
        result = await self.db.execute(
            select(User).where(func.lower(User.email) == email.strip().lower())
        )
        return result.scalar_one_or_none()

    async def get_by_phone(self, phone: str, exclude_user_id: int | None = None) -> User | None:
        """Check if a phone number is already taken by another user (globally)."""
        query = select(User).where(User.phone == phone.strip())
        if exclude_user_id is not None:
            query = query.where(User.id != exclude_user_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_admins(
        self,
        skip: int = 0,
        limit: int = 20,
        search: str | None = None,
        hospital_id: int | None = None,
        is_active: bool | None = None
    ) -> list[User]:
        query = self._base_query()

        if hospital_id is not None:
            query = query.where(User.hospital_id == hospital_id)
        
        if is_active is not None:
            query = query.where(User.is_active == is_active)

        if search:
            pattern = f"%{search.strip().lower()}%"
            query = query.where(
                or_(
                    func.lower(User.full_name).like(pattern),
                    func.lower(User.email).like(pattern),
                    func.lower(User.phone).like(pattern),
                    func.lower(User.user_code).like(pattern)
                )
            )

        query = query.order_by(User.created_at.desc())
        result = await self.db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().unique().all())

    async def count_admins(
        self,
        search: str | None = None,
        hospital_id: int | None = None,
        is_active: bool | None = None
    ) -> int:
        query = select(func.count(User.id)).join(User.role).where(Role.name == UserRole.HOSPITAL_ADMIN)

        if hospital_id is not None:
            query = query.where(User.hospital_id == hospital_id)
        
        if is_active is not None:
            query = query.where(User.is_active == is_active)

        if search:
            pattern = f"%{search.strip().lower()}%"
            query = query.where(
                or_(
                    func.lower(User.full_name).like(pattern),
                    func.lower(User.email).like(pattern),
                    func.lower(User.phone).like(pattern),
                    func.lower(User.user_code).like(pattern)
                )
            )

        return await self.db.scalar(query) or 0

    async def create(self, user: User) -> User:
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def update(self, user: User) -> User:
        await self.db.flush()
        await self.db.refresh(user)
        return user
