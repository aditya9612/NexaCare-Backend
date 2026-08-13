from datetime import date, datetime
import re

from pydantic import EmailStr, Field, field_validator, model_validator

from app.schemas.common_schema import BaseSchema, PaginatedResponse
from app.utils.common_validators import (
    validate_full_name as common_validate_full_name,
    validate_mobile as common_validate_mobile,
    validate_not_future_date as common_validate_not_future_date,
)


VALID_BLOOD_GROUPS = {"A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"}
VALID_MARITAL_STATUSES = {"Single", "Married", "Divorced", "Widowed", "Separated"}
VALID_PATIENT_STATUSES = {"active", "inactive", "deceased"}


def validate_name_field(v: str | None, field_name: str) -> str | None:
    return common_validate_full_name(v, field_name)


def validate_phone_number_field(v: str | None, field_name: str) -> str | None:
    if v is not None:
        return common_validate_mobile(v, field_name)
    return v


def validate_dob_field(v: date | None) -> date | None:
    return common_validate_not_future_date(v, "Date of birth")


def validate_blood_group_field(v: str | None) -> str | None:
    if v is None:
        return v
    cleaned = v.strip().upper()
    if not cleaned or cleaned.lower() == "null":
        raise ValueError("Blood group cannot be blank or 'null'")
    if cleaned not in VALID_BLOOD_GROUPS:
        raise ValueError(f"Invalid blood group. Allowed values: {', '.join(sorted(VALID_BLOOD_GROUPS))}")
    return cleaned


def validate_marital_status_field(v: str | None) -> str | None:
    if v is None:
        return v
    cleaned = v.strip().capitalize()
    if not cleaned or cleaned.lower() == "null":
        raise ValueError("Marital status cannot be blank or 'null'")
    if cleaned not in VALID_MARITAL_STATUSES:
        raise ValueError(f"Invalid marital status. Allowed values: {', '.join(sorted(VALID_MARITAL_STATUSES))}")
    return cleaned


def validate_pincode_field(v: str | None) -> str | None:
    if v is None:
        return v
    cleaned = v.strip()
    if not cleaned or cleaned.lower() == "null":
        raise ValueError("Pincode cannot be blank or 'null'")
    if not cleaned.isdigit() or len(cleaned) not in {5, 6}:
        raise ValueError("Pincode must contain only numeric digits and be either 5 or 6 digits long")
    return cleaned


def validate_status_field(v: str | None) -> str | None:
    if v is None:
        return v
    cleaned = v.strip().lower()
    if not cleaned or cleaned == "null":
        raise ValueError("Status cannot be blank or 'null'")
    if cleaned not in VALID_PATIENT_STATUSES:
        raise ValueError(f"Invalid status. Allowed values: {', '.join(sorted(VALID_PATIENT_STATUSES))}")
    return cleaned


VALID_GENDERS = {"Male", "Female", "Other"}


def validate_gender_field(v: str | None) -> str | None:
    if v is None:
        return v
    cleaned = v.strip().capitalize()
    if not cleaned or cleaned.lower() == "null":
        raise ValueError("Gender cannot be blank or 'null'")
    if cleaned not in VALID_GENDERS:
        raise ValueError(f"Invalid gender. Allowed values: {', '.join(sorted(VALID_GENDERS))}")
    return cleaned


def validate_city_field(v: str | None) -> str | None:
    if v is None:
        return v
    cleaned = v.strip()
    if not cleaned or cleaned.lower() == "null":
        raise ValueError("City cannot be blank or 'null'")
    if not re.match(r"^[a-zA-Z\s\-\'\.]+$", cleaned):
        raise ValueError("City must contain only alphabetic characters, spaces, hyphens, dots, or apostrophes")
    return cleaned


def validate_state_field(v: str | None) -> str | None:
    if v is None:
        return v
    cleaned = v.strip()
    if not cleaned or cleaned.lower() == "null":
        raise ValueError("State cannot be blank or 'null'")
    if not re.match(r"^[a-zA-Z\s\-\'\.]+$", cleaned):
        raise ValueError("State must contain only alphabetic characters, spaces, hyphens, dots, or apostrophes")
    return cleaned




class PatientCreate(BaseSchema):
    first_name: str
    last_name: str
    gender: str | None = None
    dob: date | None = None
    blood_group: str | None = None
    marital_status: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    pincode: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_number: str | None = None
    allergies: str | None = None
    medical_history: str | None = None
    chronic_disease: str | None = None
    diagnosis: str
    insurance_provider: str | None = None
    insurance_number: str | None = None
    status: str = "active"
    preferred_language: str | None = None

    @field_validator("first_name")
    @classmethod
    def val_first_name(cls, v: str) -> str:
        res = validate_name_field(v, "First name")
        if res is None:
            raise ValueError("First name cannot be blank")
        return res

    @field_validator("last_name")
    @classmethod
    def val_last_name(cls, v: str) -> str:
        res = validate_name_field(v, "Last name")
        if res is None:
            raise ValueError("Last name cannot be blank")
        return res

    @field_validator("dob")
    @classmethod
    def val_dob(cls, v: date | None) -> date | None:
        return validate_dob_field(v)

    @field_validator("blood_group")
    @classmethod
    def val_blood_group(cls, v: str | None) -> str | None:
        return validate_blood_group_field(v)

    @field_validator("marital_status")
    @classmethod
    def val_marital_status(cls, v: str | None) -> str | None:
        return validate_marital_status_field(v)

    @field_validator("phone")
    @classmethod
    def val_phone(cls, v: str | None) -> str | None:
        return validate_phone_number_field(v, "Phone number")

    @field_validator("pincode")
    @classmethod
    def val_pincode(cls, v: str | None) -> str | None:
        return validate_pincode_field(v)

    @field_validator("emergency_contact_name")
    @classmethod
    def val_emergency_contact_name(cls, v: str | None) -> str | None:
        return validate_name_field(v, "Emergency contact name")

    @field_validator("emergency_contact_number")
    @classmethod
    def val_emergency_contact_number(cls, v: str | None) -> str | None:
        return validate_phone_number_field(v, "Emergency contact number")

    @field_validator("status")
    @classmethod
    def val_status(cls, v: str) -> str:
        res = validate_status_field(v)
        if res is None:
            raise ValueError("Status cannot be blank")
        return res

    @field_validator("gender")
    @classmethod
    def val_gender(cls, v: str | None) -> str | None:
        return validate_gender_field(v)

    @field_validator("city")
    @classmethod
    def val_city(cls, v: str | None) -> str | None:
        return validate_city_field(v)

    @field_validator("state")
    @classmethod
    def val_state(cls, v: str | None) -> str | None:
        return validate_state_field(v)




class PatientUpdate(BaseSchema):
    first_name: str | None = None
    last_name: str | None = None
    gender: str | None = None
    dob: date | None = None
    blood_group: str | None = None
    marital_status: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    pincode: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_number: str | None = None
    allergies: str | None = None
    medical_history: str | None = None
    chronic_disease: str | None = None
    diagnosis: str | None = None
    insurance_provider: str | None = None
    insurance_number: str | None = None
    status: str | None = None
    preferred_language: str | None = None

    @field_validator("first_name")
    @classmethod
    def val_first_name(cls, v: str | None) -> str | None:
        return validate_name_field(v, "First name")

    @field_validator("last_name")
    @classmethod
    def val_last_name(cls, v: str | None) -> str | None:
        return validate_name_field(v, "Last name")

    @field_validator("dob")
    @classmethod
    def val_dob(cls, v: date | None) -> date | None:
        return validate_dob_field(v)

    @field_validator("blood_group")
    @classmethod
    def val_blood_group(cls, v: str | None) -> str | None:
        return validate_blood_group_field(v)

    @field_validator("marital_status")
    @classmethod
    def val_marital_status(cls, v: str | None) -> str | None:
        return validate_marital_status_field(v)

    @field_validator("phone")
    @classmethod
    def val_phone(cls, v: str | None) -> str | None:
        return validate_phone_number_field(v, "Phone number")

    @field_validator("pincode")
    @classmethod
    def val_pincode(cls, v: str | None) -> str | None:
        return validate_pincode_field(v)

    @field_validator("emergency_contact_name")
    @classmethod
    def val_emergency_contact_name(cls, v: str | None) -> str | None:
        return validate_name_field(v, "Emergency contact name")

    @field_validator("emergency_contact_number")
    @classmethod
    def val_emergency_contact_number(cls, v: str | None) -> str | None:
        return validate_phone_number_field(v, "Emergency contact number")

    @field_validator("status")
    @classmethod
    def val_status(cls, v: str | None) -> str | None:
        return validate_status_field(v)

    @field_validator("gender")
    @classmethod
    def val_gender(cls, v: str | None) -> str | None:
        return validate_gender_field(v)

    @field_validator("city")
    @classmethod
    def val_city(cls, v: str | None) -> str | None:
        return validate_city_field(v)

    @field_validator("state")
    @classmethod
    def val_state(cls, v: str | None) -> str | None:
        return validate_state_field(v)



class PatientBedAllocationResponse(BaseSchema):
    bed_id: int
    bed_name: str
    bed_type: str
    room_id: int
    room_number: int
    room_name: str
    floor_id: int
    floor_number: int
    floor_name: str
    allocation_time: datetime | None = None
    admission_date: datetime | None = None


class BedHistoryResponse(BaseSchema):
    floor_name: str | None = None
    room_name: str | None = None
    bed_name: str | None = None
    admitted_date: str | None = None
    discharged_date: str | None = None


def parse_medical_history_to_bed_history(medical_history: str | None) -> list[dict]:
    if not medical_history:
        return []
        
    history_list = []
    lines = medical_history.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Parse Bed Admission:
        admission_match = re.search(
            r"\[Bed Admission\]:\s*Admitted to Bed\s+(.*?)\s+\(Room:\s*([^,)]*)(?:,\s*Floor:\s*([^)]*))?\)\s+on\s+(\d{4}-\d{2}-\d{2})",
            line
        )
        if admission_match:
            bed_name = admission_match.group(1).strip()
            room_name = admission_match.group(2).strip()
            floor_name = admission_match.group(3).strip() if admission_match.group(3) else None
            admitted_date = admission_match.group(4).strip()
            
            history_list.append({
                "floor_name": floor_name,
                "room_name": room_name,
                "bed_name": bed_name,
                "admitted_date": admitted_date,
                "discharged_date": None
            })
            continue

        # Parse Bed Discharge:
        discharge_match = re.search(
            r"\[Bed Discharge\]:\s*Discharged from Bed\s+([^(\n]+?)(?:\s+\(Room:\s*([^,)]*)(?:,\s*Floor:\s*([^)]*))?\))?\s+on\s+(\d{4}-\d{2}-\d{2})",
            line
        )
        if discharge_match:
            bed_name = discharge_match.group(1).strip()
            discharged_date = discharge_match.group(4).strip()
            
            for entry in reversed(history_list):
                if entry["bed_name"] == bed_name and entry["discharged_date"] is None:
                    entry["discharged_date"] = discharged_date
                    if discharge_match.group(2):
                        entry["room_name"] = discharge_match.group(2).strip()
                    if discharge_match.group(3):
                        entry["floor_name"] = discharge_match.group(3).strip()
                    break
            continue

        # Parse Bed Transfer:
        transfer_match = re.search(
            r"\[Bed Transfer\]:\s*Transferred from Bed\s+(.*?)\s+to Bed\s+(.*?)\s+on\s+(\d{4}-\d{2}-\d{2})\.\s*From Room\s+([^,]*),\s*Floor\s+(.*?)\s+to Room\s+([^,]*),\s*Floor\s+(.*)",
            line
        )
        if transfer_match:
            old_bed = transfer_match.group(1).strip()
            new_bed = transfer_match.group(2).strip()
            transfer_date = transfer_match.group(3).strip()
            old_room = transfer_match.group(4).strip()
            old_floor = transfer_match.group(5).strip()
            new_room = transfer_match.group(6).strip()
            new_floor = transfer_match.group(7).strip()
            
            # Close the old bed admission
            for entry in reversed(history_list):
                if entry["bed_name"] == old_bed and entry["discharged_date"] is None:
                    entry["discharged_date"] = transfer_date
                    break
            # Add the new bed admission
            history_list.append({
                "floor_name": new_floor,
                "room_name": new_room,
                "bed_name": new_bed,
                "admitted_date": transfer_date,
                "discharged_date": None
            })
            continue

    return history_list


class PatientBedAllocationResponse(BaseSchema):
    bed_id: int
    bed_name: str
    bed_type: str
    room_id: int
    room_number: int
    room_name: str
    floor_id: int
    floor_number: int
    floor_name: str
    allocation_time: datetime | None = None
    admission_date: datetime | None = None


class PatientResponseBase(BaseSchema):
    id: int
    patient_code: str
    first_name: str
    last_name: str
    gender: str | None
    dob: date | None
    blood_group: str | None
    marital_status: str | None
    phone: str | None
    email: str | None
    address: str | None
    city: str | None
    state: str | None
    pincode: str | None
    emergency_contact_name: str | None
    emergency_contact_number: str | None
    allergies: str | None
    medical_history: str | None
    chronic_disease: str | None
    diagnosis: str | None = ""
    insurance_provider: str | None
    insurance_number: str | None
    status: str
    preferred_language: str | None = None
    bed_allocation: PatientBedAllocationResponse | None = None
    condition_status: str | None = None
    created_at: datetime
    updated_at: datetime
    bed_history: list[BedHistoryResponse] | None = None

    @model_validator(mode="after")
    def populate_bed_history(self) -> "PatientResponse":
        raw_history = parse_medical_history_to_bed_history(self.medical_history)
        self.bed_history = [BedHistoryResponse.model_validate(item) for item in raw_history]
        return self


class PatientCreateResponse(PatientResponseBase):
    pass


class PatientResponse(PatientResponseBase):
    guardian_patient_id: int | None = None
    relationship_to_guardian: str | None = None


class PatientSearchQuery(BaseSchema):
    q: str = Field(..., min_length=1)
    page: int = 1
    size: int = 20


class PatientFilterQuery(BaseSchema):
    gender: str | None = None
    blood_group: str | None = None
    city: str | None = None
    state: str | None = None
    status: str | None = None
    page: int = 1
    size: int = 20

    @field_validator("gender")
    @classmethod
    def val_gender(cls, v: str | None) -> str | None:
        return validate_gender_field(v)

    @field_validator("blood_group")
    @classmethod
    def val_blood_group(cls, v: str | None) -> str | None:
        return validate_blood_group_field(v)

    @field_validator("city")
    @classmethod
    def val_city(cls, v: str | None) -> str | None:
        return validate_city_field(v)

    @field_validator("state")
    @classmethod
    def val_state(cls, v: str | None) -> str | None:
        return validate_state_field(v)

    @field_validator("status")
    @classmethod
    def val_status(cls, v: str | None) -> str | None:
        return validate_status_field(v)


class FamilyMemberCreate(BaseSchema):
    full_name: str
    relationship_type: str
    phone: str | None = None
    email: EmailStr | None = None

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: str) -> str:
        if v is None:
            raise ValueError("Full name is required")
        res = validate_name_field(v, "Full name")
        if res is None:
            raise ValueError("Full name cannot be blank")
        return res

    @field_validator("relationship_type")
    @classmethod
    def validate_relationship(cls, v: str) -> str:
        if v is None:
            raise ValueError("Relationship type is required")
        cleaned = v.strip()
        if not cleaned or cleaned.lower() == "null":
            raise ValueError("Relationship type cannot be blank or 'null'")
            
        if not re.match(r"^[a-zA-Z\s]+$", cleaned):
            raise ValueError("Relationship type must contain only alphabetic characters and spaces")
            
        valid_relationships = {"Spouse", "Child", "Parent", "Sibling", "Grandparent", "Grandchild", "Guardian", "Other"}
        
        norm_map = {r.lower(): r for r in valid_relationships}
        lower_cleaned = cleaned.lower()
        if lower_cleaned not in norm_map:
            raise ValueError(f"Invalid relationship type. Allowed values: {', '.join(sorted(valid_relationships))}")
            
        return norm_map[lower_cleaned]

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_phone_number_field(v, "Phone number")


class FamilyMemberResponse(BaseSchema):
    id: int
    patient_id: int
    full_name: str
    relationship_type: str
    phone: str | None
    email: str | None


class PatientDocumentCreate(BaseSchema):
    document_type: str

    @field_validator("document_type")
    @classmethod
    def check_document_type(cls, v: str) -> str:
        if v is None:
            raise ValueError("Document type is required")
            
        # Check for empty / whitespace / null string
        if not v or not v.strip() or v.lower() == "null":
            raise ValueError("Document type cannot be blank or 'null'")
            
        # Check for leading/trailing spaces
        if v.startswith(" ") or v.endswith(" "):
            raise ValueError("Document type should not contain leading or trailing spaces")
            
        val = v.strip()
        
        # Check if contains only digits or special characters
        if val.isdigit():
            raise ValueError("Document type cannot be a numeric value")
            
        if not re.match(r"^[a-zA-Z\s\-_/]+$", val):
            raise ValueError("Document type cannot contain special characters")
            
        valid_types = {
            "general",
            "report",
            "lab report",
            "prescription",
            "id proof",
            "insurance",
            "medical history",
            "consent form",
            "other",
        }
        
        # Standard normalization map
        norm_map = {
            "general": "General",
            "report": "Report",
            "lab report": "Lab Report",
            "prescription": "Prescription",
            "id proof": "ID Proof",
            "insurance": "Insurance",
            "medical history": "Medical History",
            "consent_form": "Consent Form",
            "consent": "Consent Form",
            "consent form": "Consent Form",
            "other": "Other",
            "lab_report": "Lab Report",
            "id_proof": "ID Proof",
            "medical_history": "Medical History",
        }
        
        lower_val = val.lower()
        if lower_val not in norm_map:
            raise ValueError(f"Invalid document type. Allowed types are: {', '.join(sorted(valid_types))}")
            
        return norm_map[lower_val]


class PatientDocumentResponse(BaseSchema):
    id: int
    patient_id: int
    document_name: str
    document_type: str
    file_path: str
    created_at: datetime


class PatientListResponse(BaseSchema):
    items: list[PatientResponse]
    total: int
    page: int
    size: int
    pages: int
    active_count: int
    inactive_count: int
    cities_count: int

