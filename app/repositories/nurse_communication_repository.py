from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.nurse_model import Nurse, PatientUpdate, EmergencyAlert


class NurseCommunicationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_patient_update(self, patient_update: PatientUpdate) -> PatientUpdate:
        self.db.add(patient_update)
        await self.db.flush()
        return patient_update

    async def get_patient_updates(self, patient_id: int) -> list[PatientUpdate]:
        result = await self.db.execute(
            select(PatientUpdate)
            .options(joinedload(PatientUpdate.nurse).joinedload(Nurse.user))
            .where(PatientUpdate.patient_id == patient_id)
            .order_by(PatientUpdate.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_patient_updates(
        self,
        nurse_id: int | None = None,
        patient_id: int | None = None,
        severity: str | None = None,
    ) -> list[PatientUpdate]:
        query = (
            select(PatientUpdate)
            .options(joinedload(PatientUpdate.nurse).joinedload(Nurse.user))
        )
        if patient_id is not None:
            query = query.where(PatientUpdate.patient_id == patient_id)
        if nurse_id is not None:
            query = query.where(PatientUpdate.nurse_id == nurse_id)
        if severity is not None:
            query = query.where(func.upper(PatientUpdate.severity) == severity.upper())
        query = query.order_by(PatientUpdate.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create_emergency_alert(self, emergency_alert: EmergencyAlert) -> EmergencyAlert:
        self.db.add(emergency_alert)
        await self.db.flush()
        return emergency_alert

    async def get_emergency_alerts_by_nurse(self, nurse_id: int) -> list[EmergencyAlert]:
        result = await self.db.execute(
            select(EmergencyAlert)
            .where(EmergencyAlert.nurse_id == nurse_id)
            .order_by(EmergencyAlert.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_emergency_alert_by_id(self, alert_id: int, nurse_id: int) -> EmergencyAlert | None:
        result = await self.db.execute(
            select(EmergencyAlert).where(
                EmergencyAlert.id == alert_id,
                EmergencyAlert.nurse_id == nurse_id,
            )
        )
        return result.scalar_one_or_none()

    async def update_emergency_alert(self, emergency_alert: EmergencyAlert) -> EmergencyAlert:
        await self.db.flush()
        await self.db.refresh(emergency_alert)
        return emergency_alert

    async def get_emergency_alert(self, alert_id: int) -> EmergencyAlert | None:
        result = await self.db.execute(
            select(EmergencyAlert).where(EmergencyAlert.id == alert_id)
        )
        return result.scalar_one_or_none()

    async def delete_emergency_alert(self, emergency_alert: EmergencyAlert) -> None:
        await self.db.delete(emergency_alert)
        await self.db.flush()
