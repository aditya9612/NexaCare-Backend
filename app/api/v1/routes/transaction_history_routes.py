from datetime import date
from fastapi import APIRouter, Depends, Query

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.common_schema import APIResponse, MessageResponse
from app.schemas.transaction_history_schema import (
    TransactionHistoryCreate,
    TransactionHistoryResponse,
    DashboardSummaryResponse,
)
from app.services.transaction_history_service import TransactionHistoryService
from app.utils.pagination import PaginatedResult

router = APIRouter()


@router.post("", response_model=APIResponse[TransactionHistoryResponse], status_code=201)
async def create_transaction_history(
    data: TransactionHistoryCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("billing", "create")),
):
    tx_history = await TransactionHistoryService(db).create_transaction_history(data, current_user.id)
    return APIResponse(message="Transaction History entry created successfully", data=tx_history)


@router.get("", response_model=APIResponse[PaginatedResult[TransactionHistoryResponse]])
async def list_transaction_histories(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    event_type: str | None = Query(None),
    status: str | None = Query(None),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    reference: str | None = Query(None),
    q: str | None = Query(None),
    _: User = Depends(require_permission("billing", "read")),
):
    result = await TransactionHistoryService(db).list_transaction_histories(
        page=page,
        size=size,
        sort_by=sort_by,
        sort_order=sort_order,
        event_type=event_type,
        status=status,
        start_date=start_date,
        end_date=end_date,
        reference_no=reference,
        q=q,
    )
    return APIResponse(message="Transaction History retrieved successfully", data=result)


@router.get("/summary", response_model=APIResponse[DashboardSummaryResponse])
async def get_dashboard_summary(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("billing", "read")),
):
    summary = await TransactionHistoryService(db).get_dashboard_summary()
    return APIResponse(message="Dashboard financial summary retrieved successfully", data=summary)


@router.get("/{id}", response_model=APIResponse[TransactionHistoryResponse])
async def get_transaction_history(
    id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("billing", "read")),
):
    tx_history = await TransactionHistoryService(db).get_transaction_history(id)
    return APIResponse(message="Transaction History details retrieved successfully", data=tx_history)


@router.delete("/{id}", response_model=APIResponse[MessageResponse])
async def delete_transaction_history(
    id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("billing", "delete")),
):
    await TransactionHistoryService(db).delete_transaction_history(id, current_user.id)
    return APIResponse(message="Transaction History deleted successfully", data=MessageResponse(message="Soft deleted"))
