from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.refresh_token_model import RefreshToken
from app.models.user_model import User


class AuthRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_email(self, email: str) -> User | None:
        normalized = email.strip().lower()
        result = await self.db.execute(
            select(User)
            .options(joinedload(User.role))
            .where(func.lower(User.email) == normalized)
        )
        return result.scalar_one_or_none()

    async def get_by_phone(self, phone: str) -> User | None:
        from sqlalchemy import or_
        from app.core.exceptions import ConflictException
        from app.utils.phone_utils import indian_mobile_last10

        phone_clean = phone.strip()
        last10 = indian_mobile_last10(phone_clean)

        conditions = [User.phone == phone_clean]
        if last10 and len(last10) == 10:
            candidates = {
                last10,
                f"+91{last10}",
                f"91{last10}",
                f"0{last10}",
            }
            for candidate in candidates:
                conditions.append(User.phone == candidate)
            conditions.append(User.phone.like(f"%{last10}"))

        result = await self.db.execute(
            select(User)
            .options(joinedload(User.role))
            .where(or_(*conditions))
        )
        users = list(result.scalars().all())
        if len(users) > 1:
            raise ConflictException(
                "Multiple accounts found associated with this mobile number. Please log in using your registered email."
            )
        return users[0] if users else None

    async def get_by_id(self, user_id: int) -> User | None:
        result = await self.db.execute(
            select(User).options(joinedload(User.role)).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_user_code(self, user_code: str) -> User | None:
        result = await self.db.execute(select(User).where(User.user_code == user_code))
        return result.scalar_one_or_none()

    async def create(self, user: User) -> User:
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def update(self, user: User) -> User:
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def save_refresh_token(self, token: RefreshToken) -> RefreshToken:
        self.db.add(token)
        await self.db.flush()
        return token

    async def get_refresh_token(self, token: str) -> RefreshToken | None:
        result = await self.db.execute(
            select(RefreshToken).where(RefreshToken.token == token, RefreshToken.is_revoked.is_(False))
        )
        return result.scalar_one_or_none()

    async def revoke_refresh_token(self, token: RefreshToken) -> None:
        token.is_revoked = True
        await self.db.flush()

    async def revoke_all_user_tokens(self, user_id: int) -> None:
        result = await self.db.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id,
                RefreshToken.is_revoked.is_(False),
            )
        )
        for token in result.scalars().all():
            token.is_revoked = True
        await self.db.flush()
