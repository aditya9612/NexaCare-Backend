from datetime import datetime
from typing import List, Optional

from pydantic import Field

from app.schemas.common_schema import BaseSchema


class LabTestCreate(BaseSchema):
    test_name: str
    category: str
    description: str | None = None
    price: float = Field(0.0, ge=0)
    sample_type: str = "blood"
    turnaround_hours: int = Field(24, ge=1)
    normal_range: str | None = None
    department_id: int


class LabTestUpdate(BaseSchema):
    test_name: str | None = None
    category: str | None = None
    description: str | None = None
    price: float | None = Field(None, ge=0)
    sample_type: str | None = None
    turnaround_hours: int | None = Field(None, ge=1)
    normal_range: str | None = None
    is_active: bool | None = None
    department_id: int


class LabTestResponse(BaseSchema):
    id: int
    test_code: str
    test_name: str
    category: str
    description: str | None
    price: float
    sample_type: str
    turnaround_hours: int
    normal_range: str | None
    is_active: bool
    department_id: int | None
    created_at: datetime
    updated_at: datetime


class TestOrderCreate(BaseSchema):
    patient_id: int
    doctor_id: int
    lab_test_id: int
    appointment_id: int
    priority: str = "normal"
    notes: str | None = None

class TestOrderUpdate(BaseSchema):
    patient_id: int | None = None
    doctor_id: int | None = None
    lab_test_id: int | None = None
    appointment_id: int | None = None
    status: str | None = None
    priority: str | None = None
    notes: str | None = None

class TestOrderUpdate(BaseSchema):
    patient_id: int | None = None
    doctor_id: int | None = None
    lab_test_id: int | None = None
    appointment_id: int | None = None
    priority: str | None = None
    notes: str | None = None
    status: str | None = None


class TestOrderResponse(BaseSchema):
    id: int
    order_number: str
    patient_id: int
    doctor_id: int | None
    lab_test_id: int
    appointment_id: int | None
    status: str
    priority: str
    notes: str | None
    ordered_at: datetime
    completed_at: datetime | None
    lab_test: LabTestResponse | None = None
    created_at: datetime


class SampleCreate(BaseSchema):
    test_order_id: int
    sample_type: str
    collection_date: datetime | None = None
    status: str = "pending"
    volume: float | None = None
    notes: str | None = None

class SampleUpdate(BaseSchema):
    sample_type: str | None = None
    collection_date: datetime | None = None
    status: str | None = None
    volume: float | None = None
    notes: str | None = None

class SampleResponse(BaseSchema):
    id: int
    test_order_id: int
    sample_code: str
    sample_type: str
    collected_at: datetime | None
    collection_date: datetime | None
    collected_by: int | None
    status: str
    volume: float | None
    notes: str | None
    created_at: datetime


class TestResultCreate(BaseSchema):
    test_order_id: int
    parameter_name: str
    result_value: str
    unit: str | None = None
    normal_range: str | None = None
    is_critical: bool = False


class TestResultUpdate(BaseSchema):
    parameter_name: str | None = None
    result_value: str | None = None
    unit: str | None = None
    normal_range: str | None = None
    is_critical: bool | None = None
    status: str | None = None    


class TestResultResponse(BaseSchema):
    id: int
    test_order_id: int
    parameter_name: str
    result_value: str
    unit: str | None
    normal_range: str | None
    is_critical: bool
    status: str
    entered_at: datetime | None
    created_at: datetime


class LabReportCreate(BaseSchema):
    test_order_id: int
    summary: str | None = None


class LabReportApprove(BaseSchema):
    approved: bool = True
    summary: str | None = None


class LabReportResponse(BaseSchema):
    id: int
    test_order_id: int
    report_number: str
    status: str
    summary: str | None
    report_path: str | None
    approved_by: int | None
    approved_at: datetime | None
    generated_at: datetime | None
    created_at: datetime


class CriticalAlert(BaseSchema):
    result_id: int
    test_order_id: int
    order_number: str
    patient_id: int
    parameter_name: str
    result_value: str
    entered_at: datetime | None
