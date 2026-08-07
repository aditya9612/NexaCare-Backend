from fastapi import APIRouter, Depends

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.schemas.common_schema import APIResponse, MessageResponse
from app.schemas.share_schema import ShareEmailRequest
from app.services.share_service import ShareService

router = APIRouter()


@router.post("/email", response_model=APIResponse[MessageResponse], status_code=200)
async def share_resource_via_email(
    data: ShareEmailRequest,
    db: DbSession,
    current_user: CurrentUser,
) -> APIResponse[MessageResponse]:
    """
    Share a resource (e.g., lab_report) via email.
    
    Checks permissions dynamically depending on the 'purpose':
    - purpose == 'lab_report': Requires 'lab:read' permission.
    """
    # 1. Dynamic permission check
    if data.purpose == "lab_report":
        checker = require_permission("lab", "share")
        await checker(db, current_user)
    
    # 2. Process dispatching
    await ShareService(db).dispatch_share(data, current_user)
    return APIResponse(message="Resource shared successfully via email", data=MessageResponse(message="Email dispatched"))
