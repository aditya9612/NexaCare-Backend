from fastapi import APIRouter, Depends

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.accountant_schema import AccountantDashboardResponse
from app.schemas.common_schema import APIResponse
from app.services.accountant_service import AccountantService

router = APIRouter()


@router.get(
    "/dashboard",
    response_model=APIResponse[AccountantDashboardResponse],
)
async def get_accountant_dashboard(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("billing", "read")),
):
    data = await AccountantService(db).get_dashboard()

    return APIResponse(
        message="Accountant dashboard retrieved",
        data=data,
    )