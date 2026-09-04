from datetime import date, datetime
from pydantic import Field, field_validator

from app.schemas.common_schema import BaseSchema


class DischargeInitiateRequest(BaseSchema):
    appointment_id: int = Field(..., gt=0, description="ID of the admitted IPD appointment")
    diagnosis_at_discharge: str = Field(..., min_length=2, description="Final confirmed diagnosis at discharge")
    treatment_summary: str = Field(..., min_length=3, description="Summary of clinical procedures and treatments given")
    condition_on_discharge: str = Field(default="Stable", description="Condition of patient: Stable, Recovered, Relieved, etc.")
    post_medications: str | None = Field(default=None, description="Discharge prescription: medicine name, dosage, frequency, duration")
    home_care_instructions: str | None = Field(default=None, description="Wound care, diet, physical activity precautions")
    follow_up_date: date | None = Field(default=None, description="Next doctor visit / review date")
    discharge_notes: str | None = None


class ClearPharmacyRequest(BaseSchema):
    notes: str | None = Field(default=None, description="Confirmation that remaining/unused meds returned and billed")


class ProcedureChargeItem(BaseSchema):
    description: str = Field(..., min_length=2, description="Procedure or surgical intervention name")
    amount: float = Field(..., ge=0.0, description="Cost of the clinical procedure")


class GenerateIPDBillRequest(BaseSchema):
    discount_amount: float = Field(default=0.0, ge=0.0, description="Any approved hospital discount")
    additional_doctor_visits: int = Field(default=0, ge=0, description="Additional specialist/visiting consultant visits")
    gst_rate: float = Field(default=0.0, ge=0.0, le=28.0, description="GST rate percentage (0 - 28%)")
    procedure_charges: list[ProcedureChargeItem] | None = Field(default=None, description="Optional procedure / surgery charges")
    include_prior_opd_balance: bool = Field(default=False, description="Include unpaid prior OPD charges from this admission episode")
    notes: str | None = None


class ClearBillingRequest(BaseSchema):
    notes: str | None = Field(default=None, description="Billing clearance confirmation notes")


class ClearPaymentRequest(BaseSchema):
    payment_method: str = Field(default="cash", description="cash, upi, card, net_banking, insurance, cheque, or neft_rtgs")
    transaction_ref: str | None = Field(default=None, description="UPI reference / Cheque / Card transaction ID")
    notes: str | None = None

    @field_validator("payment_method")
    @classmethod
    def validate_payment_method(cls, v: str) -> str:
        allowed = {"cash", "upi", "card", "net_banking", "insurance", "cheque", "neft_rtgs", "credit_card", "debit_card"}
        cleaned = (v or "cash").strip().lower()
        if cleaned not in allowed:
            raise ValueError(f"Invalid payment method '{v}'. Allowed methods: {', '.join(sorted(allowed))}")
        return cleaned


class DischargeClearanceStatus(BaseSchema):
    pharmacy_cleared: bool
    pharmacy_cleared_at: datetime | None = None
    billing_cleared: bool
    billing_cleared_at: datetime | None = None
    billing_id: int | None = None
    final_bill_id: int | None = None
    payment_cleared: bool
    payment_cleared_at: datetime | None = None
    doctor_approved: bool
    doctor_approved_at: datetime | None = None
    ready_for_discharge: bool
    discharge_status: str


class DischargeResponse(BaseSchema):
    id: int
    discharge_number: str
    appointment_id: int
    patient_id: int
    doctor_id: int
    bed_id: int | None = None
    admission_date: datetime
    discharge_date: datetime
    diagnosis_at_admission: str | None = None
    diagnosis_at_discharge: str
    treatment_summary: str
    condition_on_discharge: str
    post_medications: str | None = None
    home_care_instructions: str | None = None
    follow_up_date: date | None = None
    
    pharmacy_cleared: bool
    pharmacy_cleared_at: datetime | None = None
    pharmacy_notes: str | None = None
    
    billing_cleared: bool
    billing_cleared_at: datetime | None = None
    billing_id: int | None = None
    final_bill_id: int | None = None
    billing_notes: str | None = None
    
    payment_cleared: bool
    payment_cleared_at: datetime | None = None
    payment_notes: str | None = None
    
    doctor_approved: bool
    doctor_approved_at: datetime | None = None
    
    discharge_status: str
    gate_pass_number: str | None = None
    discharge_notes: str | None = None
    created_at: datetime
    updated_at: datetime


class DischargeGatePassResponse(BaseSchema):
    gate_pass_number: str
    discharge_number: str
    patient_name: str
    patient_code: str
    admission_date: datetime
    discharge_date: datetime
    doctor_name: str
    ward_name: str | None = None
    bed_number: str | None = None
    payment_status: str
    authorized_by: str
    issued_at: datetime
