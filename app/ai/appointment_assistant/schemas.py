from datetime import date, time
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class BookingStep(str, Enum):
    COLLECT_SYMPTOMS = "collect_symptoms"
    SUGGEST_SPECIALIST = "suggest_specialist"
    PICK_DOCTOR = "pick_doctor"
    PICK_SLOT = "pick_slot"
    CONFIRM = "confirm"
    BOOKED = "booked"


class BookingState(BaseModel):
    step: BookingStep = BookingStep.COLLECT_SYMPTOMS
    patient_id: int
    symptoms: Optional[str] = None
    recommended_specialist: Optional[str] = None
    doctor_id: Optional[int] = None
    doctor_name: Optional[str] = None
    department_id: Optional[int] = None
    appointment_date: Optional[date] = None
    appointment_time: Optional[time] = None
    consultation_type: Optional[str] = "in_person"

    def to_dict(self) -> Dict[str, Any]:
        data = self.model_dump(mode="json")
        data["step"] = self.step.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BookingState":
        if "step" in data and isinstance(data["step"], str):
            data = {**data, "step": BookingStep(data["step"])}
        return cls.model_validate(data)


class SuggestedSlot(BaseModel):
    doctor_id: int
    doctor_name: str
    specialization: str
    appointment_date: date
    appointment_time: time


class BookingTurnResult(BaseModel):
    message: str
    booking_state: BookingState
    suggested_slots: List[SuggestedSlot] = Field(default_factory=list)
    appointment: Optional[Dict[str, Any]] = None
    requires_confirmation: bool = False
