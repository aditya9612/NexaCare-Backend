from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.super_admin_repository import SuperAdminRepository
from app.schemas.super_admin_schema import (
    SuperAdminDashboardResponse, 
    SuperAdminAnalyticsResponse, 
    HospitalGrowthItem, 
    RevenueTrendItem,
    DashboardOverviewResponse,
    PatientRegistrationItem,
    PatientAnalyticsResponse,
    UserDistribution,
    RecentAdminItem,
    UsersDashboardResponse
)

class SuperAdminService:
    def __init__(self, db: AsyncSession):
        self.repo = SuperAdminRepository(db)

    async def get_dashboard_stats(self) -> SuperAdminDashboardResponse:
        stats = await self.repo.get_dashboard_stats()
        return SuperAdminDashboardResponse.model_validate(stats)

    async def get_analytics(self) -> SuperAdminAnalyticsResponse:
        growth = await self.repo.get_hospital_growth()
        revenue = await self.repo.get_revenue_trends()

        growth_items = []
        for g in growth:
            month_str = f"{g['year']:04d}-{g['month']:02d}"
            growth_items.append(HospitalGrowthItem(month=month_str, count=g["count"]))

        revenue_items = []
        for r in revenue:
            month_str = f"{r['year']:04d}-{r['month']:02d}"
            revenue_items.append(RevenueTrendItem(month=month_str, amount=r["amount"]))

        return SuperAdminAnalyticsResponse(
            hospital_growth=growth_items,
            revenue_trends=revenue_items
        )

    # Extended Dashboard Service Methods

    async def get_dashboard_overview(self) -> DashboardOverviewResponse:
        now = datetime.utcnow()
        current_month_start = datetime(now.year, now.month, 1)
        
        if now.month == 1:
            prev_month_start = datetime(now.year - 1, 12, 1)
            prev_month_end = datetime(now.year - 1, 12, 31, 23, 59, 59, 999999)
        else:
            prev_month_start = datetime(now.year, now.month - 1, 1)
            prev_month_end = current_month_start - timedelta(microseconds=1)

        raw = await self.repo.get_dashboard_overview_data(current_month_start, prev_month_start, prev_month_end)

        def compute_growth(curr: int, prev: int) -> float:
            if prev == 0:
                return 100.0 if curr > 0 else 0.0
            return round(((curr - prev) / prev) * 100, 2)

        patient_growth = compute_growth(raw["current_patients"], raw["prev_patients"])
        appt_growth = compute_growth(raw["current_appointments"], raw["prev_appointments"])
        session_growth = compute_growth(raw["current_sessions"], raw["prev_sessions"])

        return DashboardOverviewResponse(
            total_patients=raw["total_patients"],
            patient_growth_percentage=patient_growth,
            total_appointments=raw["total_appointments"],
            appointment_growth_percentage=appt_growth,
            active_sessions=raw["active_sessions"],
            session_growth_percentage=session_growth,
            system_health="Healthy",
            uptime_percentage=99.9
        )

    async def get_patient_analytics_dashboard(self) -> PatientAnalyticsResponse:
        now = datetime.utcnow()
        current_month_start = datetime(now.year, now.month, 1)
        
        months_list = []
        for i in range(5, -1, -1):
            m = now.month - i
            y = now.year
            if m <= 0:
                m += 12
                y -= 1
            month_name = datetime(y, m, 1).strftime("%b")
            months_list.append({
                "year": y,
                "month": m,
                "label": month_name,
                "count": 0
            })

        start_date = datetime(months_list[0]["year"], months_list[0]["month"], 1)
        raw_regs = await self.repo.get_patients_last_6_months(start_date)
        regs_map = {(r["year"], r["month"]): r["count"] for r in raw_regs}
        
        monthly_registrations = []
        for item in months_list:
            key = (item["year"], item["month"])
            count = regs_map.get(key, 0)
            monthly_registrations.append(PatientRegistrationItem(
                month=item["label"],
                count=count
            ))

        if now.month == 1:
            prev_month_start = datetime(now.year - 1, 12, 1)
            prev_month_end = datetime(now.year - 1, 12, 31, 23, 59, 59, 999999)
        else:
            prev_month_start = datetime(now.year, now.month - 1, 1)
            prev_month_end = current_month_start - timedelta(microseconds=1)

        raw_overview = await self.repo.get_dashboard_overview_data(current_month_start, prev_month_start, prev_month_end)
        
        def compute_growth(curr: int, prev: int) -> float:
            if prev == 0:
                return 100.0 if curr > 0 else 0.0
            return round(((curr - prev) / prev) * 100, 2)

        patient_growth = compute_growth(raw_overview["current_patients"], raw_overview["prev_patients"])

        return PatientAnalyticsResponse(
            total_patients=raw_overview["total_patients"],
            patient_growth_percentage=patient_growth,
            monthly_registrations=monthly_registrations
        )

    async def get_users_dashboard(self) -> UsersDashboardResponse:
        from app.core.constants import UserRole

        raw_distribution = await self.repo.get_users_distribution_data()
        dist_map = {item["role_name"]: item["count"] for item in raw_distribution}

        admins_count = dist_map.get(UserRole.SUPER_ADMIN, 0) + dist_map.get(UserRole.HOSPITAL_ADMIN, 0)
        doctors_count = dist_map.get(UserRole.DOCTOR, 0)
        nurses_count = dist_map.get(UserRole.NURSE, 0)
        
        staff_roles = [
            UserRole.RECEPTIONIST,
            UserRole.ACCOUNTANT,
            UserRole.PHARMACIST,
            UserRole.LAB_TECHNICIAN
        ]
        staff_count = sum(dist_map.get(role, 0) for role in staff_roles)

        user_distribution = UserDistribution(
            admins=admins_count,
            doctors=doctors_count,
            nurses=nurses_count,
            staff=staff_count
        )

        recent_admins_raw = await self.repo.get_recent_admins(limit=10)
        
        recent_admins = []
        for user in recent_admins_raw:
            recent_admins.append(RecentAdminItem(
                id=user.id,
                full_name=user.full_name,
                email=user.email,
                role=UserRole.HOSPITAL_ADMIN,
                status="active" if user.is_active else "inactive",
                hospital_name=user.hospital.name if user.hospital else None
            ))

        return UsersDashboardResponse(
            user_distribution=user_distribution,
            recent_admins=recent_admins
        )
