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

# New response models for Overview, Patients, and Users dashboards

class DashboardOverviewResponse(BaseSchema):
    total_patients: int
    patient_growth_percentage: float
    total_appointments: int
    appointment_growth_percentage: float
    active_sessions: int
    session_growth_percentage: float
    system_health: str
    uptime_percentage: float

class PatientRegistrationItem(BaseSchema):
    month: str
    count: int

class PatientAnalyticsResponse(BaseSchema):
    total_patients: int
    patient_growth_percentage: float
    monthly_registrations: list[PatientRegistrationItem]

class UserDistribution(BaseSchema):
    admins: int
    doctors: int
    nurses: int
    staff: int

class RecentAdminItem(BaseSchema):
    id: int
    full_name: str
    email: str
    role: str
    status: str
    hospital_name: str | None = None

class UsersDashboardResponse(BaseSchema):
    user_distribution: UserDistribution
    recent_admins: list[RecentAdminItem]
