from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.super_admin_repository import SuperAdminRepository
from app.schemas.super_admin_schema import SuperAdminDashboardResponse, SuperAdminAnalyticsResponse, HospitalGrowthItem, RevenueTrendItem

class SuperAdminService:
    def __init__(self, db: AsyncSession):
        self.repo = SuperAdminRepository(db)

    async def get_dashboard_stats(self) -> SuperAdminDashboardResponse:
        stats = await self.repo.get_dashboard_stats()
        return SuperAdminDashboardResponse.model_validate(stats)

    async def get_analytics(self) -> SuperAdminAnalyticsResponse:
        growth = await self.repo.get_hospital_growth()
        revenue = await self.repo.get_revenue_trends()

        # Format hospital growth items: month is format "YYYY-MM"
        growth_items = []
        for g in growth:
            month_str = f"{g['year']:04d}-{g['month']:02d}"
            growth_items.append(HospitalGrowthItem(month=month_str, count=g["count"]))

        # Format revenue trend items: month is format "YYYY-MM"
        revenue_items = []
        for r in revenue:
            month_str = f"{r['year']:04d}-{r['month']:02d}"
            revenue_items.append(RevenueTrendItem(month=month_str, amount=r["amount"]))

        return SuperAdminAnalyticsResponse(
            hospital_growth=growth_items,
            revenue_trends=revenue_items
        )
