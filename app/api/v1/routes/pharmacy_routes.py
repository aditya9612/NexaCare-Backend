from datetime import date
from enum import Enum
from typing import Optional
from fastapi import APIRouter, Depends, Query, File, UploadFile, HTTPException, Response, Request
from fastapi.responses import StreamingResponse


class MedicineExportFormat(str, Enum):
    EXCEL = "excel"
    PDF = "pdf"

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
    PharmacyReturnCreate,
    PharmacyReturnResponse,
    PrescriptionCreate,
    PrescriptionDispenseRequest,
    PrescriptionResponse,
    PrescriptionStatusUpdate,
    PrescriptionUpdate,
    PurchaseCreate,
    PurchaseResponse,
    SalesReport,
    SupplierCreate,
    SupplierResponse,
    SupplierUpdate,
)

from app.services.pharmacy_service import PharmacyService
from app.utils.pagination import PaginatedResult

router = APIRouter()

ALLOWED_FILTERS = {
    "today", "7_days", "30_days", "month_to_date", "month",
    "3_month", "6_month", "1_year", "overall", "custom"
}

FILTER_ALIASES = {
    "today": "today",
    "7_days": "7_days",
    "7days": "7_days",
    "last_7_days": "7_days",
    "last7days": "7_days",
    "7d": "7_days",
    "week": "7_days",
    "this_week": "7_days",
    "1_week": "7_days",
    "30_days": "30_days",
    "30days": "30_days",
    "last_30_days": "30_days",
    "last30days": "30_days",
    "30d": "30_days",
    "month": "month",
    "month_to_date": "month_to_date",
    "this_month": "month_to_date",
    "current_month": "month_to_date",
    "1_month": "month",
    "1month": "month",
    "3_month": "3_month",
    "3_months": "3_month",
    "3month": "3_month",
    "3months": "3_month",
    "90_days": "3_month",
    "90days": "3_month",
    "quarter": "3_month",
    "6_month": "6_month",
    "6_months": "6_month",
    "6month": "6_month",
    "6months": "6_month",
    "180_days": "6_month",
    "year": "1_year",
    "1_year": "1_year",
    "1year": "1_year",
    "12_months": "1_year",
    "365_days": "1_year",
    "yearly": "1_year",
    "overall": "overall",
    "all": "overall",
    "all_time": "overall",
    "custom": "custom",
}


# --- Pharmacy Dashboard ---
@router.get("/dashboard", response_model=APIResponse[PharmacyDashboardResponse])
@router.get("/dashboard/summary", response_model=APIResponse[PharmacyDashboardResponse])
async def get_pharmacy_dashboard(
    request: Request,
    db: DbSession,
    current_user: CurrentUser,
    filter: Optional[str] = Query(None, description="Time range filter (today, 7_days, 30_days, month_to_date, month, 3_month, 6_month, 1_year, overall, custom)"),
    start_date: Optional[date] = Query(None, description="Start date for custom filter (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date for custom filter (YYYY-MM-DD)"),
    _: User = Depends(require_permission("pharmacy", "read")),
):
    qp = request.query_params
    raw_filter = filter or qp.get("time_filter") or qp.get("time_range") or qp.get("timeRange") or qp.get("period") or qp.get("range") or qp.get("timeline") or qp.get("filter_type")

    resolved_start = start_date
    if not resolved_start:
        for k in ("startDate", "from_date", "fromDate"):
            val = qp.get(k)
            if val:
                try:
                    resolved_start = date.fromisoformat(val)
                    break
                except ValueError:
                    pass

    resolved_end = end_date
    if not resolved_end:
        for k in ("endDate", "to_date", "toDate"):
            val = qp.get(k)
            if val:
                try:
                    resolved_end = date.fromisoformat(val)
                    break
                except ValueError:
                    pass

    if resolved_start or resolved_end:
        resolved_filter = "custom"
        if resolved_start and resolved_end and resolved_start > resolved_end:
            raise BadRequestException("start_date cannot be after end_date")
    elif raw_filter:
        clean_key = str(raw_filter).strip().lower().replace("-", "_")
        resolved_filter = FILTER_ALIASES.get(clean_key)
        if not resolved_filter:
            raise BadRequestException(f"Invalid filter. Allowed values: {', '.join(sorted(ALLOWED_FILTERS))}")
        if resolved_filter == "custom" and not resolved_start and not resolved_end:
            raise BadRequestException("start_date and end_date are required when filter is 'custom'")
    else:
        resolved_filter = "7_days"

    dashboard_data = await PharmacyService(db).get_dashboard_summary(
        time_filter=resolved_filter,
        start_date=resolved_start,
        end_date=resolved_end,
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


@router.get("/medicines/bulk-template")
async def download_bulk_template(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "create")),
):
    stream = await PharmacyService(db).generate_medicine_bulk_template()
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=medicine_bulk_template.xlsx"}
    )


@router.post("/medicines/bulk-upload", status_code=201)
async def upload_medicines_bulk(
    db: DbSession,
    current_user: CurrentUser,
    file: UploadFile = File(...),
    _: User = Depends(require_permission("pharmacy", "create")),
):
    if not file.filename.endswith(".xlsx"):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file format. Only .xlsx files are supported."
        )

    result = await PharmacyService(db).import_medicines_from_excel(file, current_user.id)
    return APIResponse(message="Medicine bulk upload processed", data=result)


@router.get("/medicines/export")
async def export_medicines_list(
    db: DbSession,
    current_user: CurrentUser,
    format: MedicineExportFormat = Query(MedicineExportFormat.EXCEL),
    _: User = Depends(require_permission("pharmacy", "read")),
):
    data, media_type = await PharmacyService(db).export_medicines(format.value)

    if format == MedicineExportFormat.EXCEL:
        return StreamingResponse(
            data,
            media_type=media_type,
            headers={"Content-Disposition": "attachment; filename=medicines_export.xlsx"}
        )
    else:
        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": "attachment; filename=medicines_export.pdf"}
        )


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
    from app.core.constants import UserRole
    from app.core.exceptions import NotFoundException
    from app.repositories.nurse_repository import NurseRepository
    from app.repositories.doctor_repository import DoctorRepository

    role_name = current_user.role.name.lower() if current_user.role else ""

    doctor_id = None
    department_id = None
    assigned_patient_ids = None

    if role_name == "nurse":
        nurse = await NurseRepository(db).get_by_user_id(current_user.id)
        if not nurse:
            raise NotFoundException("Nurse profile not found")
        department_id = None

        # Fetch active assigned patients for this nurse
        from app.models.nurse_model import NursePatientAssignment
        from sqlalchemy import select
        res = await db.execute(
            select(NursePatientAssignment.patient_id)
            .where(
                NursePatientAssignment.nurse_id == nurse.id,
                NursePatientAssignment.status == "Active"
            )
        )
        assigned_patient_ids = list(res.scalars().all())
    elif role_name == UserRole.DOCTOR:
        doctor = await DoctorRepository(db).get_by_user_id(current_user.id)
        doctor_id = doctor.id if doctor else None

    result = await PharmacyService(db).list_prescriptions(
        page=page,
        size=size,
        status=status,
        doctor_id=doctor_id,
        patient_id=patient_id,
        appointment_id=appointment_id,
        department_id=department_id,
        assigned_patient_ids=assigned_patient_ids,
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



@router.post("/prescriptions/{prescription_id}/dispense", response_model=APIResponse[dict])
async def dispense_prescription(
    prescription_id: int,
    db: DbSession,
    current_user: CurrentUser,
    data: PrescriptionDispenseRequest,
    _: User = Depends(require_permission("pharmacy", "update")),
):
    result = await PharmacyService(db).dispense_prescription(
        prescription_id=prescription_id,
        user_id=current_user.id,
        data=data,
    )
    return APIResponse(message="Prescription dispensed and invoice generated successfully", data=result)


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
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Page size"),
    status: Optional[str] = Query(None, description="Filter by invoice status (e.g. PAID, PENDING, CANCELLED)"),
    patient_name: Optional[str] = Query(None, description="Filter by patient name (case-insensitive search)"),
    invoice_date: Optional[date] = Query(None, alias="date", description="Filter by invoice date (YYYY-MM-DD)"),
    _: User = Depends(require_permission("pharmacy", "read")),
):
    result = await PharmacyService(db).list_invoices(
        page=page,
        size=size,
        status=status,
        patient_name=patient_name,
        invoice_date=invoice_date,
    )
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


@router.post("/invoices/{invoice_id}/return", response_model=APIResponse[PharmacyReturnResponse])
async def return_pharmacy_invoice_items(
    invoice_id: int,
    data: PharmacyReturnCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "update")),
):
    return_obj = await PharmacyService(db).process_return(
        invoice_id=invoice_id,
        data=data,
        user_id=current_user.id,
    )
    return APIResponse(message="Medicine return processed and inventory restocked successfully", data=return_obj)


@router.get("/returns", response_model=APIResponse[PaginatedResult[PharmacyReturnResponse]])
async def list_pharmacy_returns(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    _: User = Depends(require_permission("pharmacy", "read")),
):
    result = await PharmacyService(db).list_returns(page=page, size=size)
    return APIResponse(message="Pharmacy returns retrieved", data=result)


@router.get("/returns/{return_id}", response_model=APIResponse[PharmacyReturnResponse])
async def get_pharmacy_return(
    return_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "read")),
):
    return_obj = await PharmacyService(db).get_return_by_id(return_id)
    return APIResponse(message="Pharmacy return retrieved", data=return_obj)


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
class SupplierExportFormat(str, Enum):
    EXCEL = "excel"
    PDF = "pdf"


@router.get("/suppliers/bulk-template")
async def download_bulk_template(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "read")),
):
    stream = await PharmacyService(db).generate_supplier_bulk_template()
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=suppliers_bulk_template.xlsx"}
    )


@router.post("/suppliers/bulk-upload", status_code=201)
async def upload_suppliers_bulk(
    db: DbSession,
    current_user: CurrentUser,
    file: UploadFile = File(...),
    _: User = Depends(require_permission("pharmacy", "create")),
):
    if not file.filename.endswith(".xlsx"):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file format. Only .xlsx files are supported."
        )
        
    result = await PharmacyService(db).import_suppliers_from_excel(file, current_user.id)
    return APIResponse(message="Suppliers bulk upload processed", data=result)


@router.get("/suppliers/export")
async def export_suppliers(
    db: DbSession,
    current_user: CurrentUser,
    format: SupplierExportFormat = Query(SupplierExportFormat.EXCEL),
    _: User = Depends(require_permission("pharmacy", "read")),
):
    data, media_type = await PharmacyService(db).export_suppliers(format.value)
    
    if format == SupplierExportFormat.EXCEL:
        return StreamingResponse(
            data,
            media_type=media_type,
            headers={"Content-Disposition": "attachment; filename=suppliers_export.xlsx"}
        )
    else:
        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": "attachment; filename=suppliers_export.pdf"}
        )


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
    days: int = Query(
        30,
        ge=1,
        description="Number of days ahead to check for expiring inventory items (must be a positive integer, e.g., 7, 30, 90)",
        openapi_examples={
            "7_days": {"summary": "7 Days (1 Week)", "value": 7},
            "30_days": {"summary": "30 Days (1 Month)", "value": 30},
            "90_days": {"summary": "90 Days (3 Months)", "value": 90},
        },
    ),
    _: User = Depends(require_permission("pharmacy", "read")),
):
    alerts = await PharmacyService(db).get_expiry_alerts(days=days)
    return APIResponse(message="Expiry alerts", data=alerts)


@router.get("/sales-reports", response_model=APIResponse[SalesReport])
async def sales_report(
    db: DbSession,
    current_user: CurrentUser,
    period: str = "all",
    _: User = Depends(require_permission("pharmacy", "read")),
):
    report = await PharmacyService(db).get_sales_report(period=period)
    return APIResponse(message="Sales report", data=report)



@router.get("/inventory/overview", response_model=APIResponse[PharmacyInventoryOverviewResponse])
async def get_inventory_overview(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("pharmacy", "read")),
):
    overview = await PharmacyService(db).get_inventory_overview()
    return APIResponse(message="Pharmacy inventory overview retrieved", data=overview)
