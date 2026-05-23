from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.common_schema import APIResponse, MessageResponse
from app.schemas.lab_schema import (
    CriticalAlert,
    LabReportApprove,
    LabReportCreate,
    LabReportResponse,
    LabTestCreate,
    LabTestResponse,
    LabTestUpdate,
    SampleCreate,
    SampleResponse,
    TestOrderCreate,
    TestOrderResponse,
    TestResultCreate,
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
    service = LabService(db)
    if q:
        result = await service.search_tests(q, page=page, size=size)
    else:
        result = await service.list_tests(
            page=page, size=size, sort_by=sort_by, sort_order=sort_order, category=category
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
    result = await LabService(db).list_orders(page=page, size=size, status=status, patient_id=patient_id)
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


# --- Samples ---
@router.post("/samples", response_model=APIResponse[SampleResponse], status_code=201)
async def collect_sample(
    data: SampleCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("lab", "create")),
):
    sample = await LabService(db).collect_sample(data, current_user.id)
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
    result = await LabService(db).list_samples(page=page, size=size, status=status)
    return APIResponse(message="Samples retrieved", data=result)


# --- Results ---
@router.post("/results", response_model=APIResponse[TestResultResponse], status_code=201)
async def enter_test_result(
    data: TestResultCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("lab", "create")),
):
    result = await LabService(db).enter_result(data, current_user.id)
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
        page=page, size=size, test_order_id=test_order_id, is_critical=is_critical
    )
    return APIResponse(message="Test results retrieved", data=result)


# --- Reports ---
@router.post("/reports", response_model=APIResponse[LabReportResponse], status_code=201)
async def create_lab_report(
    data: LabReportCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("lab", "create")),
):
    report = await LabService(db).create_report(data, current_user.id)
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
    result = await LabService(db).list_reports(page=page, size=size, status=status)
    return APIResponse(message="Lab reports retrieved", data=result)


@router.put("/reports/{report_id}/approve", response_model=APIResponse[LabReportResponse])
async def approve_lab_report(
    report_id: int,
    data: LabReportApprove,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("lab", "approve")),
):
    report = await LabService(db).approve_report(report_id, data, current_user.id)
    return APIResponse(message="Lab report processed", data=report)


@router.get("/reports/{report_id}/download")
async def download_lab_report(
    report_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("lab", "export")),
):
    from app.repositories.lab_repository import LabReportRepository
    report = await LabReportRepository(db).get_by_id(report_id)
    if not report or not report.report_path:
        from app.core.exceptions import NotFoundException
        raise NotFoundException("Report file not found")
    return FileResponse(report.report_path, media_type="text/html", filename=f"report_{report_id}.html")


# --- Analytics ---
@router.get("/pending-tests", response_model=APIResponse[PaginatedResult[TestOrderResponse]])
async def pending_tests(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    _: User = Depends(require_permission("lab", "read")),
):
    result = await LabService(db).get_pending_tests(page=page, size=size)
    return APIResponse(message="Pending tests", data=result)


@router.get("/completed-tests", response_model=APIResponse[PaginatedResult[TestOrderResponse]])
async def completed_tests(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    _: User = Depends(require_permission("lab", "read")),
):
    result = await LabService(db).get_completed_tests(page=page, size=size)
    return APIResponse(message="Completed tests", data=result)


@router.get("/critical-alerts", response_model=APIResponse[list[CriticalAlert]])
async def critical_alerts(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("lab", "read")),
):
    alerts = await LabService(db).get_critical_alerts()
    return APIResponse(message="Critical alerts", data=alerts)
