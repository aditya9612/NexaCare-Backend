from fastapi.responses import StreamingResponse
from app.services.report_export_service import ReportExportService
from app.schemas.report_schema import ExportPayload, ReportFormat
from app.core.report_config import REPORT_CONTENT_TYPES


def export_response(payload: ExportPayload, format: ReportFormat, download: bool, report_name: str, original_result: any):
    if format == ReportFormat.JSON:
        return original_result

    if format == ReportFormat.PDF:
        stream = ReportExportService.export_pdf(payload)
        ext = "pdf"
    elif format == ReportFormat.CSV:
        stream = ReportExportService.export_csv(payload)
        ext = "csv"
    else:
        return original_result

    filename = ReportExportService.generate_export_filename(report_name, ext, payload.generated_at)
    content_type = REPORT_CONTENT_TYPES.get(format, "application/octet-stream")

    headers = {}
    if download:
        headers["Content-Disposition"] = f"attachment; filename={filename}"
    else:
        headers["Content-Disposition"] = f"inline; filename={filename}"
    
    headers["Access-Control-Expose-Headers"] = "Content-Disposition"

    return StreamingResponse(stream, media_type=content_type, headers=headers)


from app.schemas.report_schema import ReportFormat

from fastapi import Query, HTTPException
import re
from datetime import datetime, date
from app.schemas.report_schema import FinancialPeriod
from fastapi import APIRouter, Depends
from app.core.dependencies import DbSession, CurrentUser
from app.schemas.report_schema import (
    DoctorLabReportResponse,
    LabSummaryResponse, LabPerformanceResponse, LabRevenueResponse, 
    ReportPlaceholderResponse,
    DailyRevenueResponse,
    PatientStatisticsResponse,
    AppointmentTrendsResponse,
    InventoryStatusResponse,
    PharmacySalesResponse,
    PharmacyInventoryResponse,
    PharmacyExpiryResponse, PharmacyProfitLossResponse,
    UnifiedAccountantFinancialResponse,
    AccountantRevenueVsExpenseResponse,
    AccountantDepartmentWiseResponse,
)
from app.services.report_service import ReportService

router = APIRouter()

# ---------------------------------------------------------
# HOSPITAL ADMIN REPORTS
# ---------------------------------------------------------


@router.get("/admin/daily-revenue", response_model=DailyRevenueResponse)
async def get_admin_daily_revenue(db: DbSession, current_user: CurrentUser, format: ReportFormat = Query(ReportFormat.JSON), download: bool = Query(False)):
    data = await ReportService(db).get_daily_revenue(datetime.today(), datetime.today())
    return export_response(
        ReportService.build_export_payload("Daily Revenue", data),
        format,
        download,
        "daily-revenue",
        data,
    )


@router.get("/admin/patient-statistics", response_model=PatientStatisticsResponse)
async def get_admin_patient_statistics(
    db: DbSession, current_user: CurrentUser, format: ReportFormat = Query(ReportFormat.JSON), download: bool = Query(False)
):
    data = await ReportService(db).get_patient_statistics()
    return export_response(ReportService.build_export_payload("Patient Statistics", data), format, download, "patient-statistics", data)


@router.get("/admin/appointment-trends", response_model=AppointmentTrendsResponse)
async def get_admin_appointment_trends(
    db: DbSession, current_user: CurrentUser, format: ReportFormat = Query(ReportFormat.JSON), download: bool = Query(False)
):
    data = await ReportService(db).get_appointment_trends()
    return export_response(ReportService.build_export_payload("Appointment Trends", data), format, download, "appointment-trends", data)


@router.get("/admin/inventory-status", response_model=InventoryStatusResponse)
async def get_admin_inventory_status(db: DbSession, current_user: CurrentUser, format: ReportFormat = Query(ReportFormat.JSON), download: bool = Query(False)):
    data = await ReportService(db).get_inventory_status()
    return export_response(ReportService.build_export_payload("Inventory Status", data), format, download, "inventory-status", data)


# ---------------------------------------------------------
# ACCOUNTANT REPORTS
# ---------------------------------------------------------

def validate_period_filters(period: FinancialPeriod, date_filter: date | None, month_filter: str | None, year_filter: str | None) -> tuple[date | None, str | None, str | None]:
    if period == FinancialPeriod.DAILY:
        if month_filter or year_filter:
            raise HTTPException(status_code=422, detail="For period=daily only the 'date' parameter may be supplied.")
    elif period == FinancialPeriod.MONTHLY:
        if date_filter or year_filter:
            raise HTTPException(status_code=422, detail="For period=monthly use only month=YYYY-MM.")
        if month_filter:
            if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", month_filter):
                raise HTTPException(status_code=422, detail="Invalid month format or value. For period=monthly use a valid month=YYYY-MM between 01 and 12.")
    elif period == FinancialPeriod.YEARLY:
        if date_filter or month_filter:
            raise HTTPException(status_code=422, detail="For period=yearly use only year=YYYY.")
        if year_filter:
            if not re.match(r"^\d{4}$", year_filter):
                raise HTTPException(status_code=422, detail="Invalid year format. For period=yearly use only year=YYYY.")
            
    return date_filter, month_filter, year_filter


@router.get(
    "/accountant",
    response_model=UnifiedAccountantFinancialResponse,
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {},
                "application/pdf": {"schema": {"type": "string", "format": "binary"}},
                "text/csv": {"schema": {"type": "string"}},
            }
        }
    }
)
async def get_accountant_financial_report(
    db: DbSession, 
    current_user: CurrentUser, 
    period: FinancialPeriod = Query(FinancialPeriod.DAILY, description="Report period (daily, monthly, yearly). Default is daily.", examples={"default": {"summary": "Example", "value": "daily"}}),
    date_filter: date | None = Query(None, alias="date", description="YYYY-MM-DD for daily reports. Defaults to current date if omitted.", examples={"default": {"summary": "Example", "value": "2026-07-31"}}),
    month_filter: str | None = Query(None, alias="month", description="YYYY-MM for monthly reports. Defaults to current month if omitted.", examples={"default": {"summary": "Example", "value": "2026-07"}}),
    year_filter: str | None = Query(None, alias="year", description="YYYY for yearly reports. Defaults to current year if omitted.", examples={"default": {"summary": "Example", "value": "2026"}}),
    format: ReportFormat = Query(ReportFormat.JSON, description="Output format (json, pdf, csv). Default is json.", examples={"default": {"summary": "Example", "value": "json"}}), 
    download: bool = Query(False, description="Set to true to force download as an attachment. Default is false.", examples={"default": {"summary": "Example", "value": False}})
):
    target_date, target_month, target_year = validate_period_filters(
        period, date_filter, month_filter, year_filter
    )
    
    data = await ReportService(db).get_unified_accountant_financial_report(
        period=period,
        target_date=target_date,
        month=target_month,
        year=target_year
    )
    
    report_title = f"Accountant {period.value.title()}"
    report_filename = f"accountant-{period.value}"
    
    return export_response(
        ReportService.build_export_payload(report_title, data),
        format,
        download,
        report_filename,
        data
    )


@router.get(
    "/accountant/revenue-vs-expense",
    response_model=AccountantRevenueVsExpenseResponse,
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {},
                "application/pdf": {"schema": {"type": "string", "format": "binary"}},
                "text/csv": {"schema": {"type": "string"}},
            }
        }
    }
)
async def get_accountant_revenue_vs_expense(
    db: DbSession, 
    current_user: CurrentUser, 
    start_date: date | None = Query(None, description="Start date for the report (YYYY-MM-DD)."),
    end_date: date | None = Query(None, description="End date for the report (YYYY-MM-DD)."),
    format: ReportFormat = Query(ReportFormat.JSON, description="Output format (json, pdf, csv). Default is json.", examples={"default": {"summary": "Example", "value": "json"}}), 
    download: bool = Query(False, description="Set to true to force download as an attachment. Default is false.", examples={"default": {"summary": "Example", "value": False}})
):
    data = await ReportService(db).get_accountant_revenue_vs_expense(start_date, end_date)
    return export_response(
        ReportService.build_export_payload("Revenue vs Expense", data),
        format,
        download,
        "revenue-vs-expense",
        data,
    )


@router.get(
    "/accountant/department-wise",
    response_model=AccountantDepartmentWiseResponse,
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {},
                "application/pdf": {"schema": {"type": "string", "format": "binary"}},
                "text/csv": {"schema": {"type": "string"}},
            }
        }
    }
)
async def get_accountant_department_wise(
    db: DbSession, 
    current_user: CurrentUser,
    start_date: date | None = Query(None, description="Start date for the report (YYYY-MM-DD)."),
    end_date: date | None = Query(None, description="End date for the report (YYYY-MM-DD)."),
    format: ReportFormat = Query(ReportFormat.JSON, description="Output format (json, pdf, csv). Default is json.", examples={"default": {"summary": "Example", "value": "json"}}), 
    download: bool = Query(False, description="Set to true to force download as an attachment. Default is false.", examples={"default": {"summary": "Example", "value": False}})
):
    data = await ReportService(db).get_accountant_department_wise(start_date, end_date)
    return export_response(
        ReportService.build_export_payload("Department-wise Financials", data),
        format,
        download,
        "department-wise",
        data,
    )


# ---------------------------------------------------------
# PHARMACY REPORTS
# ---------------------------------------------------------


import calendar

@router.get("/pharmacy/sales", response_model=PharmacySalesResponse)
async def get_pharmacy_sales(
    db: DbSession, 
    current_user: CurrentUser, 
    period: str | None = Query(None, description="daily | monthly | yearly"),
    start_date: date | None = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: date | None = Query(None, description="End date (YYYY-MM-DD)"),
    format: ReportFormat = Query(ReportFormat.JSON), 
    download: bool = Query(False)
):
    if start_date and end_date:
        if start_date > end_date:
            raise HTTPException(status_code=400, detail="start_date cannot be greater than end_date")
        s_date = start_date
        e_date = end_date
    else:
        today = date.today()
        if period == "monthly":
            s_date = today.replace(day=1)
            e_date = today.replace(day=calendar.monthrange(today.year, today.month)[1])
        elif period == "yearly":
            s_date = today.replace(month=1, day=1)
            e_date = today.replace(month=12, day=31)
        elif period == "daily" or period is None:
            s_date = today
            e_date = today
        else:
            raise HTTPException(status_code=400, detail="Invalid period value. Must be daily, monthly, or yearly.")

    data = await ReportService(db).get_pharmacy_sales(s_date, e_date)
    return export_response(ReportService.build_export_payload("Pharmacy Sales", data), format, download, "pharmacy-sales", data)


@router.get("/pharmacy/inventory", response_model=PharmacyInventoryResponse)
async def get_pharmacy_inventory(db: DbSession, current_user: CurrentUser, format: ReportFormat = Query(ReportFormat.JSON), download: bool = Query(False)):
    data = await ReportService(db).get_pharmacy_inventory()
    return export_response(ReportService.build_export_payload("Pharmacy Inventory", data), format, download, "pharmacy-inventory", data)


@router.get("/pharmacy/expiry", response_model=PharmacyExpiryResponse)
async def get_pharmacy_expiry(db: DbSession, current_user: CurrentUser, format: ReportFormat = Query(ReportFormat.JSON), download: bool = Query(False)):
    data = await ReportService(db).get_pharmacy_expiry()
    return export_response(ReportService.build_export_payload("Pharmacy Expiry", data), format, download, "pharmacy-expiry", data)


@router.get(
    "/pharmacy/profit-loss",
    response_model=PharmacyProfitLossResponse,
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {},
                "application/pdf": {"schema": {"type": "string", "format": "binary"}},
                "text/csv": {"schema": {"type": "string"}},
            }
        }
    }
)
async def get_pharmacy_profit_loss(
    db: DbSession,
    current_user: CurrentUser,
    start_date: date | None = Query(None, description="Start date for the report (YYYY-MM-DD)."),
    end_date: date | None = Query(None, description="End date for the report (YYYY-MM-DD)."),
    format: ReportFormat = Query(ReportFormat.JSON, description="Output format (json, pdf, csv). Default is json."),
    download: bool = Query(False, description="Set to true to force download as an attachment. Default is false.")
):
    data = await ReportService(db).get_pharmacy_profit_loss(start_date, end_date)
    return export_response(
        ReportService.build_export_payload("Pharmacy Profit and Loss", data),
        format,
        download,
        "pharmacy-profit-loss",
        data,
    )


# ---------------------------------------------------------
# LAB REPORTS
# ---------------------------------------------------------


@router.get(
    "/lab/daily",
    response_model=LabSummaryResponse,
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {},
                "application/pdf": {"schema": {"type": "string", "format": "binary"}},
                "text/csv": {"schema": {"type": "string"}},
            }
        }
    }
)
async def get_lab_daily(
    db: DbSession, 
    current_user: CurrentUser,
    date_filter: date | None = Query(None, alias="date", description="YYYY-MM-DD"),
    format: ReportFormat = Query(ReportFormat.JSON, description="Output format"),
    download: bool = Query(False, description="Set to true to force download")
):
    data = await ReportService(db).get_lab_daily(date_filter)
    return export_response(
        ReportService.build_export_payload("Lab Daily", data),
        format,
        download,
        "lab-daily",
        data,
    )


@router.get(
    "/lab/monthly",
    response_model=LabSummaryResponse,
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {},
                "application/pdf": {"schema": {"type": "string", "format": "binary"}},
                "text/csv": {"schema": {"type": "string"}},
            }
        }
    }
)
async def get_lab_monthly(
    db: DbSession, 
    current_user: CurrentUser,
    month: str | None = Query(None, description="MM"),
    year: str | None = Query(None, description="YYYY"),
    format: ReportFormat = Query(ReportFormat.JSON, description="Output format"),
    download: bool = Query(False, description="Set to true to force download")
):
    data = await ReportService(db).get_lab_monthly(month, year)
    return export_response(
        ReportService.build_export_payload("Lab Monthly", data),
        format,
        download,
        "lab-monthly",
        data,
    )


@router.get(
    "/lab/performance",
    response_model=LabPerformanceResponse,
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {},
                "application/pdf": {"schema": {"type": "string", "format": "binary"}},
                "text/csv": {"schema": {"type": "string"}},
            }
        }
    }
)
async def get_lab_performance(
    db: DbSession, 
    current_user: CurrentUser,
    start_date: date | None = Query(None, description="YYYY-MM-DD"),
    end_date: date | None = Query(None, description="YYYY-MM-DD"),
    format: ReportFormat = Query(ReportFormat.JSON, description="Output format"),
    download: bool = Query(False, description="Set to true to force download")
):
    data = await ReportService(db).get_lab_performance(start_date, end_date)
    return export_response(
        ReportService.build_export_payload("Lab Performance", data),
        format,
        download,
        "lab-performance",
        data,
    )


@router.get(
    "/lab/revenue",
    response_model=LabRevenueResponse,
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {},
                "application/pdf": {"schema": {"type": "string", "format": "binary"}},
                "text/csv": {"schema": {"type": "string"}},
            }
        }
    }
)
async def get_lab_revenue(
    db: DbSession, 
    current_user: CurrentUser,
    start_date: date | None = Query(None, description="YYYY-MM-DD"),
    end_date: date | None = Query(None, description="YYYY-MM-DD"),
    format: ReportFormat = Query(ReportFormat.JSON, description="Output format"),
    download: bool = Query(False, description="Set to true to force download")
):
    data = await ReportService(db).get_lab_revenue(start_date, end_date)
    return export_response(
        ReportService.build_export_payload("Lab Revenue", data),
        format,
        download,
        "lab-revenue",
        data,
    )


# ---------------------------------------------------------
# DOCTOR REPORTS
# ---------------------------------------------------------


@router.get(
    "/doctor/lab-reports",
    response_model=DoctorLabReportResponse,
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {},
                "application/pdf": {"schema": {"type": "string", "format": "binary"}},
                "text/csv": {"schema": {"type": "string"}},
            }
        }
    }
)
async def get_doctor_lab_reports(
    db: DbSession,
    current_user: CurrentUser,
    start_date: date | None = Query(None, description="YYYY-MM-DD"),
    end_date: date | None = Query(None, description="YYYY-MM-DD"),
    format: ReportFormat = Query(ReportFormat.JSON, description="Output format"),
    download: bool = Query(False, description="Set to true to force download")
):
    data = await ReportService(db).get_doctor_lab_reports(start_date, end_date)
    return export_response(
        ReportService.build_export_payload("Doctor Lab Reports", data),
        format,
        download,
        "doctor-lab-reports",
        data,
    )
