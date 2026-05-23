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
        result = await self.db.execute(
            select(User)
            .options(joinedload(User.role))
            .where(User.phone == phone)
        )
        return result.scalar_one_or_none()

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
