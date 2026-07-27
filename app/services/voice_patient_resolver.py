"""
Resolve which patient an inbound voice booking belongs to.

Rules (no extra "self vs family" prompt):
1. Look up account holder by caller phone.
2. If no holder → create new patient with spoken name + phone.
3. If spoken name matches holder → reuse holder.
4. If spoken name matches an existing dependent under holder → reuse dependent.
5. Otherwise → create new dependent patient (phone=None, guardian=holder).
"""

from __future__ import annotations

import logging
import re
from typing import Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.patient_model import Patient
from app.repositories.patient_repository import PatientRepository
from app.utils.helpers import generate_mrn

logger = logging.getLogger("nexacare.voice_patient_resolver")


def _normalize_name(value: str | None) -> str:
    if not value:
        return ""
    text = value.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def split_spoken_name(spoken_name: str) -> Tuple[str, str]:
    parts = (spoken_name or "").strip().split(maxsplit=1)
    first = parts[0] if parts else "Patient"
    last = parts[1] if len(parts) > 1 else ""
    return first, last


def names_match(spoken_name: str, patient: Patient) -> bool:
    """True if spoken name refers to this patient (full or first-name match)."""
    spoken = _normalize_name(spoken_name)
    if not spoken:
        return False

    first = _normalize_name(patient.first_name)
    last = _normalize_name(patient.last_name)
    full = f"{first} {last}".strip()

    if spoken == full:
        return True
    if spoken == first:
        return True
    # "Rahul Sharma" vs stored first=Rahul last=Sharma already covered by full.
    # Also allow spoken full when order matches loosely.
    spoken_parts = spoken.split()
    if len(spoken_parts) >= 2 and first and last:
        if spoken_parts[0] == first and spoken_parts[-1] == last:
            return True
    return False


class VoicePatientResolver:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = PatientRepository(db)

    async def resolve_for_booking(
        self,
        *,
        phone: str | None,
        spoken_name: str | None,
    ) -> Tuple[Patient, Patient]:
        """
        Returns (attendee, account_holder).

        - attendee: patient the appointment is for (may be a dependent)
        - account_holder: patient who owns the phone (same as attendee when booking for self)
        """
        name = (spoken_name or "").strip() or "Patient"
        phone = (phone or "").strip() or None

        holder = await self.repo.get_by_phone(phone) if phone else None

        if not holder:
            holder = await self._create_patient(
                spoken_name=name,
                phone=phone,
                guardian_patient_id=None,
            )
            logger.info(
                "Voice booking: created account holder id=%s name=%r phone=%r",
                holder.id,
                name,
                phone,
            )
            return holder, holder

        if names_match(name, holder):
            logger.info(
                "Voice booking: matched account holder id=%s for spoken=%r",
                holder.id,
                name,
            )
            return holder, holder

        dependents = await self.repo.list_dependents(holder.id)
        for dep in dependents:
            if names_match(name, dep):
                logger.info(
                    "Voice booking: matched dependent id=%s under guardian=%s spoken=%r",
                    dep.id,
                    holder.id,
                    name,
                )
                return dep, holder

        dependent = await self._create_patient(
            spoken_name=name,
            phone=None,
            guardian_patient_id=holder.id,
            relationship_to_guardian="Other",
        )
        logger.info(
            "Voice booking: created dependent id=%s under guardian=%s spoken=%r",
            dependent.id,
            holder.id,
            name,
        )
        return dependent, holder

    async def _create_patient(
        self,
        *,
        spoken_name: str,
        phone: str | None,
        guardian_patient_id: int | None,
        relationship_to_guardian: str | None = None,
    ) -> Patient:
        first_name, last_name = split_spoken_name(spoken_name)
        patient = Patient(
            patient_code=generate_mrn(),
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            status="active",
            guardian_patient_id=guardian_patient_id,
            relationship_to_guardian=relationship_to_guardian,
        )
        return await self.repo.create(patient)
