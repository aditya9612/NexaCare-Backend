from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import (
    TelemetryAlertSeverity,
    TelemetryAlertStatus,
    VITAL_THRESHOLDS,
    VitalType,
)
from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.core.security import generate_device_api_key, hash_api_key
from app.models.icu_telemetry_model import IcuDevice, IcuTelemetryAlert, IcuVitalReading
from app.repositories.bed_allocation_repository import BedAllocationRepository
from app.repositories.icu_telemetry_repository import (
    IcuDeviceRepository,
    IcuTelemetryAlertRepository,
    IcuVitalReadingRepository,
)
from app.schemas.icu_telemetry_schema import (
    IcuDeviceCreate,
    IcuDeviceCreatedResponse,
    IcuDeviceResponse,
    TelemetryAlertResponse,
    TelemetryIngest,
    TelemetryIngestResponse,
    VitalReadingResponse,
)
from app.utils.helpers import utc_now


class IcuTelemetryService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.device_repo = IcuDeviceRepository(db)
        self.reading_repo = IcuVitalReadingRepository(db)
        self.alert_repo = IcuTelemetryAlertRepository(db)
        self.bed_repo = BedAllocationRepository(db)

    async def create_device(self, data: IcuDeviceCreate) -> IcuDeviceCreatedResponse:
        bed = await self.bed_repo.get_bed_by_id(data.bed_id, load_patient=False)
        if not bed:
            raise NotFoundException("Bed not found")

        existing = await self.device_repo.get_by_serial(data.device_serial)
        if existing:
            raise ConflictException("Device serial already registered")

        api_key = generate_device_api_key()
        device = IcuDevice(
            bed_id=data.bed_id,
            device_serial=data.device_serial,
            api_key_hash=hash_api_key(api_key),
            name=data.name,
            is_active=True,
        )
        device = await self.device_repo.create(device)
        return IcuDeviceCreatedResponse(
            id=device.id,
            bed_id=device.bed_id,
            bed_name=bed.name,
            device_serial=device.device_serial,
            name=device.name,
            is_active=device.is_active,
            last_seen_at=device.last_seen_at,
            created_at=device.created_at,
            api_key=api_key,
        )

    async def list_devices(self) -> list[IcuDeviceResponse]:
        devices = await self.device_repo.list_all()
        return [self._to_device_response(device) for device in devices]

    async def ingest_telemetry(
        self, device: IcuDevice, data: TelemetryIngest
    ) -> TelemetryIngestResponse:
        bed = await self.bed_repo.get_bed_by_id(device.bed_id, load_patient=True)
        if not bed:
            raise NotFoundException("Bed linked to device not found")

        ecg_payload = None
        if data.ecg_data is not None:
            samples = data.ecg_data.samples or []
            if len(samples) > settings.ICU_TELEMETRY_ECG_MAX_SAMPLES:
                raise BadRequestException(
                    f"ECG samples exceed limit of {settings.ICU_TELEMETRY_ECG_MAX_SAMPLES}"
                )
            ecg_payload = {
                "sampling_hz": data.ecg_data.sampling_hz,
                "samples": samples,
            }

        recorded_at = data.recorded_at
        if recorded_at.tzinfo is not None:
            recorded_at = recorded_at.replace(tzinfo=None)

        reading = IcuVitalReading(
            bed_id=device.bed_id,
            patient_id=bed.patient_id,
            device_id=device.id,
            recorded_at=recorded_at,
            heart_rate=data.heart_rate,
            systolic_bp=data.systolic_bp,
            diastolic_bp=data.diastolic_bp,
            spo2=data.spo2,
            respiratory_rate=data.respiratory_rate,
            temperature=data.temperature,
            ecg_data=ecg_payload,
            created_at=utc_now(),
        )
        reading = await self.reading_repo.create(reading)
        await self.device_repo.update_last_seen(device, utc_now())

        alerts = await self._evaluate_thresholds(reading, bed.patient_id)
        return TelemetryIngestResponse(
            reading_id=reading.id,
            bed_id=reading.bed_id,
            patient_id=reading.patient_id,
            alerts_created=len(alerts),
            alert_ids=[alert.id for alert in alerts],
        )

    async def get_latest_for_bed(self, bed_id: int) -> VitalReadingResponse:
        bed = await self.bed_repo.get_bed_by_id(bed_id, load_patient=True)
        if not bed:
            raise NotFoundException("Bed not found")

        reading = await self.reading_repo.get_latest_for_bed(bed_id)
        if not reading:
            raise NotFoundException("No telemetry readings found for this bed")

        alert_counts = await self.alert_repo.count_active_for_beds([bed_id])
        return self._to_vital_response(reading, alert_counts.get(bed_id, 0) > 0)

    async def get_latest_for_patient(self, patient_id: int) -> VitalReadingResponse:
        reading = await self.reading_repo.get_latest_for_patient(patient_id)
        if not reading:
            raise NotFoundException("No telemetry readings found for this patient")

        alert_counts = await self.alert_repo.count_active_for_beds([reading.bed_id])
        return self._to_vital_response(reading, alert_counts.get(reading.bed_id, 0) > 0)

    async def get_latest_for_icu_beds(self) -> list[VitalReadingResponse]:
        beds = await self.bed_repo.list_icu_beds()
        icu_bed_ids = [bed.id for bed in beds]
        if not icu_bed_ids:
            return []

        readings = await self.reading_repo.get_latest_per_bed(icu_bed_ids)
        alert_counts = await self.alert_repo.count_active_for_beds(icu_bed_ids)
        return [
            self._to_vital_response(reading, alert_counts.get(reading.bed_id, 0) > 0)
            for reading in readings
        ]

    async def list_active_alerts(self, page: int = 1, size: int = 50) -> list[TelemetryAlertResponse]:
        skip = (page - 1) * size
        alerts = await self.alert_repo.list_active(skip=skip, limit=size)
        return [self._to_alert_response(alert) for alert in alerts]

    async def acknowledge_alert(self, alert_id: int, user_id: int) -> TelemetryAlertResponse:
        alert = await self.alert_repo.get_by_id(alert_id)
        if not alert:
            raise NotFoundException("Alert not found")
        if alert.status != TelemetryAlertStatus.ACTIVE:
            raise BadRequestException("Only active alerts can be acknowledged")

        alert.status = TelemetryAlertStatus.ACKNOWLEDGED
        alert.acknowledged_by = user_id
        alert.acknowledged_at = utc_now()
        await self.db.flush()
        await self.db.refresh(alert)
        return self._to_alert_response(alert)

    async def _evaluate_thresholds(
        self, reading: IcuVitalReading, patient_id: int | None
    ) -> list[IcuTelemetryAlert]:
        vitals = {
            VitalType.HEART_RATE: reading.heart_rate,
            VitalType.SYSTOLIC_BP: reading.systolic_bp,
            VitalType.DIASTOLIC_BP: reading.diastolic_bp,
            VitalType.SPO2: reading.spo2,
            VitalType.RESPIRATORY_RATE: reading.respiratory_rate,
            VitalType.TEMPERATURE: reading.temperature,
        }

        created: list[IcuTelemetryAlert] = []
        for vital_type, value in vitals.items():
            if value is None:
                continue

            breach = self._check_vital_breach(vital_type, value)
            if not breach:
                continue

            severity, message, threshold_min, threshold_max = breach
            existing = await self.alert_repo.get_active_for_bed_and_vital(
                reading.bed_id, vital_type
            )
            if existing:
                if existing.severity == TelemetryAlertSeverity.CRITICAL:
                    continue
                if severity == TelemetryAlertSeverity.WARNING:
                    continue
                existing.status = TelemetryAlertStatus.RESOLVED
                await self.db.flush()

            alert = IcuTelemetryAlert(
                bed_id=reading.bed_id,
                patient_id=patient_id,
                vital_reading_id=reading.id,
                vital_type=vital_type,
                severity=severity,
                status=TelemetryAlertStatus.ACTIVE,
                message=message,
                value=value,
                threshold_min=threshold_min,
                threshold_max=threshold_max,
            )
            alert = await self.alert_repo.create(alert)
            created.append(alert)

        return created

    def _check_vital_breach(
        self, vital_type: str, value: float
    ) -> tuple[str, str, float | None, float | None] | None:
        rules = VITAL_THRESHOLDS.get(vital_type)
        if not rules:
            return None

        label = vital_type.replace("_", " ")
        critical_min = rules.get("critical_min")
        critical_max = rules.get("critical_max")
        warning_min = rules.get("min")
        warning_max = rules.get("max")

        if critical_min is not None and value < critical_min:
            return (
                TelemetryAlertSeverity.CRITICAL,
                f"{label} critically low: {value}",
                critical_min,
                warning_max,
            )
        if critical_max is not None and value > critical_max:
            return (
                TelemetryAlertSeverity.CRITICAL,
                f"{label} critically high: {value}",
                warning_min,
                critical_max,
            )
        if warning_min is not None and value < warning_min:
            return (
                TelemetryAlertSeverity.WARNING,
                f"{label} below threshold: {value}",
                warning_min,
                warning_max,
            )
        if warning_max is not None and value > warning_max:
            return (
                TelemetryAlertSeverity.WARNING,
                f"{label} above threshold: {value}",
                warning_min,
                warning_max,
            )
        return None

    def _patient_name(self, patient) -> str | None:
        if not patient:
            return None
        return f"{patient.first_name} {patient.last_name}".strip()

    def _to_vital_response(
        self, reading: IcuVitalReading, has_active_alerts: bool
    ) -> VitalReadingResponse:
        bed = reading.bed
        patient = reading.patient
        return VitalReadingResponse(
            id=reading.id,
            bed_id=reading.bed_id,
            bed_name=bed.name if bed else None,
            patient_id=reading.patient_id,
            patient_name=self._patient_name(patient),
            device_id=reading.device_id,
            recorded_at=reading.recorded_at,
            heart_rate=reading.heart_rate,
            systolic_bp=reading.systolic_bp,
            diastolic_bp=reading.diastolic_bp,
            spo2=reading.spo2,
            respiratory_rate=reading.respiratory_rate,
            temperature=reading.temperature,
            ecg_data=reading.ecg_data,
            has_active_alerts=has_active_alerts,
        )

    def _to_alert_response(self, alert: IcuTelemetryAlert) -> TelemetryAlertResponse:
        bed = alert.bed
        patient = alert.patient
        return TelemetryAlertResponse(
            id=alert.id,
            bed_id=alert.bed_id,
            bed_name=bed.name if bed else None,
            patient_id=alert.patient_id,
            patient_name=self._patient_name(patient),
            vital_reading_id=alert.vital_reading_id,
            vital_type=alert.vital_type,
            severity=alert.severity,
            status=alert.status,
            message=alert.message,
            value=alert.value,
            threshold_min=alert.threshold_min,
            threshold_max=alert.threshold_max,
            acknowledged_by=alert.acknowledged_by,
            acknowledged_at=alert.acknowledged_at,
            created_at=alert.created_at,
        )

    def _to_device_response(self, device: IcuDevice) -> IcuDeviceResponse:
        bed = device.bed
        return IcuDeviceResponse(
            id=device.id,
            bed_id=device.bed_id,
            bed_name=bed.name if bed else None,
            device_serial=device.device_serial,
            name=device.name,
            is_active=device.is_active,
            last_seen_at=device.last_seen_at,
            created_at=device.created_at,
        )
