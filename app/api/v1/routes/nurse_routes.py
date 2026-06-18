from datetime import date

from fastapi import APIRouter, Depends

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.models.user_model import User
from app.schemas.common_schema import APIResponse, MessageResponse
from app.schemas.patient_schema import PatientResponse
from app.schemas.nurse_schema import (
    NurseAssignedPatientProfileResponse,
    NurseAssignedPatientStatusResponse,
    NurseAttendanceCreate,
    NurseAttendanceResponse,
    NurseCreate,
    NurseHandoverNoteCreate,
    NurseHandoverNoteResponse,
    NurseHandoverNoteUpdate,
    NurseNotificationResponse,
    NurseResponse,
    NurseShiftCreate,
    NurseShiftDetailsResponse,
    NurseShiftResponse,
    NurseShiftUpdate,
    NurseUpdate,
    PatientVitalCreate,
    PatientVitalResponse,
    NurseTaskResponse,
    NurseTaskStatusUpdate,
    NursePatientLabTestResponse,
)
from app.services.nurse_service import NurseService
from app.utils.pagination import PaginatedResult

router = APIRouter()


@router.post("", response_model=APIResponse[NurseResponse], status_code=201)
async def create_nurse(
    data: NurseCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("nurses", "create")),
):
    nurse = await NurseService(db).create(data, current_user.id)
    return APIResponse(message="Nurse created", data=nurse)


@router.get("", response_model=APIResponse[PaginatedResult[NurseResponse]])
async def list_nurses(
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    department_id: int | None = None,
    shift: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    _: User = Depends(require_permission("nurses", "read")),
):
    result = await NurseService(db).list_nurses(
        page=page,
        size=size,
        department_id=department_id,
        shift=shift,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return APIResponse(message="Nurses retrieved", data=result)


@router.get("/search", response_model=APIResponse[PaginatedResult[NurseResponse]])
async def search_nurses(
    q: str,
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    _: User = Depends(require_permission("nurses", "read")),
):
    result = await NurseService(db).search(q, page=page, size=size)
    return APIResponse(message="Search results", data=result)


@router.get("/{nurse_id}", response_model=APIResponse[NurseResponse])
async def get_nurse(
    nurse_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("nurses", "read")),
):
    nurse = await NurseService(db).get_by_id(nurse_id)
    return APIResponse(message="Nurse retrieved", data=nurse)


@router.put("/{nurse_id}", response_model=APIResponse[NurseResponse])
async def update_nurse(
    nurse_id: int,
    data: NurseUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("nurses", "update")),
):
    nurse = await NurseService(db).update(nurse_id, data, current_user.id)
    return APIResponse(message="Nurse updated", data=nurse)


@router.delete("/{nurse_id}", response_model=APIResponse[MessageResponse])
async def delete_nurse(
    nurse_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("nurses", "delete")),
):
    await NurseService(db).delete(nurse_id, current_user.id)
    return APIResponse(message="Nurse deleted", data=MessageResponse(message="Deleted successfully"))


@router.get(
    "/{nurse_id}/tasks",
    response_model=APIResponse[PaginatedResult[NurseTaskResponse]],
)
async def list_nurse_daily_tasks(
    nurse_id: int,
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    patient_id: int | None = None,
    status: str | None = None,
    priority: str | None = None,
    sort_by: str = "priority",
    sort_order: str = "desc",
    _: User = Depends(require_permission("nurses", "read")),
):
    result = await NurseService(db).list_daily_tasks(
        nurse_id=nurse_id,
        page=page,
        size=size,
        patient_id=patient_id,
        status=status,
        priority=priority,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return APIResponse(message="Daily nursing tasks retrieved", data=result)


@router.put(
    "/{nurse_id}/tasks/{task_id}/status",
    response_model=APIResponse[NurseTaskResponse],
)
async def update_nurse_task_status(
    nurse_id: int,
    task_id: int,
    data: NurseTaskStatusUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("nurses", "update")),
):
    task = await NurseService(db).update_task_status(
        nurse_id, task_id, data, current_user.id
    )
    return APIResponse(message="Task status updated", data=task)


@router.get(
    "/{nurse_id}/patients/status",
    response_model=APIResponse[PaginatedResult[NurseAssignedPatientStatusResponse]],
)
async def list_nurse_patient_statuses(
    nurse_id: int,
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    assignment_status: str | None = None,
    patient_status: str | None = None,
    sort_by: str = "updated_at",
    sort_order: str = "desc",
    _: User = Depends(require_permission("nurses", "read")),
):
    result = await NurseService(db).list_assigned_patient_statuses(
        nurse_id=nurse_id,
        page=page,
        size=size,
        assignment_status=assignment_status,
        patient_status=patient_status,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return APIResponse(message="Assigned patient statuses retrieved", data=result)


@router.get(
    "/{nurse_id}/patients",
    response_model=APIResponse[PaginatedResult[PatientResponse]],
)
async def list_nurse_patients(
    nurse_id: int,
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    status: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    _: User = Depends(require_permission("nurses", "read")),
):
    result = await NurseService(db).list_assigned_patients(
        nurse_id=nurse_id,
        page=page,
        size=size,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return APIResponse(message="Assigned patients retrieved", data=result)


@router.get(
    "/{nurse_id}/patients/{patient_id}/profile",
    response_model=APIResponse[NurseAssignedPatientProfileResponse],
)
async def get_nurse_patient_profile(
    nurse_id: int,
    patient_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("nurses", "read")),
):
    profile = await NurseService(db).get_assigned_patient_profile(nurse_id, patient_id)
    return APIResponse(message="Patient profile retrieved", data=profile)


@router.post(
    "/{nurse_id}/patients/{patient_id}/vitals",
    response_model=APIResponse[PatientVitalResponse],
    status_code=201,
)
async def record_patient_vitals(
    nurse_id: int,
    patient_id: int,
    data: PatientVitalCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("nurses", "create")),
):
    vital = await NurseService(db).record_patient_vitals(
        nurse_id, patient_id, data, current_user.id
    )
    return APIResponse(message="Patient vitals recorded", data=vital)


@router.get(
    "/{nurse_id}/patients/{patient_id}/lab-tests",
    response_model=APIResponse[PaginatedResult[NursePatientLabTestResponse]],
)
async def list_nurse_patient_lab_tests(
    nurse_id: int,
    patient_id: int,
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    status: str | None = None,
    sort_by: str = "ordered_at",
    sort_order: str = "desc",
    _: User = Depends(require_permission("nurses", "read")),
):
    result = await NurseService(db).list_patient_lab_tests(
        nurse_id=nurse_id,
        patient_id=patient_id,
        page=page,
        size=size,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return APIResponse(message="Patient lab test requests retrieved", data=result)


@router.get(
    "/{nurse_id}/shift-details",
    response_model=APIResponse[NurseShiftDetailsResponse],
)
async def get_nurse_shift_details(
    nurse_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("nurses", "read")),
):
    details = await NurseService(db).get_shift_details(nurse_id)
    return APIResponse(message="Nurse shift details retrieved", data=details)


@router.post(
    "/{nurse_id}/shifts",
    response_model=APIResponse[NurseShiftResponse],
    status_code=201,
)
async def create_nurse_shift(
    nurse_id: int,
    data: NurseShiftCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("nurses", "create")),
):
    shift = await NurseService(db).create_shift(nurse_id, data, current_user.id)
    return APIResponse(message="Nurse shift created", data=shift)


@router.put(
    "/{nurse_id}/shifts/{shift_id}",
    response_model=APIResponse[NurseShiftResponse],
)
async def update_nurse_shift(
    nurse_id: int,
    shift_id: int,
    data: NurseShiftUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("nurses", "update")),
):
    shift = await NurseService(db).update_shift(
        nurse_id, shift_id, data, current_user.id
    )
    return APIResponse(message="Nurse shift updated", data=shift)


@router.get("/{nurse_id}/shifts", response_model=APIResponse[PaginatedResult[NurseShiftResponse]])
async def list_nurse_shifts(
    nurse_id: int,
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    start_date: date | None = None,
    end_date: date | None = None,
    shift_name: str | None = None,
    sort_by: str = "shift_date",
    sort_order: str = "desc",
    _: User = Depends(require_permission("nurses", "read")),
):
    result = await NurseService(db).list_shifts(
        nurse_id=nurse_id,
        page=page,
        size=size,
        start_date=start_date,
        end_date=end_date,
        shift_name=shift_name,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return APIResponse(message="Nurse shifts retrieved", data=result)


@router.post(
    "/{nurse_id}/attendance",
    response_model=APIResponse[NurseAttendanceResponse],
    status_code=201,
)
async def create_nurse_attendance(
    nurse_id: int,
    data: NurseAttendanceCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("nurses", "create")),
):
    attendance = await NurseService(db).create_attendance(nurse_id, data, current_user.id)
    return APIResponse(message="Nurse attendance created", data=attendance)


@router.get(
    "/{nurse_id}/attendance",
    response_model=APIResponse[PaginatedResult[NurseAttendanceResponse]],
)
async def list_nurse_attendance(
    nurse_id: int,
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    start_date: date | None = None,
    end_date: date | None = None,
    status: str | None = None,
    sort_by: str = "attendance_date",
    sort_order: str = "desc",
    _: User = Depends(require_permission("nurses", "read")),
):
    result = await NurseService(db).list_attendance(
        nurse_id=nurse_id,
        page=page,
        size=size,
        start_date=start_date,
        end_date=end_date,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return APIResponse(message="Nurse attendance retrieved", data=result)


@router.post(
    "/{nurse_id}/handover-notes",
    response_model=APIResponse[NurseHandoverNoteResponse],
    status_code=201,
)
async def create_nurse_handover_note(
    nurse_id: int,
    data: NurseHandoverNoteCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("nurses", "create")),
):
    note = await NurseService(db).create_handover_note(nurse_id, data, current_user.id)
    return APIResponse(message="Nurse handover note created", data=note)


@router.get(
    "/{nurse_id}/handover-notes",
    response_model=APIResponse[PaginatedResult[NurseHandoverNoteResponse]],
)
async def list_nurse_handover_notes(
    nurse_id: int,
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    start_date: date | None = None,
    end_date: date | None = None,
    status: str | None = None,
    shift_id: int | None = None,
    sort_by: str = "handover_date",
    sort_order: str = "desc",
    _: User = Depends(require_permission("nurses", "read")),
):
    result = await NurseService(db).list_handover_notes(
        nurse_id=nurse_id,
        page=page,
        size=size,
        start_date=start_date,
        end_date=end_date,
        status=status,
        shift_id=shift_id,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return APIResponse(message="Nurse handover notes retrieved", data=result)


@router.put(
    "/{nurse_id}/handover-notes/{note_id}",
    response_model=APIResponse[NurseHandoverNoteResponse],
)
async def update_nurse_handover_note(
    nurse_id: int,
    note_id: int,
    data: NurseHandoverNoteUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: User = Depends(require_permission("nurses", "update")),
):
    note = await NurseService(db).update_handover_note(
        nurse_id, note_id, data, current_user.id
    )
    return APIResponse(message="Nurse handover note updated", data=note)


@router.get(
    "/{nurse_id}/notifications",
    response_model=APIResponse[PaginatedResult[NurseNotificationResponse]],
)
async def list_nurse_notifications(
    nurse_id: int,
    db: DbSession,
    current_user: CurrentUser,
    page: int = 1,
    size: int = 20,
    status: str = "Active",
    notification_type: str | None = None,
    priority: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    _: User = Depends(require_permission("nurses", "read")),
):
    result = await NurseService(db).list_notifications(
        nurse_id=nurse_id,
        page=page,
        size=size,
        status=status,
        notification_type=notification_type,
        priority=priority,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return APIResponse(message="Nurse notifications retrieved", data=result)
