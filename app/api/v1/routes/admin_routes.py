from fastapi import APIRouter

from app.core.dependencies import AdminUser, DbSession

router = APIRouter()


@router.get("/users")
async def admin_list_users(db: DbSession, _: AdminUser):
    return {"message": "Admin user management"}


@router.get("/audit-logs")
async def admin_audit_logs(db: DbSession, _: AdminUser):
    return {"message": "Audit logs"}

