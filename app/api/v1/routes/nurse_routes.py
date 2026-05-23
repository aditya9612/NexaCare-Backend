from fastapi import APIRouter

from app.core.dependencies import CurrentUser, DbSession

router = APIRouter()


@router.get("/")
async def list_nurses(db: DbSession, _: CurrentUser):
    return {"message": "Nurse endpoints - implement in nurse service"}


@router.get("/{nurse_id}")
async def get_nurse(nurse_id: int, db: DbSession, _: CurrentUser):
    return {"nurse_id": nurse_id}
