from datetime import date

from fastapi import APIRouter, Depends, Response, Query
from fastapi.responses import FileResponse

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.billing_schema import (
    BillingCreate,
    BillingResponse,
    BillingSummary,
    BillingUpdate,
    DailyCollectionSummary,
    PaymentCreate,
    PaymentResponse,
    RefundCreate,
    RevenueReport,
)
from app.schemas.common_schema import APIResponse, MessageResponse
from app.services.billing_service import BillingService
from app.utils.pagination import PaginatedResult

router = APIRouter()


@router.post("", response_model=APIResponse[BillingResponse], status_code=201)
async def create_billing(
    data: BillingCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("billing", "create")),
):
    billing = await BillingService(db).create(data, current_user.id)
    return APIResponse(message="Bill created successfully", data=billing)


@router.get("", response_model=APIResponse[PaginatedResult[BillingResponse]])
async def list_billings(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    status: str | None = None,
    patient_id: int | None = None,
    q: str | None = None,
    _: User = Depends(require_permission("billing", "read")),
):
    service = BillingService(db)
    if q:
        result = await service.search(q, page=page, size=size, status=status)
    else:
        result = await service.list_billings(
            page=page, size=size, sort_by=sort_by, sort_order=sort_order,
            status=status, patient_id=patient_id,
        )
    return APIResponse(message="Bills retrieved", data=result)


@router.get("/reports/daily", response_model=APIResponse[DailyCollectionSummary])
async def daily_collection_report(
    db: DbSession,
    current_user: CurrentUser,
    target_date: date | None = None,
    _: User = Depends(require_permission("billing", "read")),
):
    report = await BillingService(db).get_daily_report(target_date)
    return APIResponse(message="Daily collection report", data=report)


@router.get("/reports/monthly", response_model=APIResponse[RevenueReport])
async def monthly_revenue_report(
    db: DbSession,
    current_user: CurrentUser,
    target_date: date | None = Query(default=None),
    _: User = Depends(require_permission("billing", "read")),
):
    report = await BillingService(db).get_period_report("monthly", target_date)
    return APIResponse(message="Monthly revenue report", data=report)


@router.get("/reports/yearly", response_model=APIResponse[RevenueReport])
async def yearly_revenue_report(
    db: DbSession,
    current_user: CurrentUser,
    target_date: date | None = Query(default=None),
    _: User = Depends(require_permission("billing", "read")),
):
    report = await BillingService(db).get_period_report("yearly", target_date)
    return APIResponse(message="Yearly revenue report", data=report)


@router.get("/pending-payments", response_model=APIResponse[PaginatedResult[BillingResponse]])
async def pending_payments(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    _: User = Depends(require_permission("billing", "read")),
):
    result = await BillingService(db).get_pending_payments(page=page, size=size)
    return APIResponse(message="Pending payments retrieved", data=result)


@router.get("/revenue-summary", response_model=APIResponse[BillingSummary])
async def revenue_summary(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("billing", "read")),
):
    summary = await BillingService(db).get_revenue_summary()
    return APIResponse(message="Revenue summary", data=summary)


@router.get("/{billing_id}", response_model=APIResponse[BillingResponse])
async def get_billing(
    billing_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("billing", "read")),
):
    billing = await BillingService(db).get_by_id(billing_id)
    return APIResponse(message="Bill retrieved", data=billing)


@router.put("/{billing_id}", response_model=APIResponse[BillingResponse])
async def update_billing(
    billing_id: int,
    data: BillingUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("billing", "update")),
):
    billing = await BillingService(db).update(billing_id, data, current_user.id)
    return APIResponse(message="Bill updated", data=billing)


@router.delete("/{billing_id}", response_model=APIResponse[MessageResponse])
async def delete_billing(
    billing_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("billing", "delete")),
):
    await BillingService(db).delete(billing_id, current_user.id)
    return APIResponse(message="Bill deleted", data=MessageResponse(message="Soft deleted"))


@router.post("/{billing_id}/payment", response_model=APIResponse[PaymentResponse], status_code=201)
async def collect_payment(
    billing_id: int,
    data: PaymentCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("billing", "update")),
):
    payment = await BillingService(db).collect_payment(billing_id, data, current_user.id)
    return APIResponse(message="Payment collected", data=payment)


@router.post("/{billing_id}/refund", response_model=APIResponse[PaymentResponse], status_code=201)
async def process_refund(
    billing_id: int,
    data: RefundCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("billing", "approve")),
):
    payment = await BillingService(db).process_refund(billing_id, data, current_user.id)
    return APIResponse(message="Refund processed", data=payment)


@router.get("/{billing_id}/invoice")
async def download_invoice(
    billing_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("billing", "export")),
):
    _, pdf_bytes = await BillingService(db).generate_invoice(billing_id, current_user.id)
    print("DEBUG: type(pdf_bytes) =", type(pdf_bytes))
    if isinstance(pdf_bytes, bytes):
        print("DEBUG: len(pdf_bytes) =", len(pdf_bytes))
        print("DEBUG: pdf_bytes starts with:", pdf_bytes[:20])
    else:
        print("DEBUG: pdf_bytes value:", str(pdf_bytes)[:100])

    response = Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=invoice_{billing_id}.pdf"
        }
    )
    print("DEBUG: response.media_type =", response.media_type)
    print("DEBUG: response.headers =", dict(response.headers))
    return response
