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
    import logging
    logger = logging.getLogger("nexacare.api.public")
    
    try:
        doctors = await PublicService(db).list_public_doctors(
            department_id=department_id,
            department=department,
            specialty=specialty,
            appointment_date=date,
        )
        return APIResponse(message="Available doctors retrieved successfully", data=doctors)
    except Exception as exc:
        logger.exception("Exception in list_public_doctors API route: %s", exc)
        from fastapi import HTTPException
        if isinstance(exc, HTTPException):
            raise exc
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred while listing public doctors: {str(exc)}"
        )


@router.get("/debug/health")
async def debug_health(db: DbSession):
    """
    Detailed health and debug monitor endpoint for the public portal.
    Checks DB and Redis connectivity, calculating response latencies.
    """
    import time
    from fastapi.responses import JSONResponse
    from sqlalchemy import text
    from app.utils.redis_service import get_redis
    
    health_status = {
        "status": "healthy",
        "timestamp": time.time(),
        "services": {}
    }
    
    # 1. Database Connectivity Check
    try:
        start_time = time.time()
        await db.execute(text("SELECT 1"))
        db_elapsed = (time.time() - start_time) * 1000
        health_status["services"]["database"] = {
            "status": "connected",
            "latency_ms": round(db_elapsed, 2)
        }
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["services"]["database"] = {
            "status": "disconnected",
            "error": str(e)
        }
        
    # 2. Redis Connectivity Check
    try:
        start_time = time.time()
        redis_client = await get_redis()
        if redis_client:
            await redis_client.ping()
            redis_elapsed = (time.time() - start_time) * 1000
            health_status["services"]["redis"] = {
                "status": "connected",
                "latency_ms": round(redis_elapsed, 2)
            }
        else:
            raise Exception("Redis client initialization failed (offline)")
    except Exception as e:
        health_status["services"]["redis"] = {
            "status": "disconnected",
            "error": str(e)
        }
        
    if health_status["status"] == "unhealthy":
        return JSONResponse(status_code=503, content=health_status)
        
    return health_status


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
