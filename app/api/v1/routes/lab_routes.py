from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.common_schema import APIResponse, MessageResponse
from app.schemas.lab_schema import (
    CriticalAlert,
    LabReportApprove,
    RejectLabReportRequest,
    LabReportCreate,
    LabReportResponse,
    LabTestCreate,
    LabTestResponse,
    LabTestUpdate,
    SampleCreate,
    SampleUpdate,
    SampleResponse,
    TestOrderCreate,
    TestOrderResponse,
    TestOrderUpdate,
    TestResultCreate,
    TestResultUpdate,
    TestResultResponse,
)
from app.services.lab_service import LabService
from app.utils.pagination import PaginatedResult

router = APIRouter()


# --- Lab Test Catalog ---
@router.post("/tests", response_model=APIResponse[LabTestResponse], status_code=201)
async def create_lab_test(
    data: LabTestCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("lab", "create")),
):
    test = await LabService(db).create_test(data, current_user.id)
    return APIResponse(message="Lab test created", data=test)


@router.get("/tests", response_model=APIResponse[PaginatedResult[LabTestResponse]])
async def list_lab_tests(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    category: str | None = None,
    q: str | None = None,
    _: User = Depends(require_permission("lab", "read")),
):
    from app.repositories.doctor_repository import DoctorRepository
    doctor = await DoctorRepository(db).get_by_user_id(current_user.id)
    doctor_id = doctor.id if doctor else None

    service = LabService(db)
    if q:
        result = await service.search_tests(q, page=page, size=size, doctor_id=doctor_id, current_user=current_user)
    else:
        result = await service.list_tests(
            page=page, size=size, sort_by=sort_by, sort_order=sort_order, category=category, doctor_id=doctor_id, current_user=current_user
        )
    return APIResponse(message="Lab tests retrieved", data=result)


@router.get("/tests/{test_id}", response_model=APIResponse[LabTestResponse])
async def get_lab_test(
    test_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("lab", "read")),
):
    test = await LabService(db).get_test(test_id)
    return APIResponse(message="Lab test retrieved", data=test)


@router.put("/tests/{test_id}", response_model=APIResponse[LabTestResponse])
async def update_lab_test(
    test_id: int,
    data: LabTestUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("lab", "update")),
):
    test = await LabService(db).update_test(test_id, data, current_user.id)
    return APIResponse(message="Lab test updated", data=test)


@router.delete("/tests/{test_id}", response_model=APIResponse[MessageResponse])
async def delete_lab_test(
    test_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("lab", "delete")),
):
    await LabService(db).delete_test(test_id, current_user.id)
    return APIResponse(message="Lab test deleted", data=MessageResponse(message="Soft deleted"))


# --- Test Orders ---
@router.post("/orders", response_model=APIResponse[TestOrderResponse], status_code=201)
async def create_test_order(
    data: TestOrderCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("lab", "create")),
):
    order = await LabService(db).create_order(data, current_user.id)
    return APIResponse(message="Test order created", data=order)


@router.get("/orders", response_model=APIResponse[PaginatedResult[TestOrderResponse]])
async def list_test_orders(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    status: str | None = None,
    patient_id: int | None = None,
    _: User = Depends(require_permission("lab", "read")),
):
    result = await LabService(db).list_orders(
        page=page, size=size, status=status, patient_id=patient_id, current_user=current_user
    )
    return APIResponse(message="Test orders retrieved", data=result)

@router.get("/orders/{order_id}", response_model=APIResponse[TestOrderResponse])
async def get_test_order(
    order_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("lab", "read")),
):
    order = await LabService(db).get_order(order_id)
    return APIResponse(message="Test order retrieved", data=order)


@router.put("/test-orders/{order_id}", response_model=APIResponse[TestOrderResponse])
async def update_test_order_legacy(
    order_id: int,
    data: TestOrderUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("lab", "update")),
):
    order = await LabService(db).update_order(order_id, data, current_user.id)
    return APIResponse(message="Test order updated", data=order)


@router.delete("/test-orders/{order_id}", response_model=APIResponse[MessageResponse])
async def delete_test_order_legacy(
    order_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    await LabService(db).delete_order(order_id, current_user)
    return APIResponse(message="Test order deleted", data=MessageResponse(message="Soft deleted"))


@router.put("/orders/{order_id}", response_model=APIResponse[TestOrderResponse])
async def update_test_order(
    order_id: int,
    data: TestOrderUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("lab", "update")),
):
    order = await LabService(db).update_order(order_id, data, current_user.id)
    return APIResponse(message="Test order updated", data=order)


@router.delete("/orders/{order_id}", response_model=APIResponse[MessageResponse])
async def delete_test_order(
    order_id: int,
    db: DbSession,
    current_user: CurrentUser,
):
    await LabService(db).delete_order(order_id, current_user)
    return APIResponse(message="Test order deleted", data=MessageResponse(message="Soft deleted"))


# --- Samples ---
@router.post("/samples", response_model=APIResponse[SampleResponse], status_code=201)
async def collect_sample(
    data: SampleCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("lab", "create")),
):
    sample = await LabService(db).collect_sample(data, current_user)
    return APIResponse(message="Sample collected", data=sample)


@router.get("/samples", response_model=APIResponse[PaginatedResult[SampleResponse]])
async def list_samples(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    status: str | None = None,
    _: User = Depends(require_permission("lab", "read")),
):
    result = await LabService(db).list_samples(page=page, size=size, status=status, current_user=current_user)
    return APIResponse(message="Samples retrieved", data=result)

@router.get("/samples/{sample_id}", response_model=APIResponse[SampleResponse])
async def get_sample(
    sample_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("lab", "read")),
):
    sample = await LabService(db).get_sample(sample_id)
    return APIResponse(message="Sample retrieved", data=sample)

@router.put("/samples/{sample_id}", response_model=APIResponse[SampleResponse])
async def update_sample(
    sample_id: int,
    data: SampleUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("lab", "update")),
):
    sample = await LabService(db).update_sample(sample_id, data, current_user.id)
    return APIResponse(message="Sample updated", data=sample)

@router.delete("/samples/{sample_id}", response_model=APIResponse[MessageResponse])
async def delete_sample(
    sample_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("lab", "delete")),
):
    await LabService(db).delete_sample(sample_id, current_user.id)
    return APIResponse(
        message="Sample deleted",
        data=MessageResponse(message="Deleted successfully"),
    )        


# --- Results ---
@router.post("/results", response_model=APIResponse[TestResultResponse], status_code=201)
async def enter_test_result(
    db: DbSession,
    current_user: CurrentUser,
    sample_id: int = Form(...),
    parameter_name: str = Form(...),
    result_value: str = Form(...),
    remark: str = Form(...),
    unit: str | None = Form(None),
    normal_range: str | None = Form(None),
    is_critical: bool = Form(False),
    document: UploadFile | None = File(None),
    _: User = Depends(require_permission("lab", "create")),
):
    data = TestResultCreate(
        sample_id=sample_id,
        parameter_name=parameter_name,
        result_value=result_value,
        remark=remark,
        unit=unit,
        normal_range=normal_range,
        is_critical=is_critical,
    )

    result = await LabService(db).enter_result(data, current_user, document)
    return APIResponse(message="Test result entered", data=result)


@router.get("/results", response_model=APIResponse[PaginatedResult[TestResultResponse]])
async def list_test_results(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    test_order_id: int | None = None,
    is_critical: bool | None = None,
    _: User = Depends(require_permission("lab", "read")),
):
    result = await LabService(db).list_results(
        page=page, size=size, test_order_id=test_order_id, is_critical=is_critical, current_user=current_user
    )
    return APIResponse(message="Test results retrieved", data=result)


@router.get("/results/{result_id}", response_model=APIResponse[TestResultResponse])
async def get_test_result(
    result_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("lab", "read")),
):
    result = await LabService(db).get_result(result_id)
    return APIResponse(message="Test result retrieved", data=result)


@router.put("/results/{result_id}", response_model=APIResponse[TestResultResponse])
async def update_test_result(
    result_id: int,
    data: TestResultUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("lab", "update")),
):
    result = await LabService(db).update_result(result_id, data, current_user.id)
    return APIResponse(message="Test result updated", data=result)


# --- Reports ---
@router.post("/reports", response_model=APIResponse[LabReportResponse], status_code=201)
async def create_lab_report(
    data: LabReportCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("lab", "create")),
):
    report = await LabService(db).create_report(data, current_user)
    return APIResponse(message="Lab report created", data=report)


@router.get("/reports", response_model=APIResponse[PaginatedResult[LabReportResponse]])
async def list_lab_reports(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    status: str | None = None,
    _: User = Depends(require_permission("lab", "read")),
):
    result = await LabService(db).list_reports(page=page, size=size, status=status,  current_user=current_user)
    return APIResponse(message="Lab reports retrieved", data=result)


@router.get("/reports/{report_id}", response_model=APIResponse[LabReportResponse])
async def get_lab_report(
    report_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("lab", "read")),
):
    report = await LabService(db).get_report(report_id)
    return APIResponse(message="Lab report retrieved", data=report)    


@router.put("/reports/{report_id}/approve", response_model=APIResponse[LabReportResponse])
async def approve_lab_report(
    report_id: int,
    data: LabReportApprove,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("lab", "approve")),
):
    report = await LabService(db).approve_report(report_id, data,  current_user)
    return APIResponse(message="Lab report processed", data=report)


@router.patch("/reports/{report_id}/reject", response_model=APIResponse[LabReportResponse])
async def reject_lab_report(
    report_id: int,
    data: RejectLabReportRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("lab", "update")),
):
    report = await LabService(db).reject_lab_report(report_id, data, current_user.id)
    return APIResponse(message="Lab report rejected successfully.", data=report)


@router.delete("/reports/{report_id}", response_model=APIResponse[MessageResponse])
async def delete_lab_report(
    report_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("lab", "delete")),
):
    await LabService(db).delete_report(report_id, current_user.id)
    return APIResponse(
        message="Lab report deleted successfully.",
        data=MessageResponse(message="Deleted successfully"),
    )


@router.get("/reports/{report_id}/download")
async def download_lab_report(
    report_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("lab", "export")),
):
    from app.repositories.lab_repository import LabReportRepository
    from app.core.exceptions import NotFoundException
    import os
    
    report = await LabReportRepository(db).get_by_id(report_id)
    if not report:
        raise NotFoundException("Report file not found")

    await LabService(db)._validate_lab_report_access(
        report,
        current_user,
        "download",
    )
        
    def resolve_disk_path(path_str: str | None) -> str | None:
        if not path_str:
            return None
        p = path_str.replace("\\", "/")
        if p.startswith("/"):
            p = p.lstrip("/")
        if p.startswith("uploads/"):
            return os.path.join("app", p)
        return p

    disk_path = resolve_disk_path(report.report_path)
    need_generation = False
    if not disk_path or not report.report_path.endswith(".pdf") or not os.path.exists(disk_path):
        need_generation = True
        
    if need_generation:
        from app.repositories.lab_repository import TestOrderRepository
        from app.models.patient_model import Patient
        from app.models.doctor_model import Doctor
        from app.models.lab_model import TestResult
        from app.utils.pdf_generator import generate_lab_report_html
        from app.utils.helpers import utc_now
        from sqlalchemy import select
        
        order = await TestOrderRepository(db).get_by_id(report.test_order_id)
        if not order:
            raise NotFoundException("Associated test order not found")
            
        patient = await db.get(Patient, order.patient_id)
        doctor = await db.get(Doctor, order.doctor_id) if order.doctor_id else None
        
        result_objs = await db.execute(select(TestResult).where(TestResult.test_order_id == order.id))
        results = list(result_objs.scalars().all())

        columns = ["Parameter", "Result Value", "Unit", "Normal Range", "Is Critical"]
        rows = [
            [
                r.parameter_name,
                r.result_value,
                r.unit or "-",
                r.normal_range or "-",
                "Yes" if r.is_critical else "No"
            ]
            for r in results
        ]

        report_data = {
            "order_number": order.order_number,
            "status": report.status,
            "generated_at": report.approved_at.strftime("%Y-%m-%d %H:%M:%S") if report.approved_at else utc_now().strftime("%Y-%m-%d %H:%M:%S"),
            "patient_name": f"{patient.first_name} {patient.last_name}" if patient else "Unknown",
            "patient_code": patient.patient_code if patient else "Unknown",
            "patient_gender": patient.gender if patient else "Unknown",
            "patient_dob": str(patient.dob) if patient and patient.dob else "Unknown",
            "doctor_name": f"Dr. {doctor.first_name} {doctor.last_name}" if doctor else "",
            "doctor_code": doctor.doctor_code if doctor else "",
            "test_name": order.lab_test.test_name if order.lab_test else "Unknown",
            "test_category": order.lab_test.category if order.lab_test else "Unknown",
            "summary": report.summary or "",
            "columns": columns,
            "rows": rows,
        }

        path = await generate_lab_report_html(
            report.report_number,
            report_data,
        )
        report.report_path = path
        await LabReportRepository(db).update(report)
        disk_path = resolve_disk_path(report.report_path)
        
    if not disk_path or not os.path.exists(disk_path):
        raise NotFoundException("Report PDF file not found")

    return FileResponse(
        disk_path,
        media_type="application/pdf",
        filename=f"lab_report_{report_id}.pdf",
    )

# --- Analytics ---
@router.get("/pending-tests", response_model=APIResponse[PaginatedResult[TestOrderResponse]])
async def pending_tests(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    _: User = Depends(require_permission("lab", "read")),
):
    result = await LabService(db).get_pending_tests(page=page, size=size, current_user=current_user)
    return APIResponse(message="Pending tests", data=result)


@router.get("/completed-tests", response_model=APIResponse[PaginatedResult[TestOrderResponse]])
async def completed_tests(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    _: User = Depends(require_permission("lab", "read")),
):
    result = await LabService(db).get_completed_tests(page=page, size=size, current_user=current_user)
    return APIResponse(message="Completed tests", data=result)


@router.get("/critical-alerts", response_model=APIResponse[list[CriticalAlert]])
async def critical_alerts(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("lab", "read")),
):
    alerts = await LabService(db).get_critical_alerts(current_user=current_user)
    return APIResponse(message="Critical alerts", data=alerts)


@router.get("/analytics", response_model=APIResponse)
async def lab_analytics_alias(
    db: DbSession,
    current_user: CurrentUser,
    time_filter: str = "7_days",
    start_date: str | None = None,
    end_date: str | None = None,
    _: User = Depends(require_permission("lab", "read")),
):
    from app.services.lab_dashboard_service import LabDashboardService
    from datetime import datetime
    s_date = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
    e_date = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None
    data = await LabDashboardService(db).get_analytics_data(
        time_filter=time_filter, start_date=s_date, end_date=e_date
    )
    return APIResponse(message="Lab analytics data retrieved", data=data)

