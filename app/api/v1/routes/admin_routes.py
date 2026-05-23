from fastapi import APIRouter

from app.core.dependencies import CurrentUser, DbSession

router = APIRouter()


@router.get("/users")
async def admin_list_users(db: DbSession, _: CurrentUser):
    return {"message": "Admin user management"}


@router.get("/audit-logs")
async def admin_audit_logs(db: DbSession, _: CurrentUser):
    return {"message": "Audit logs"}
