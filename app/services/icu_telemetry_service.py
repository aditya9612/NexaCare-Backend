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
from app.repositories.audit_repository import AuditRepository
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
    IcuDeviceUpdate,
    TelemetryAlertResponse,
    TelemetryIngest,
    TelemetryIngestResponse,
    VitalReadingResponse,
)
from app.utils.helpers import utc_now
from app.utils.pagination import PaginatedResult, build_paginated_result


class IcuTelemetryService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.device_repo = IcuDeviceRepository(db)
        self.reading_repo = IcuVitalReadingRepository(db)
        self.alert_repo = IcuTelemetryAlertRepository(db)
        self.bed_repo = BedAllocationRepository(db)
        self.audit_repo = AuditRepository(db)

    async def create_device(self, data: IcuDeviceCreate, user_id: int) -> IcuDeviceCreatedResponse:
        bed = await self.bed_repo.get_bed_by_id(data.bed_id, load_patient=False)
        if not bed:
            raise NotFoundException("Bed not found")

        existing = await self.device_repo.get_by_serial(data.device_serial)
        if existing:
            raise ConflictException("Device serial already registered")

        active_on_bed = await self.device_repo.get_active_for_bed(data.bed_id)
        if active_on_bed:
            raise ConflictException("An active device is already registered for this bed")

        api_key = generate_device_api_key()
        device = IcuDevice(
            bed_id=data.bed_id,
            device_serial=data.device_serial,
            api_key_hash=hash_api_key(api_key),
            name=data.name,
            is_active=True,
        )
        device = await self.device_repo.create(device)
        await self.audit_repo.create(
            "create",
            "icu_devices",
            user_id=user_id,
            resource_id=str(device.id),
            details=f"serial={device.device_serial}, bed_id={device.bed_id}",
        )
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

    async def update_device(
        self, device_id: int, data: IcuDeviceUpdate, user_id: int
    ) -> IcuDeviceResponse:
        device = await self.device_repo.get_by_id(device_id)
        if not device:
            raise NotFoundException("Device not found")

        updates = data.model_dump(exclude_unset=True)
        if not updates:
            raise BadRequestException("No fields to update")

        if "bed_id" in updates:
            bed = await self.bed_repo.get_bed_by_id(updates["bed_id"], load_patient=False)
            if not bed:
                raise NotFoundException("Bed not found")
            if device.is_active:
                active_on_bed = await self.device_repo.get_active_for_bed(
                    updates["bed_id"], exclude_device_id=device.id
                )
                if active_on_bed:
                    raise ConflictException("An active device is already registered for this bed")

        for key, value in updates.items():
            setattr(device, key, value)

        device = await self.device_repo.save(device)
        await self.audit_repo.create(
            "update",
            "icu_devices",
            user_id=user_id,
            resource_id=str(device.id),
            details=f"fields={','.join(sorted(updates.keys()))}",
        )
        return self._to_device_response(device)

    async def set_device_status(
        self, device_id: int, is_active: bool, user_id: int
    ) -> IcuDeviceResponse:
        device = await self.device_repo.get_by_id(device_id)
        if not device:
            raise NotFoundException("Device not found")
        if device.is_active == is_active:
            state = "active" if is_active else "inactive"
            raise BadRequestException(f"Device is already {state}")

        if is_active:
            active_on_bed = await self.device_repo.get_active_for_bed(
                device.bed_id, exclude_device_id=device.id
            )
            if active_on_bed:
                raise ConflictException("An active device is already registered for this bed")

        device.is_active = is_active
        device = await self.device_repo.save(device)
        action = "activate" if is_active else "deactivate"
        await self.audit_repo.create(
            action,
            "icu_devices",
            user_id=user_id,
            resource_id=str(device.id),
            details=f"serial={device.device_serial}, is_active={is_active}",
        )
        return self._to_device_response(device)

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

    async def get_history_for_bed(
        self,
        bed_id: int,
        from_time=None,
        to_time=None,
        page: int = 1,
        size: int = 50,
        include_ecg: bool = False,
    ) -> PaginatedResult[VitalReadingResponse]:
        bed = await self.bed_repo.get_bed_by_id(bed_id, load_patient=False)
        if not bed:
            raise NotFoundException("Bed not found")

        resolved_from, resolved_to = self._resolve_history_window(from_time, to_time)
        skip = (page - 1) * size
        readings = await self.reading_repo.list_history(
            bed_id=bed_id,
            from_time=resolved_from,
            to_time=resolved_to,
            skip=skip,
            limit=size,
        )
        total = await self.reading_repo.count_history(
            bed_id=bed_id,
            from_time=resolved_from,
            to_time=resolved_to,
        )
        items = [self._to_vital_response(reading, include_ecg=include_ecg) for reading in readings]
        return build_paginated_result(items, total, page, size)

    async def get_history_for_patient(
        self,
        patient_id: int,
        from_time=None,
        to_time=None,
        page: int = 1,
        size: int = 50,
        include_ecg: bool = False,
    ) -> PaginatedResult[VitalReadingResponse]:
        resolved_from, resolved_to = self._resolve_history_window(from_time, to_time)
        skip = (page - 1) * size
        readings = await self.reading_repo.list_history(
            patient_id=patient_id,
            from_time=resolved_from,
            to_time=resolved_to,
            skip=skip,
            limit=size,
        )
        total = await self.reading_repo.count_history(
            patient_id=patient_id,
            from_time=resolved_from,
            to_time=resolved_to,
        )
        items = [self._to_vital_response(reading, include_ecg=include_ecg) for reading in readings]
        return build_paginated_result(items, total, page, size)

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
        await self.audit_repo.create(
            "acknowledge",
            "icu_telemetry_alerts",
            user_id=user_id,
            resource_id=str(alert.id),
            details=f"vital_type={alert.vital_type}, severity={alert.severity}, bed_id={alert.bed_id}",
        )
        return self._to_alert_response(alert)

    def _normalize_history_datetime(self, value):
        if value is None:
            return None
        if value.tzinfo is not None:
            return value.replace(tzinfo=None)
        return value

    def _resolve_history_window(self, from_time, to_time):
        from datetime import timedelta

        normalized_from = self._normalize_history_datetime(from_time)
        normalized_to = self._normalize_history_datetime(to_time)
        now = utc_now()

        if normalized_from is None and normalized_to is None:
            normalized_to = now
            normalized_from = now - timedelta(hours=settings.ICU_TELEMETRY_HISTORY_DEFAULT_HOURS)
        elif normalized_from is None:
            normalized_to = normalized_to or now
            normalized_from = normalized_to - timedelta(hours=settings.ICU_TELEMETRY_HISTORY_DEFAULT_HOURS)
        elif normalized_to is None:
            normalized_to = now

        if normalized_from > normalized_to:
            raise BadRequestException("from_time must be before or equal to to_time")

        max_span = timedelta(days=settings.ICU_TELEMETRY_HISTORY_MAX_DAYS)
        if normalized_to - normalized_from > max_span:
            raise BadRequestException(
                f"Time range cannot exceed {settings.ICU_TELEMETRY_HISTORY_MAX_DAYS} days"
            )

        return normalized_from, normalized_to

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
        self,
        reading: IcuVitalReading,
        has_active_alerts: bool = False,
        include_ecg: bool = True,
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
            ecg_data=reading.ecg_data if include_ecg else None,
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
