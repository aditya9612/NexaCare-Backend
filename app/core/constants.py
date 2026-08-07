class UserRole:
    SUPER_ADMIN = "Super Admin"
    HOSPITAL_ADMIN = "Hospital Admin"
    DOCTOR = "Doctor"
    NURSE = "Nurse"
    RECEPTIONIST = "Receptionist"
    ACCOUNTANT = "Accountant"
    PHARMACIST = "Pharmacist"
    LAB_TECHNICIAN = "Lab Technician"
    PATIENT = "Patient"

    ADMIN_ROLES = {SUPER_ADMIN, HOSPITAL_ADMIN}
    CLINICAL_ROLES = {DOCTOR, NURSE, RECEPTIONIST}
    ALL = {
        SUPER_ADMIN,
        HOSPITAL_ADMIN,
        DOCTOR,
        NURSE,
        RECEPTIONIST,
        ACCOUNTANT,
        PHARMACIST,
        LAB_TECHNICIAN,
        PATIENT,
    }


from enum import Enum

class OperationMode(str, Enum):
    FIXED_HOURS = "fixed_hours"
    TWENTY_FOUR_SEVEN = "twenty_four_seven"
    SHIFT_BASED = "shift_based"
    CUSTOM = "custom"

class PermissionAction:
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    EXPORT = "export"
    APPROVE = "approve"
    ASSIGN = "assign"
    SHARE = "share"



class AppointmentStatus:
    PENDING = "Pending"
    CONFIRMED = "Confirmed"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"
    NO_SHOW = "No Show"

    ACTIVE = {PENDING, CONFIRMED}
    TERMINAL = {COMPLETED, CANCELLED, NO_SHOW}


class PatientStatus:
    ACTIVE = "active"
    INACTIVE = "inactive"
    DECEASED = "deceased"


class DoctorAvailability:
    AVAILABLE = "available"
    BUSY = "busy"
    ON_LEAVE = "onleave"
    UNAVAILABLE = "unavailable"


class BillingStatus:
    PENDING = "pending"
    PAID = "paid"
    PARTIAL = "partial"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class PaymentMethod:
    CASH = "cash"
    CARD = "card"
    UPI = "upi"
    BANK_TRANSFER = "bank_transfer"
    INSURANCE = "insurance"
    CHEQUE = "cheque"


class PharmacyStatus:
    PENDING = "pending"
    DISPENSED = "dispensed"
    CANCELLED = "cancelled"


class PurchaseStatus:
    ORDERED = "ordered"
    RECEIVED = "received"
    CANCELLED = "cancelled"


class LabOrderStatus:
    ORDERED = "ordered"
    SAMPLE_COLLECTED = "sample_collected"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class LabReportStatus:
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"


class SampleStatus:
    PENDING = "pending"
    COLLECTED = "collected"
    REJECTED = "rejected"


class StockTransactionType:
    INWARD = "inward"
    OUTWARD = "outward"
    TRANSFER = "transfer"
    ADJUSTMENT = "adjustment"
    CONSUMPTION = "consumption"


class ReorderAlertStatus:
    ACTIVE = "active"
    RESOLVED = "resolved"


class TelemetryAlertStatus:
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class TelemetryAlertSeverity:
    WARNING = "warning"
    CRITICAL = "critical"


class VitalType:
    HEART_RATE = "heart_rate"
    SYSTOLIC_BP = "systolic_bp"
    DIASTOLIC_BP = "diastolic_bp"
    SPO2 = "spo2"
    RESPIRATORY_RATE = "respiratory_rate"
    TEMPERATURE = "temperature"


VITAL_THRESHOLDS: dict[str, dict[str, float]] = {
    VitalType.HEART_RATE: {
        "min": 60,
        "max": 100,
        "critical_min": 40,
        "critical_max": 130,
    },
    VitalType.SYSTOLIC_BP: {
        "min": 90,
        "max": 140,
        "critical_min": 70,
        "critical_max": 180,
    },
    VitalType.DIASTOLIC_BP: {
        "min": 60,
        "max": 90,
        "critical_min": 40,
        "critical_max": 120,
    },
    VitalType.SPO2: {
        "min": 94,
        "critical_min": 88,
    },
    VitalType.RESPIRATORY_RATE: {
        "min": 12,
        "max": 20,
        "critical_min": 8,
        "critical_max": 30,
    },
    VitalType.TEMPERATURE: {
        "min": 36.1,
        "max": 37.5,
        "critical_min": 35.0,
        "critical_max": 39.5,
    },
}


class ChatSessionStatus:
    ACTIVE = "Active"
    CLOSED = "Closed"
    ESCALATED = "Escalated"


class ChatSenderType:
    USER = "User"
    BOT = "Bot"
    AGENT = "Agent"


class ChatMessageType:
    TEXT = "Text"
    VOICE = "Voice"
    IMAGE = "Image"
    FILE = "File"


class VoiceCallStatus:
    PENDING = "Pending"
    CALLING = "Calling"
    COMPLETED = "Completed"
    FAILED = "Failed"
    BUSY = "Busy"
    CANCELLED = "Cancelled"


class VoiceCallType:
    REMINDER = "reminder"
    CONFIRMATION = "confirmation"
    FOLLOW_UP = "follow_up"
    APPOINTMENT_ASSISTANT = "appointment_assistant"


class VoiceResponseType:
    DTMF = "DTMF"
    VOICE = "Voice"


class TelephonyProviderType:
    TWILIO = "twilio"
    EXOTEL = "exotel"

    ALL = {TWILIO, EXOTEL}


class VoiceLanguage:
    EN = "en"
    HI = "hi"
    MR = "mr"

    ALL = {EN, HI, MR}
    DTMF_MAP = {"1": EN, "2": HI, "3": MR}


class VoiceGender:
    FEMALE = "female"
    MALE = "male"


class TransferStatus:
    NONE = "none"
    INITIATED = "initiated"
    CONNECTED = "connected"
    BUSY = "busy"
    QUEUED = "queued"
    FAILED = "failed"


class CallbackTicketStatus:
    QUEUED = "queued"
    CALLED_BACK = "called_back"
    CLOSED = "closed"


class WhatsAppMessageType:
    TEXT = "Text"
    IMAGE = "Image"
    PDF = "PDF"
    VIDEO = "Video"
    AUDIO = "Audio"


class WhatsAppDeliveryStatus:
    PENDING = "Pending"
    SENT = "Sent"
    DELIVERED = "Delivered"
    READ = "Read"
    FAILED = "Failed"


class CampaignStatus:
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class KPIStatus:
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    BEHIND = "behind"


class ReportExportStatus:
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ReportExportFormat:
    PDF = "pdf"
    EXCEL = "excel"


class DayOfWeek:
    """Python weekday() convention: 0 = Monday, 6 = Sunday."""

    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6

    NAMES = (
        "MONDAY",
        "TUESDAY",
        "WEDNESDAY",
        "THURSDAY",
        "FRIDAY",
        "SATURDAY",
        "SUNDAY",
    )

    @classmethod
    def name_for(cls, day_of_week: int) -> str:
        if 0 <= day_of_week <= 6:
            return cls.NAMES[day_of_week]
        raise ValueError(f"day_of_week must be 0-6, got {day_of_week}")
