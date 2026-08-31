from fastapi import APIRouter, Depends, status

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.common_schema import APIResponse
from app.schemas.final_bill_schema import IPDFinalBillResponse, IPDFinalBillSummaryResponse
from app.schemas.discharge_schema import (
    ClearBillingRequest,
    ClearPaymentRequest,
    ClearPharmacyRequest,
    DischargeClearanceStatus,
    DischargeGatePassResponse,
    DischargeInitiateRequest,
    DischargeResponse,
    GenerateIPDBillRequest,
)
from app.services.discharge_service import DischargeService

router = APIRouter(prefix="/discharge", tags=["Discharge & Clearances"])


@router.post("/initiate", response_model=APIResponse[DischargeResponse], status_code=status.HTTP_201_CREATED)
async def initiate_discharge(
    data: DischargeInitiateRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("appointments", "update")),
):
    """
    Doctor initiates patient discharge and submits medical discharge summary.
    Discharge status transitions to PENDING_CLEARANCES.
    """
    discharge = await DischargeService(db).initiate_discharge(data, current_user.id)
    return APIResponse(
        success=True,
        message="Discharge initiated successfully. Awaiting multi-stage clearances.",
        data=discharge,
    )


@router.get("/active", response_model=APIResponse[list[DischargeResponse]])
async def list_active_discharges(
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("appointments", "read")),
):
    """
    List all active discharge cases currently undergoing clearances.
    """
    items = await DischargeService(db).list_active_discharges()
    return APIResponse(
        success=True,
        message="Active discharges retrieved successfully",
        data=items,
    )


@router.get("/{discharge_id}", response_model=APIResponse[DischargeResponse])
async def get_discharge(
    discharge_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("appointments", "read")),
):
    """
    Get discharge record and clearance statuses by discharge ID.
    """
    discharge = await DischargeService(db).get_by_id(discharge_id)
    return APIResponse(
        success=True,
        message="Discharge record retrieved successfully",
        data=discharge,
    )


@router.get("/by-appointment/{appointment_id}", response_model=APIResponse[DischargeResponse])
async def get_discharge_by_appointment(
    appointment_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("appointments", "read")),
):
    """
    Get discharge details for an appointment.
    """
    discharge = await DischargeService(db).get_by_appointment(appointment_id)
    return APIResponse(
        success=True,
        message="Discharge record retrieved successfully",
        data=discharge,
    )


@router.get("/{discharge_id}/clearance-status", response_model=APIResponse[DischargeClearanceStatus])
async def get_clearance_status(
    discharge_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("appointments", "read")),
):
    """
    Check real-time clearance status (Pharmacy, Billing, Payment, Doctor Approval).
    """
    status_data = await DischargeService(db).get_clearance_status(discharge_id)
    return APIResponse(
        success=True,
        message="Clearance status retrieved successfully",
        data=status_data,
    )


@router.patch("/{discharge_id}/clear-pharmacy", response_model=APIResponse[DischargeResponse])
async def clear_pharmacy(
    discharge_id: int,
    db: DbSession,
    current_user: CurrentUser,
    data: ClearPharmacyRequest | None = None,
    _: User = Depends(require_permission("pharmacy", "update")),
):
    """
    Pharmacist verifies returned/unbilled medications and approves Pharmacy Clearance.
    """
    discharge = await DischargeService(db).clear_pharmacy(discharge_id, current_user.id, data)
    return APIResponse(
        success=True,
        message="Pharmacy clearance approved successfully",
        data=discharge,
    )


@router.get("/final-bills", response_model=APIResponse[list[IPDFinalBillSummaryResponse]])
async def list_final_bills(
    db: DbSession,
    current_user: CurrentUser,
    skip: int = 0,
    limit: int = 50,
    patient_id: int | None = None,
    status: str | None = None,
    _: User = Depends(require_permission("billing", "read")),
):
    """
    List all IPD Final Discharge Bills with search and status filters.
    """
    bills = await DischargeService(db).list_final_bills(skip=skip, limit=limit, patient_id=patient_id, status=status)
    return APIResponse(
        success=True,
        message="IPD Final Bills retrieved successfully",
        data=bills,
    )


@router.get("/{discharge_id}/final-bill", response_model=APIResponse[IPDFinalBillResponse])
async def get_discharge_final_bill(
    discharge_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("billing", "read")),
):
    """
    Get detailed IPD Final Bill with all line items and component breakdowns by discharge ID.
    """
    final_bill = await DischargeService(db).get_final_bill_by_discharge_id(discharge_id)
    return APIResponse(
        success=True,
        message="IPD Final Bill retrieved successfully",
        data=final_bill,
    )


@router.post("/{discharge_id}/generate-final-bill", response_model=APIResponse[IPDFinalBillResponse])
async def generate_final_bill(
    discharge_id: int,
    data: GenerateIPDBillRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("billing", "create")),
):
    """
    Accountant calculates total stay days and auto-generates final IPD bill based on Room Tariffs, Lab, Radiology, and Pharmacy.
    """
    result = await DischargeService(db).generate_ipd_final_bill(discharge_id, data, current_user.id)
    return APIResponse(
        success=True,
        message="IPD Final Bill generated successfully",
        data=result,
    )


@router.patch("/{discharge_id}/clear-billing", response_model=APIResponse[DischargeResponse])
async def clear_billing(
    discharge_id: int,
    data: ClearBillingRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("billing", "update")),
):
    """
    Billing department verifies final bill and approves Billing Clearance.
    """
    discharge = await DischargeService(db).clear_billing(discharge_id, current_user.id, data)
    return APIResponse(
        success=True,
        message="Billing clearance approved successfully",
        data=discharge,
    )


@router.patch("/{discharge_id}/clear-payment", response_model=APIResponse[DischargeResponse])
async def clear_payment(
    discharge_id: int,
    data: ClearPaymentRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("billing", "update")),
):
    """
    Cashier settles remaining bill balance and approves Payment Clearance.
    """
    discharge = await DischargeService(db).clear_payment(discharge_id, data, current_user.id)
    return APIResponse(
        success=True,
        message="Payment clearance approved successfully",
        data=discharge,
    )


@router.post("/{discharge_id}/approve", response_model=APIResponse[DischargeResponse])
async def approve_discharge(
    discharge_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("appointments", "update")),
):
    """
    Doctor gives final approval after all 3 clearances are met.
    Patient is marked DISCHARGED, Gate Pass is generated, and Bed transitions to CLEANING.
    """
    discharge = await DischargeService(db).doctor_approve_discharge(discharge_id, current_user.id)
    return APIResponse(
        success=True,
        message="Discharge approved successfully. Gate pass generated and bed sent for housekeeping sanitization.",
        data=discharge,
    )


@router.get("/{discharge_id}/gate-pass", response_model=APIResponse[DischargeGatePassResponse])
async def get_gate_pass(
    discharge_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("appointments", "read")),
):
    """
    Get official Security Gate Pass for discharged patient.
    """
    gate_pass = await DischargeService(db).get_gate_pass(discharge_id)
    return APIResponse(
        success=True,
        message="Gate pass retrieved successfully",
        data=gate_pass,
    )
