from pydantic import BaseModel
from app.schemas.common_schema import BaseSchema

class SuperAdminDashboardResponse(BaseSchema):
    total_hospitals: int
    total_branches: int
    total_admins: int
    active_admins: int
    inactive_admins: int
    online_admins: int
    total_doctors: int
    total_staff: int
    total_patients: int
    total_appointments: int
    active_sessions: int
    system_health: str

class HospitalGrowthItem(BaseSchema):
    month: str
    count: int

class RevenueTrendItem(BaseSchema):
    month: str
    amount: float

class SuperAdminAnalyticsResponse(BaseSchema):
    hospital_growth: list[HospitalGrowthItem]
    revenue_trends: list[RevenueTrendItem]
