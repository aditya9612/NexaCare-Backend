from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.core.exceptions import BadRequestException
from app.schemas.common_schema import APIResponse, MessageResponse
from app.schemas.pharmacy_schema import (
    ExpiryAlert,
    LowStockAlert,
    MedicineCreate,
    MedicineResponse,
    MedicineUpdate,
    PharmacyInvoiceCreate,
    PharmacyInvoiceUpdate,
    PharmacyInvoiceResponse,
    PharmacyDashboardResponse,
    PharmacyInventoryOverviewResponse,
    PrescriptionCreate,
    PrescriptionResponse,
    PrescriptionUpdate,
    PrescriptionStatusUpdate,
    PurchaseCreate,
    PurchaseResponse,
    SalesReport,
    SupplierCreate,
    SupplierResponse,
    SupplierUpdate,
    PharmacyDashboardResponse,
)

from app.services.pharmacy_service import PharmacyService
from app.utils.pagination import PaginatedResult

router = APIRouter()

ALLOWED_FILTERS = {"today", "7_days", "30_days", "month_to_date", "month", "3_month", "overall", "custom"}


# --- Pharmacy Dashboard ---
@router.get("/dashboard", response_model=APIResponse[PharmacyDashboardResponse])
@router.get("/dashboard/summary", response_model=APIResponse[PharmacyDashboardResponse])
async def get_pharmacy_dashboard(
    db: DbSession,
    current_user: CurrentUser,
    time_filter: str = Query("7_days", alias="filter", description="Time range filter (default: 7_days)"),
    start_date: Optional[date] = Query(None, description="Start date for custom filter (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date for custom filter (YYYY-MM-DD)"),
    _: User = Depends(require_permission("pharmacy", "read")),
):
    if time_filter not in ALLOWED_FILTERS:
        raise BadRequestException(f"Invalid filter. Allowed values: {', '.join(sorted(ALLOWED_FILTERS))}")
    if time_filter == "custom":
        if not start_date or not end_date:
            raise BadRequestException("start_date and end_date are required when filter is 'custom'")
        if start_date > end_date:
            raise BadRequestException("start_date cannot be after end_date")

    dashboard_data = await PharmacyService(db).get_dashboard_summary(
        time_filter=time_filter,
        start_date=start_date,
        end_date=end_date,
    )
    return APIResponse(message="Pharmacy dashboard summary retrieved", data=dashboard_data)



# --- Medicines ---

@router.post("/medicines", response_model=APIResponse[MedicineResponse], status_code=201)
async def create_medicine(
    data: MedicineCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "create")),
):
    medicine = await PharmacyService(db).create_medicine(data, current_user.id)
    return APIResponse(message="Medicine created", data=medicine)


@router.get("/medicines", response_model=APIResponse[PaginatedResult[MedicineResponse]])
async def list_medicines(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    category: str | None = None,
    q: str | None = None,
    _: User = Depends(require_permission("pharmacy", "read")),
):
    service = PharmacyService(db)
    if q:
        result = await service.search_medicines(q, page=page, size=size)
    else:
        result = await service.list_medicines(
            page=page, size=size, sort_by=sort_by, sort_order=sort_order, category=category
        )
    return APIResponse(message="Medicines retrieved", data=result)


@router.get("/medicines/{medicine_id}", response_model=APIResponse[MedicineResponse])
async def get_medicine(
    medicine_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "read")),
):
    medicine = await PharmacyService(db).get_medicine(medicine_id)
    return APIResponse(message="Medicine retrieved", data=medicine)


@router.put("/medicines/{medicine_id}", response_model=APIResponse[MedicineResponse])
async def update_medicine(
    medicine_id: int,
    data: MedicineUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "update")),
):
    medicine = await PharmacyService(db).update_medicine(medicine_id, data, current_user.id)
    return APIResponse(message="Medicine updated", data=medicine)


@router.delete("/medicines/{medicine_id}", response_model=APIResponse[MessageResponse])
async def delete_medicine(
    medicine_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "delete")),
):
    await PharmacyService(db).delete_medicine(medicine_id, current_user.id)
    return APIResponse(message="Medicine deleted", data=MessageResponse(message="Soft deleted"))


# --- Prescriptions ---
@router.post("/prescriptions", response_model=APIResponse[PrescriptionResponse], status_code=201)
async def create_prescription(
    data: PrescriptionCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "create")),
):
    prescription = await PharmacyService(db).create_prescription(data, current_user.id)
    return APIResponse(message="Prescription created", data=prescription)


@router.get("/prescriptions", response_model=APIResponse[PaginatedResult[PrescriptionResponse]])
async def list_prescriptions(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    status: str | None = None,
    patient_id: int | None = Query(None),
    appointment_id: int | None = Query(None),
    _: User = Depends(require_permission("pharmacy", "read")),
):
    from app.repositories.doctor_repository import DoctorRepository
    doctor = await DoctorRepository(db).get_by_user_id(current_user.id)
    
    result = await PharmacyService(db).list_prescriptions(
        page=page,
        size=size,
        status=status,
        doctor_id=doctor.id if doctor else None,
        patient_id=patient_id,
        appointment_id=appointment_id,
    )
    return APIResponse(message="Prescriptions retrieved", data=result)




@router.get("/prescriptions/{prescription_id}")
async def get_prescription(
    prescription_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "read")),
):
    from app.repositories.doctor_repository import DoctorRepository
    doctor = await DoctorRepository(db).get_by_user_id(current_user.id)
    prescription = await PharmacyService(db).get_prescription(
        prescription_id,
        doctor_id=doctor.id if doctor else None
    )
    return APIResponse(message="Prescription retrieved", data=prescription)


@router.put("/prescriptions/{prescription_id}", response_model=APIResponse[PrescriptionResponse])
async def update_prescription(
    prescription_id: int,
    data: PrescriptionUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "update")),
):
    from app.repositories.doctor_repository import DoctorRepository
    from app.core.exceptions import ForbiddenException
    doctor = await DoctorRepository(db).get_by_user_id(current_user.id)
    if not doctor:
        raise ForbiddenException("Only registered doctors can modify prescriptions")
    
    prescription = await PharmacyService(db).update_prescription(
        prescription_id=prescription_id,
        data=data,
        doctor_id=doctor.id,
        user_id=current_user.id,
        current_user=current_user
    )
    return APIResponse(message="Prescription updated", data=prescription)


@router.patch("/prescriptions/{prescription_id}/status", response_model=APIResponse[PrescriptionResponse])
async def update_prescription_status(
    prescription_id: int,
    data: PrescriptionStatusUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "update")),
):
    prescription = await PharmacyService(db).update_prescription_status(
        prescription_id=prescription_id,
        data=data,
        user_id=current_user.id
    )
    return APIResponse(message="Prescription status updated", data=prescription)



@router.delete("/prescriptions/{prescription_id}", response_model=APIResponse[MessageResponse])
async def delete_prescription(
    prescription_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "delete")),
):
    from app.repositories.doctor_repository import DoctorRepository
    from app.core.exceptions import ForbiddenException
    doctor = await DoctorRepository(db).get_by_user_id(current_user.id)
    if not doctor:
        raise ForbiddenException("Only registered doctors can delete prescriptions")
        
    await PharmacyService(db).delete_prescription(
        prescription_id=prescription_id,
        doctor_id=doctor.id,
        user_id=current_user.id
    )
    return APIResponse(message="Prescription deleted", data=MessageResponse(message="Deleted successfully"))


# --- Invoices ---    


# --- Invoices ---
@router.post("/invoices", response_model=APIResponse[PharmacyInvoiceResponse], status_code=201)
async def create_pharmacy_invoice(
    data: PharmacyInvoiceCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "create")),
):
    invoice = await PharmacyService(db).create_invoice(data, current_user.id)
    return APIResponse(message="Pharmacy invoice created", data=invoice)


@router.get("/invoices", response_model=APIResponse[PaginatedResult[PharmacyInvoiceResponse]])
async def list_pharmacy_invoices(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    _: User = Depends(require_permission("pharmacy", "read")),
):
    result = await PharmacyService(db).list_invoices(page=page, size=size)
    return APIResponse(message="Pharmacy invoices retrieved", data=result)

@router.get("/invoices/{invoice_id}", response_model=APIResponse[PharmacyInvoiceResponse])
async def get_pharmacy_invoice(
    invoice_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "read")),
):
    invoice = await PharmacyService(db).get_invoice_by_id(invoice_id)
    return APIResponse(message="Pharmacy invoice retrieved", data=invoice)


@router.put("/invoices/{invoice_id}", response_model=APIResponse[PharmacyInvoiceResponse])
async def update_pharmacy_invoice(
    invoice_id: int,
    data: PharmacyInvoiceUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "update")),
):
    invoice = await PharmacyService(db).update_invoice(invoice_id, data)
    return APIResponse(message="Pharmacy invoice updated", data=invoice)



@router.get("/invoices/{invoice_id}/download")
async def download_pharmacy_invoice(
    invoice_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "read")),
):
    return await PharmacyService(db).download_invoice(invoice_id)


@router.delete("/invoices/{invoice_id}", response_model=APIResponse[MessageResponse])
async def delete_pharmacy_invoice(
    invoice_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "delete")),
):
    await PharmacyService(db).delete_invoice(invoice_id)
    return APIResponse(message="Pharmacy invoice deleted", data=MessageResponse(message="Soft deleted"))


# --- Suppliers ---
@router.post("/suppliers", response_model=APIResponse[SupplierResponse], status_code=201)
async def create_supplier(
    data: SupplierCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "create")),
):
    supplier = await PharmacyService(db).create_supplier(data, current_user.id)
    return APIResponse(message="Supplier created", data=supplier)


@router.get("/suppliers", response_model=APIResponse[PaginatedResult[SupplierResponse]])
async def list_suppliers(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    _: User = Depends(require_permission("pharmacy", "read")),
):
    result = await PharmacyService(db).list_suppliers(page=page, size=size)
    return APIResponse(message="Suppliers retrieved", data=result)

@router.get("/suppliers/{supplier_id}", response_model=APIResponse[SupplierResponse])
async def get_supplier(
    supplier_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "read")),
):
    supplier = await PharmacyService(db).get_supplier(supplier_id)
    return APIResponse(message="Supplier retrieved", data=supplier)

@router.put("/suppliers/{supplier_id}", response_model=APIResponse[SupplierResponse])
async def update_supplier(
    supplier_id: int,
    data: SupplierUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "update")),
):
    supplier = await PharmacyService(db).update_supplier(supplier_id, data, current_user.id)
    return APIResponse(message="Supplier updated", data=supplier)


@router.delete("/suppliers/{supplier_id}", response_model=APIResponse[MessageResponse])
async def delete_supplier(
    supplier_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "delete")),
):
    await PharmacyService(db).delete_supplier(supplier_id, current_user.id)
    return APIResponse(message="Supplier deleted", data=MessageResponse(message="Soft deleted"))


# --- Purchases ---
@router.post("/purchases", response_model=APIResponse[PurchaseResponse], status_code=201)
async def create_purchase(
    data: PurchaseCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "create")),
):
    purchase = await PharmacyService(db).create_purchase(data, current_user.id)
    return APIResponse(message="Purchase created", data=purchase)


@router.get("/purchases", response_model=APIResponse[PaginatedResult[PurchaseResponse]])
async def list_purchases(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    _: User = Depends(require_permission("pharmacy", "read")),
):
    result = await PharmacyService(db).list_purchases(page=page, size=size)
    return APIResponse(message="Purchases retrieved", data=result)

@router.get("/purchases/{purchase_id}", response_model=APIResponse[PurchaseResponse])
async def get_purchase(
    purchase_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "read")),
):
    purchase = await PharmacyService(db).get_purchase(purchase_id)
    return APIResponse(message="Purchase retrieved", data=purchase)


@router.put("/purchases/{purchase_id}", response_model=APIResponse[PurchaseResponse])
async def update_purchase(
    purchase_id: int,
    data: PurchaseCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "update")),
):
    purchase = await PharmacyService(db).update_purchase(
        purchase_id, data, current_user.id
    )
    return APIResponse(message="Purchase updated", data=purchase)


@router.delete("/purchases/{purchase_id}", response_model=APIResponse[MessageResponse])
async def delete_purchase(
    purchase_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "delete")),
):
    await PharmacyService(db).delete_purchase(
        purchase_id, current_user.id
    )
    return APIResponse(
        message="Purchase deleted",
        data=MessageResponse(message="Soft deleted"),
    )


@router.patch("/purchases/{purchase_id}/receive", response_model=APIResponse[PurchaseResponse])
async def receive_purchase_order(
    purchase_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "update")),
):
    purchase = await PharmacyService(db).receive_purchase_order(
        purchase_id, current_user
    )
    return APIResponse(
        message="Purchase order received and stock updated",
        data=purchase,
    )    


# --- Alerts & Reports ---
@router.get("/low-stock", response_model=APIResponse[list[LowStockAlert]])
async def low_stock_alerts(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "read")),
):
    alerts = await PharmacyService(db).get_low_stock()
    return APIResponse(message="Low stock alerts", data=alerts)


@router.get("/expiry-alerts", response_model=APIResponse[list[ExpiryAlert]])
async def expiry_alerts(
    db: DbSession,
    current_user: CurrentUser,
    days: int = 30,
    _: User = Depends(require_permission("pharmacy", "read")),
):
    alerts = await PharmacyService(db).get_expiry_alerts(days=days)
    return APIResponse(message="Expiry alerts", data=alerts)


@router.get("/sales-reports", response_model=APIResponse[SalesReport])
async def sales_report(
    db: DbSession,
    current_user: CurrentUser,
    period: str = "monthly",
    _: User = Depends(require_permission("pharmacy", "read")),
):
    report = await PharmacyService(db).get_sales_report(period=period)
    return APIResponse(message="Sales report", data=report)


@router.get("/dashboard/summary", response_model=APIResponse[PharmacyDashboardResponse])
async def get_dashboard_summary(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "read")),
):
    summary = await PharmacyService(db).get_dashboard_summary()
    return APIResponse(message="Pharmacy dashboard summary retrieved", data=summary)


@router.get("/inventory/overview", response_model=APIResponse[PharmacyInventoryOverviewResponse])
async def get_inventory_overview(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "read")),
):
    overview = await PharmacyService(db).get_inventory_overview()
    return APIResponse(message="Pharmacy inventory overview retrieved", data=overview)
