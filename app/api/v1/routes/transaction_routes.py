from datetime import date
from fastapi import APIRouter, Depends, Query

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.common_schema import APIResponse, MessageResponse
from app.schemas.transaction_schema import TransactionCreate, TransactionUpdate, TransactionResponse
from app.services.transaction_service import TransactionService
from app.utils.pagination import PaginatedResult

router = APIRouter()


@router.post("", response_model=APIResponse[TransactionResponse], status_code=201)
async def create_transaction(
    data: TransactionCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("billing", "update")),
):
    transaction = await TransactionService(db).create_transaction(data, current_user.id)
    return APIResponse(message="Transaction recorded successfully", data=transaction)


@router.get("", response_model=APIResponse[PaginatedResult[TransactionResponse]])
async def list_transactions(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    billing_id: int | None = Query(None),
    payment_method: str | None = Query(None),
    status: str | None = Query(None),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    q: str | None = Query(None),
    _: User = Depends(require_permission("billing", "read")),
):
    result = await TransactionService(db).list_transactions(
        page=page,
        size=size,
        sort_by=sort_by,
        sort_order=sort_order,
        billing_id=billing_id,
        payment_method=payment_method,
        status=status,
        start_date=start_date,
        end_date=end_date,
        q=q,
    )
    return APIResponse(message="Transaction history retrieved successfully", data=result)


@router.get("/{id}", response_model=APIResponse[TransactionResponse])
async def get_transaction(
    id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("billing", "read")),
):
    transaction = await TransactionService(db).get_transaction(id)
    return APIResponse(message="Transaction retrieved successfully", data=transaction)


@router.patch("/{id}", response_model=APIResponse[TransactionResponse])
async def update_transaction(
    id: int,
    data: TransactionUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("billing", "update")),
):
    transaction = await TransactionService(db).update_transaction(id, data, current_user.id)
    return APIResponse(message="Transaction updated successfully", data=transaction)


@router.delete("/{id}", response_model=APIResponse[MessageResponse])
async def delete_transaction(
    id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("billing", "delete")),
):
    await TransactionService(db).delete_transaction(id, current_user.id)
    return APIResponse(message="Transaction deleted successfully", data=MessageResponse(message="Deleted successfully"))
