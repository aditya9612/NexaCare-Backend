from typing import Optional
from datetime import date
from pydantic import BaseModel

class ReportPlaceholderResponse(BaseModel):
    message: str = "Not implemented yet"

class DailyRevenueResponse(BaseModel):
    date: str
    billing_revenue: float
    pharmacy_revenue: float
    total_revenue: float

class PatientGenderCount(BaseModel):
    gender: str
    count: int

class PatientAgeCount(BaseModel):
    range: str
    count: int

class PatientStatisticsResponse(BaseModel):
    total_patients: int
    new_patients: int
    active_patients: int
    inactive_patients: int
    gender_distribution: list[PatientGenderCount]
    age_distribution: list[PatientAgeCount]

class AppointmentTrend(BaseModel):
    date: str
    status: str
    count: int

class AppointmentTrendsResponse(BaseModel):
    total_appointments: int
    trend: list[AppointmentTrend]

class InventoryStatusResponse(BaseModel):
    total_items: int
    active_items: int
    inactive_items: int
    low_stock_items: int
    out_of_stock_items: int
    expiring_items: int
    expired_items: int
    reorder_alerts: int

class PharmacySalesResponse(BaseModel):
    total_sales: float
    total_invoices: int
    average_invoice_value: float

class PharmacyInventoryResponse(BaseModel):
    total_medicines: int
    active_medicines: int
    inactive_medicines: int
    low_stock_medicines: int
    out_of_stock_medicines: int
    total_stock_quantity: int

class PharmacyExpiryResponse(BaseModel):
    total_medicines: int
    expired_medicines: int
    expiring_30_days: int
    expiring_60_days: int
    expiring_90_days: int

class LabTestSummaryResponse(BaseModel):
    total_tests: int
    pending_tests: int
    in_progress_tests: int
    completed_tests: int
    cancelled_tests: int

class LabOrderedValueResponse(BaseModel):
    total_ordered_value: float
    total_tests_ordered: int
    average_test_value: float

class LabTechnicianWorkloadResponse(BaseModel):
    assignment_supported: bool = False
    message: str = "Technician assignment is not natively supported by the schema. Lab operates on a shared-pool basis."
    unassigned_pending_tests: int
    unassigned_in_progress_tests: int
    unassigned_completed_tests: int

class LabTurnaroundTimeResponse(BaseModel):
    total_completed_tests: int
    average_turnaround_minutes: int
    minimum_turnaround_minutes: int
    maximum_turnaround_minutes: int

from datetime import date
from typing import Optional
from enum import Enum

class FinancialPeriod(str, Enum):
    DAILY = "daily"
    MONTHLY = "monthly"
    YEARLY = "yearly"
    CUSTOM = "custom"

class UnifiedAccountantFinancialResponse(BaseModel):
    period: FinancialPeriod
    start_date: date
    end_date: date
    total_billed_amount: float
    total_collected_amount: float
    total_expense_amount: float
    net_cash_flow: float
    total_bills: int
    total_payments: int
    total_expenses: int

class AccountantRevenueVsExpenseResponse(BaseModel):
    total_billed_amount: float
    total_collected_amount: float
    total_expense_amount: float
    net_cash_flow: float
    collection_rate_percent: float
    expense_ratio_percent: float

class DepartmentFinancialStats(BaseModel):
    department_name: str
    revenue: float
    patient_count: int
    appointment_count: int

class AccountantDepartmentWiseResponse(BaseModel):
    total_revenue: float
    departments: list[DepartmentFinancialStats]

class ReportFormat(str, Enum):
    JSON = "json"
    PDF = "pdf"
    CSV = "csv"

from datetime import datetime
from typing import Any
from pydantic import Field, ConfigDict

class CollectionSection(BaseModel):
    title: str
    rows: list[dict[str, Any]]

class ExportPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    generated_at: datetime
    filters: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    main_table_title: str = Field(default='Main Data')
    main_rows: list[dict[str, Any]] = Field(default_factory=list)
    additional_sections: list[CollectionSection] = Field(default_factory=list)

class PharmacyProfitLossResponse(BaseModel):
    total_sales: float = Field(..., description="Total sales from pharmacy invoices")
    total_cost: float = Field(..., description="Total cost from pharmacy purchases")
    gross_profit: float = Field(..., description="Gross profit (sales - cost)")
    invoice_count: int = Field(..., description="Number of invoices generated")
    medicine_count: int = Field(..., description="Total active medicines in inventory")
    generated_at: datetime = Field(default_factory=datetime.now, description="Report generation timestamp")


class LabSummaryResponse(BaseModel):
    period: str = Field(..., description="The period covered (e.g., '2026-07-31' or '2026-07')")
    total_orders: int = Field(..., description="Total test orders placed")
    completed_orders: int = Field(..., description="Number of completed test orders")
    pending_orders: int = Field(..., description="Number of pending test orders")
    total_revenue: float = Field(..., description="Total revenue from orders (sum of test prices)")
    generated_at: datetime = Field(default_factory=datetime.now)

class LabPerformanceResponse(BaseModel):
    total_orders: int = Field(..., description="Total test orders placed")
    completed_orders: int = Field(..., description="Number of completed test orders")
    average_turnaround_hours: float | None = Field(None, description="Average time in hours from order to completion")
    generated_at: datetime = Field(default_factory=datetime.now)

class LabRevenueByTest(BaseModel):
    test_name: str
    order_count: int
    revenue: float

class LabRevenueResponse(BaseModel):
    total_revenue: float = Field(..., description="Total revenue across all tests")
    revenue_by_test: list[LabRevenueByTest] = Field(..., description="Breakdown of revenue by test type")
    generated_at: datetime = Field(default_factory=datetime.now)


class DoctorLabReportItem(BaseModel):
    doctor_name: str
    total_lab_orders: int
    completed_reports: int
    pending_reports: int
    cancelled_reports: int

class DoctorLabReportResponse(BaseModel):
    reports: list[DoctorLabReportItem]
    generated_at: datetime = Field(default_factory=datetime.now)
