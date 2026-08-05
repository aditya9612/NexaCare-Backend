from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.nurse_model import PatientUpdate, EmergencyAlert


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
            .options(joinedload(PatientUpdate.nurse).joinedload(PatientUpdate.nurse.user))
            .where(PatientUpdate.patient_id == patient_id)
            .order_by(PatientUpdate.created_at.desc())
        )
        return list(result.scalars().all())

    async def create_emergency_alert(self, emergency_alert: EmergencyAlert) -> EmergencyAlert:
        self.db.add(emergency_alert)
        await self.db.flush()
        return emergency_alert
