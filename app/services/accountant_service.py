from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.accountant_repository import AccountantRepository
from app.schemas.accountant_schema import AccountantDashboardResponse


class AccountantService:
    def __init__(self, db: AsyncSession):
        self.repo = AccountantRepository(db)

    async def get_dashboard(self) -> AccountantDashboardResponse:
        data = await self.repo.get_dashboard_stats()
        return AccountantDashboardResponse(**data)