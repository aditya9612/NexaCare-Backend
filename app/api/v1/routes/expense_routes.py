from datetime import date
from fastapi import APIRouter, Depends, Query

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.common_schema import APIResponse, MessageResponse
from app.schemas.expense_schema import (
    ExpenseCategoryCreate, ExpenseCategoryUpdate, ExpenseCategoryResponse,
    ExpenseCreate, ExpenseUpdate, ExpenseResponse, ExpenseQuery,
    VendorPaymentCreate, VendorPaymentUpdate, VendorPaymentResponse,
    ExpenseSummaryResponse
)
from app.services.expense_service import ExpenseService
from app.utils.pagination import PaginatedResult

router = APIRouter()


# --- Expense Categories ---

@router.post("/categories", response_model=APIResponse[ExpenseCategoryResponse], status_code=201)
async def create_expense_category(
    data: ExpenseCategoryCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("expense", "create")),
):
    category = await ExpenseService(db).create_category(data, current_user.id)
    return APIResponse(message="Expense category created", data=category)


@router.get("/categories", response_model=APIResponse[PaginatedResult[ExpenseCategoryResponse]])
async def list_expense_categories(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_permission("expense", "read")),
):
    result = await ExpenseService(db).list_categories(page=page, size=size)
    return APIResponse(message="Expense categories retrieved", data=result)


@router.get("/categories/{category_id}", response_model=APIResponse[ExpenseCategoryResponse])
async def get_expense_category(
    category_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("expense", "read")),
):
    category = await ExpenseService(db).get_category(category_id)
    return APIResponse(message="Expense category retrieved", data=category)


@router.patch("/categories/{category_id}", response_model=APIResponse[ExpenseCategoryResponse])
async def update_expense_category(
    category_id: int,
    data: ExpenseCategoryUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("expense", "update")),
):
    category = await ExpenseService(db).update_category(category_id, data, current_user.id)
    return APIResponse(message="Expense category updated", data=category)


@router.delete("/categories/{category_id}", response_model=APIResponse[MessageResponse])
async def delete_expense_category(
    category_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("expense", "delete")),
):
    await ExpenseService(db).delete_category(category_id, current_user.id)
    return APIResponse(message="Expense category deleted", data=MessageResponse(message="Soft deleted"))


# --- Expense Vendors ---

# --- Expense Vendor endpoints removed (moved to unified /vendors API) ---


# --- Vendor Payments ---

@router.post("/vendor-payments", response_model=APIResponse[VendorPaymentResponse], status_code=201)
async def create_vendor_payment(
    data: VendorPaymentCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("expense", "create")),
):
    payment = await ExpenseService(db).create_payment(data, current_user.id)
    return APIResponse(message="Vendor payment recorded", data=payment)


@router.get("/vendor-payments", response_model=APIResponse[PaginatedResult[VendorPaymentResponse]])
async def list_vendor_payments(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    vendor_id: int | None = Query(None),
    expense_id: int | None = Query(None),
    _: User = Depends(require_permission("expense", "read")),
):
    result = await ExpenseService(db).list_payments(
        page=page, size=size, vendor_id=vendor_id, expense_id=expense_id
    )
    return APIResponse(message="Vendor payments retrieved", data=result)


@router.get("/vendor-payments/{payment_id}", response_model=APIResponse[VendorPaymentResponse])
async def get_vendor_payment(
    payment_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("expense", "read")),
):
    payment = await ExpenseService(db).get_payment(payment_id)
    return APIResponse(message="Vendor payment retrieved", data=payment)


@router.patch("/vendor-payments/{payment_id}", response_model=APIResponse[VendorPaymentResponse])
async def update_vendor_payment(
    payment_id: int,
    data: VendorPaymentUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("expense", "update")),
):
    payment = await ExpenseService(db).update_payment(payment_id, data, current_user.id)
    return APIResponse(message="Vendor payment updated", data=payment)


@router.delete("/vendor-payments/{payment_id}", response_model=APIResponse[MessageResponse])
async def delete_vendor_payment(
    payment_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("expense", "delete")),
):
    await ExpenseService(db).delete_payment(payment_id, current_user.id)
    return APIResponse(message="Vendor payment deleted", data=MessageResponse(message="Soft deleted"))


# --- Reports ---

@router.get("/reports/summary", response_model=APIResponse[ExpenseSummaryResponse])
async def get_expenses_summary(
    db: DbSession,
    current_user: CurrentUser,
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    _: User = Depends(require_permission("expense", "read")),
):
    summary = await ExpenseService(db).get_expense_summary(start_date, end_date)
    return APIResponse(message="Expenses summary retrieved", data=summary)


# --- Expenses ---

@router.post("", response_model=APIResponse[ExpenseResponse], status_code=201)
async def create_expense(
    data: ExpenseCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("expense", "create")),
):
    expense = await ExpenseService(db).create_expense(data, current_user.id)
    return APIResponse(message="Expense recorded", data=expense)


@router.get("", response_model=APIResponse[PaginatedResult[ExpenseResponse]])
async def list_expenses(
    db: DbSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    category_id: int | None = Query(None),
    vendor_id: int | None = Query(None),
    status: str | None = Query(None),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    description: str | None = Query(None),
    _: User = Depends(require_permission("expense", "read")),
):
    query = ExpenseQuery(
        page=page,
        size=size,
        sort_by=sort_by,
        sort_order=sort_order,
        category_id=category_id,
        vendor_id=vendor_id,
        status=status,
        start_date=start_date,
        end_date=end_date,
        description=description
    )
    result = await ExpenseService(db).list_expenses(query)
    return APIResponse(message="Expenses retrieved", data=result)


@router.get("/{expense_id}", response_model=APIResponse[ExpenseResponse])
async def get_expense(
    expense_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("expense", "read")),
):
    expense = await ExpenseService(db).get_expense(expense_id)
    return APIResponse(message="Expense retrieved", data=expense)


@router.patch("/{expense_id}", response_model=APIResponse[ExpenseResponse])
async def update_expense(
    expense_id: int,
    data: ExpenseUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("expense", "update")),
):
    expense = await ExpenseService(db).update_expense(expense_id, data, current_user.id)
    return APIResponse(message="Expense updated", data=expense)


@router.delete("/{expense_id}", response_model=APIResponse[MessageResponse])
async def delete_expense(
    expense_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("expense", "delete")),
):
    await ExpenseService(db).delete_expense(expense_id, current_user.id)
    return APIResponse(message="Expense deleted", data=MessageResponse(message="Soft deleted"))
