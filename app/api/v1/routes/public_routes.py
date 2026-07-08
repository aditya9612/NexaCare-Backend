from datetime import date
from typing import List, Optional

from fastapi import APIRouter, File, Form, UploadFile, Depends
from pydantic import ValidationError

from app.core.dependencies import DbSession
from app.schemas.common_schema import APIResponse
from app.schemas.appointment_schema import AppointmentResponse
from app.schemas.public_schema import (
    AdvancedBookingRequest,
    PublicDoctorResponse,
    QuickBookingRequest,
    ReportUploadResponse,
    SymptomAnalysisRequest,
    SymptomAnalysisResponse,
)
from app.services.public_service import PublicService

router = APIRouter()


@router.get("/doctors", response_model=APIResponse[List[PublicDoctorResponse]])
async def list_public_doctors(
    db: DbSession,
    department_id: Optional[int] = None,
    department: Optional[str] = None,
    specialty: Optional[str] = None,
    date: Optional[date] = None,
):
    """
    Get available doctors with their availability slots and weekly schedule.
    `working_days` / `weekly_schedule.day_name` use MONDAY–SUNDAY (day_of_week 0–6).
    Supports optional filters: department_id, department, specialty, date.
    """
    doctors = await PublicService(db).list_public_doctors(
        department_id=department_id,
        department=department,
        specialty=specialty,
        appointment_date=date,
    )
    return APIResponse(message="Available doctors retrieved successfully", data=doctors)


@router.post("/appointments/book", response_model=APIResponse[AppointmentResponse], status_code=201)
async def quick_book_appointment(
    db: DbSession,
    request_data: QuickBookingRequest,
):
    """
    Quickly book an appointment.
    Creates a new patient if they do not exist by phone.
    """
    appointment = await PublicService(db).quick_book_appointment(request_data)
    return APIResponse(message="Appointment booked successfully", data=appointment)


@router.post("/ai/analyze-symptoms", response_model=APIResponse[SymptomAnalysisResponse])
async def analyze_symptoms(
    db: DbSession,
    request_data: SymptomAnalysisRequest,
):
    """
    Analyze patient symptoms and suggest specialist doctor and booking slots.
    """
    analysis = await PublicService(db).analyze_symptoms(request_data)
    return APIResponse(message="Symptom analysis completed", data=analysis)


@router.post("/appointments/upload-report", response_model=APIResponse[ReportUploadResponse], status_code=201)
async def upload_public_report(
    db: DbSession,
    file: UploadFile = File(...),
    patient_phone: str = Form(...),
    patient_name: Optional[str] = Form(None),
):
    """
    Upload a medical report PDF/Image and associate it with a patient.
    Creates a new patient if they do not exist by phone.
    """
    from app.utils.phone_utils import validate_phone_field
    from fastapi import HTTPException
    try:
        normalized = validate_phone_field(patient_phone)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc) if str(exc) else "Invalid phone number format"
        )

    upload_result = await PublicService(db).upload_public_report(
        file=file,
        patient_phone=normalized,
        patient_name=patient_name,
    )
    return APIResponse(message="Report uploaded successfully", data=upload_result)


@router.post("/appointments/book-ai", response_model=APIResponse[AppointmentResponse], status_code=201)
async def advanced_book_appointment(
    db: DbSession,
    request_data: AdvancedBookingRequest,
):
    """
    Book an appointment with AI triage insights and optional report document link.
    """
    appointment = await PublicService(db).advanced_book_appointment(request_data)
    return APIResponse(message="Appointment booked successfully with AI insights", data=appointment)
