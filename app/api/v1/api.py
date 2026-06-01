from fastapi import APIRouter

from app.api.v1.routes import (
    admin_routes,
    ai_routes,
    analytics_routes,
    appointment_routes,
    auth_routes,
    billing_routes,
    chat_routes,
    dashboard_routes,
    doctor_routes,
    department_routes,
    inventory_routes,
    lab_routes,
    nurse_routes,
    patient_routes,
    pharmacy_routes,
    rbac_routes,
    voice_assistant_routes,
    voice_routes,
    whatsapp_routes,
    super_admin_routes,
    subscription_routes,
    platform_routes,
    security_routes,
    branch_routes,
    admin_management_routes,
)


api_router = APIRouter()

api_router.include_router(auth_routes.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(rbac_routes.router, tags=["RBAC"])
api_router.include_router(patient_routes.router, prefix="/patients", tags=["Patients"])
api_router.include_router(doctor_routes.router, prefix="/doctors", tags=["Doctors"])
api_router.include_router(appointment_routes.router, prefix="/appointments", tags=["Appointments"])
api_router.include_router(dashboard_routes.router, prefix="/dashboard", tags=["Dashboard"])
api_router.include_router(nurse_routes.router, prefix="/nurses", tags=["Nurses"])
api_router.include_router(pharmacy_routes.router, prefix="/pharmacy", tags=["Pharmacy"])
api_router.include_router(lab_routes.router, prefix="/lab", tags=["Lab"])
api_router.include_router(billing_routes.router, prefix="/billing", tags=["Billing"])
api_router.include_router(department_routes.router, prefix="/departments", tags=["Departments"])
api_router.include_router(inventory_routes.router, prefix="/inventory", tags=["Inventory"])
api_router.include_router(admin_routes.router, prefix="/admin", tags=["Admin"])
api_router.include_router(ai_routes.router, prefix="/ai", tags=["AI"])
api_router.include_router(chat_routes.router, prefix="/ai/chat", tags=["AI Chatbot"])
api_router.include_router(voice_routes.router, prefix="/voice-reminder", tags=["Voice Reminder"])
api_router.include_router(
    voice_assistant_routes.router,
    prefix="/voice-assistant",
    tags=["Voice Appointment Assistant"],
)
api_router.include_router(whatsapp_routes.router, prefix="/whatsapp", tags=["WhatsApp"])
api_router.include_router(analytics_routes.router, prefix="/analytics", tags=["Analytics"])
api_router.include_router(super_admin_routes.router, prefix="/super-admin", tags=["Super Admin"])
api_router.include_router(subscription_routes.router, prefix="/subscriptions", tags=["Subscriptions"])
api_router.include_router(platform_routes.router, prefix="/platform", tags=["Platform"])
api_router.include_router(security_routes.router, prefix="/security", tags=["Security"])
api_router.include_router(branch_routes.router, prefix="/branches", tags=["Branches"])
api_router.include_router(admin_management_routes.router, prefix="/super-admin/admins", tags=["Super Admin Admins"])

