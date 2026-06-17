from datetime import datetime

from pydantic import Field

from app.schemas.common_schema import BaseSchema


class EcgDataPayload(BaseSchema):
    sampling_hz: int | None = None
    samples: list[float] = Field(default_factory=list)


class TelemetryIngest(BaseSchema):
    recorded_at: datetime
    heart_rate: float | None = None
    systolic_bp: float | None = None
    diastolic_bp: float | None = None
    spo2: float | None = None
    respiratory_rate: float | None = None
    temperature: float | None = None
    ecg_data: EcgDataPayload | None = None


class TelemetryIngestResponse(BaseSchema):
    reading_id: int
    bed_id: int
    patient_id: int | None
    alerts_created: int
    alert_ids: list[int]


class VitalReadingResponse(BaseSchema):
    id: int
    bed_id: int
    bed_name: str | None = None
    patient_id: int | None = None
    patient_name: str | None = None
    device_id: int
    recorded_at: datetime
    heart_rate: float | None = None
    systolic_bp: float | None = None
    diastolic_bp: float | None = None
    spo2: float | None = None
    respiratory_rate: float | None = None
    temperature: float | None = None
    ecg_data: dict | None = None
    has_active_alerts: bool = False


class TelemetryAlertResponse(BaseSchema):
    id: int
    bed_id: int
    bed_name: str | None = None
    patient_id: int | None = None
    patient_name: str | None = None
    vital_reading_id: int
    vital_type: str
    severity: str
    status: str
    message: str
    value: float
    threshold_min: float | None = None
    threshold_max: float | None = None
    acknowledged_by: int | None = None
    acknowledged_at: datetime | None = None
    created_at: datetime


class IcuDeviceCreate(BaseSchema):
    bed_id: int
    device_serial: str
    name: str


class IcuDeviceResponse(BaseSchema):
    id: int
    bed_id: int
    bed_name: str | None = None
    device_serial: str
    name: str
    is_active: bool
    last_seen_at: datetime | None = None
    created_at: datetime


class IcuDeviceCreatedResponse(IcuDeviceResponse):
    api_key: str
