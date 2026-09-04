from typing import List, Optional
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import BedStatus
from app.core.exceptions import BadRequestException, NotFoundException, ConflictException
from app.models.bed_allocation_model import Floor, Room, Bed, BedActivityLog
from app.models.patient_model import Patient
from app.repositories.bed_allocation_repository import BedAllocationRepository
from app.schemas.bed_allocation_schema import (
    FloorCreate,
    FloorUpdate,
    RoomCreate,
    RoomUpdate,
    BedCreate,
    BedUpdate,
    BedAllocationRequest,
    BedReleaseRequest,
    BedTransferRequest,
    BedAnalyticsSummaryResponse,
    ICUAnalyticsResponse,
)
from app.utils.helpers import utc_now


class BedAllocationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = BedAllocationRepository(db)

    # Floor Services
    async def get_floor(self, floor_id: int) -> Floor:
        floor = await self.repo.get_floor_by_id(floor_id)
        if not floor:
            raise NotFoundException("Floor not found")
        for room in floor.rooms:
            for bed in room.beds:
                if bed.patient and getattr(bed.patient, "is_deleted", False):
                    bed.status = "Available"
                    bed.patient_id = None
                    bed.patient = None
                    bed.allocation_time = None
                    bed.admission_date = None
        return floor

    async def list_floors(
        self,
        status: Optional[str] = None,
        floor_id: Optional[int] = None,
        floor_number: Optional[int] = None,
        floor_type: Optional[str] = None,
        room_id: Optional[int] = None,
        room_number: Optional[int] = None,
        room_type: Optional[str] = None,
    ) -> List[Floor]:
        floors = await self.repo.list_floors(
            floor_id=floor_id,
            floor_number=floor_number,
            floor_type=floor_type,
        )

        status_clean = status.strip().lower() if status else None
        room_type_clean = room_type.strip().lower() if room_type else None

        filtered_floors = []
        for floor in floors:
            matching_rooms = []
            for room in floor.rooms:
                if room_id is not None and room.id != room_id:
                    continue
                if room_number is not None and room.number != room_number:
                    continue
                if room_type_clean is not None and (room.type or "").strip().lower() != room_type_clean:
                    continue

                matching_beds = []
                for bed in room.beds:
                    if bed.patient and getattr(bed.patient, "is_deleted", False):
                        bed.status = "Available"
                        bed.patient_id = None
                        bed.patient = None
                        bed.allocation_time = None
                        bed.admission_date = None

                    if status_clean is not None:
                        if (bed.status or "").strip().lower() != status_clean:
                            continue

                    matching_beds.append(bed)

                if status_clean is not None:
                    if matching_beds:
                        room.beds = matching_beds
                        matching_rooms.append(room)
                else:
                    room.beds = matching_beds
                    matching_rooms.append(room)

            if room_id is not None or room_number is not None or room_type_clean is not None or status_clean is not None:
                if matching_rooms:
                    floor.rooms = matching_rooms
                    filtered_floors.append(floor)
            else:
                floor.rooms = matching_rooms
                filtered_floors.append(floor)

        return filtered_floors

    async def create_floor(self, data: FloorCreate) -> Floor:
        existing = await self.repo.get_floor_by_number(data.number)
        if existing:
            raise ConflictException(f"Floor number {data.number} already exists")

        floor = Floor(
            number=data.number,
            name=data.name,
            type=data.type,
            description=data.description,
        )
        floor = await self.repo.create_floor(floor)

        if data.rooms:
            for r_data in data.rooms:
                room = Room(
                    floor_id=floor.id,
                    number=r_data.number,
                    name=r_data.name,
                    type=r_data.type,
                    capacity=r_data.capacity,
                    description=r_data.description,
                )
                room = await self.repo.create_room(room)
                # Auto-create beds up to room capacity
                for i in range(1, room.capacity + 1):
                    bed = Bed(
                        room_id=room.id,
                        name=f"Bed {i}",
                        type=room.type,
                        status="Available",
                    )
                    await self.repo.create_bed(bed)

        return await self.get_floor(floor.id)

    async def update_floor(self, floor_id: int, data: FloorUpdate) -> Floor:
        floor = await self.get_floor(floor_id)
        
        if data.number is not None and data.number != floor.number:
            existing = await self.repo.get_floor_by_number(data.number)
            if existing:
                raise ConflictException(f"Floor number {data.number} already exists")
            floor.number = data.number

        if data.name is not None:
            floor.name = data.name
        if data.type is not None:
            floor.type = data.type
        if data.description is not None:
            floor.description = data.description

        await self.db.flush()
        log = BedActivityLog(
            type="crud",
            message=f"Updated floor {floor.name} (Number: {floor.number}).",
            floor_id=floor.id,
        )
        await self.repo.create_activity_log(log)
        return await self.get_floor(floor.id)

    async def delete_floor(self, floor_id: int) -> None:
        floor = await self.get_floor(floor_id)

        for room in floor.rooms:
            for bed in room.beds:
                if bed.status == "Occupied":
                    raise BadRequestException("Cannot delete floor because it contains occupied beds.")

        log = BedActivityLog(
            type="crud",
            message=f"Deleted floor {floor.name} (Number: {floor.number}).",
            floor_id=floor.id,
        )
        await self.repo.create_activity_log(log)

        await self.repo.delete_floor(floor)

    # Room Services
    async def get_room(self, room_id: int) -> Room:
        room = await self.repo.get_room_by_id(room_id)
        if not room:
            raise NotFoundException("Room not found")
        for bed in room.beds:
            if bed.patient and getattr(bed.patient, "is_deleted", False):
                bed.status = "Available"
                bed.patient_id = None
                bed.patient = None
                bed.allocation_time = None
                bed.admission_date = None
        return room

    async def create_room(self, floor_id: int, data: RoomCreate) -> Room:
        floor = await self.get_floor(floor_id)

        existing = await self.repo.get_room_by_number(floor_id, data.number)
        if existing:
            raise ConflictException(f"Room number {data.number} already exists on floor {floor.name}")

        room = Room(
            floor_id=floor_id,
            number=data.number,
            name=data.name,
            type=data.type,
            capacity=data.capacity,
            description=data.description,
        )
        room = await self.repo.create_room(room)

        for i in range(1, room.capacity + 1):
            bed = Bed(
                room_id=room.id,
                name=f"Bed {i}",
                type=room.type,
                status="Available",
            )
            await self.repo.create_bed(bed)

        log = BedActivityLog(
            type="crud",
            message=f"Created room {room.name} under floor {floor.name}.",
            floor_id=floor_id,
            room_id=room.id,
        )
        await self.repo.create_activity_log(log)

        return await self.get_room(room.id)

    async def update_room(self, room_id: int, data: RoomUpdate) -> Room:
        room = await self.get_room(room_id)

        if data.number is not None and data.number != room.number:
            existing = await self.repo.get_room_by_number(room.floor_id, data.number)
            if existing:
                raise ConflictException(f"Room number {data.number} already exists on this floor")
            room.number = data.number

        if data.name is not None:
            room.name = data.name
        if data.type is not None:
            room.type = data.type
        if data.description is not None:
            room.description = data.description
        
        if data.capacity is not None:
            room.capacity = data.capacity

        await self.db.flush()

        log = BedActivityLog(
            type="crud",
            message=f"Updated room {room.name} under floor {room.floor.name if room.floor else ''}.",
            floor_id=room.floor_id,
            room_id=room.id,
        )
        await self.repo.create_activity_log(log)

        return await self.get_room(room.id)

    async def delete_room(self, room_id: int) -> None:
        room = await self.get_room(room_id)

        for bed in room.beds:
            if bed.status == "Occupied":
                raise BadRequestException("Cannot delete room because it contains occupied beds.")

        log = BedActivityLog(
            type="crud",
            message=f"Deleted room {room.name} under floor {room.floor.name if room.floor else ''}.",
            floor_id=room.floor_id,
            room_id=room.id,
        )
        await self.repo.create_activity_log(log)

        await self.repo.delete_room(room)

    # Bed Services
    async def get_bed(self, bed_id: int) -> Bed:
        bed = await self.repo.get_bed_by_id(bed_id)
        if not bed:
            raise NotFoundException("Bed not found")
        if bed.patient and getattr(bed.patient, "is_deleted", False):
            bed.status = "Available"
            bed.patient_id = None
            bed.patient = None
            bed.allocation_time = None
            bed.admission_date = None
        return bed

    async def create_bed(self, room_id: int, data: BedCreate) -> Bed:
        room = await self.get_room(room_id)

        if len(room.beds) >= room.capacity:
            room.capacity = len(room.beds) + 1

        existing = await self.repo.get_bed_by_name(room_id, data.name)
        if existing:
            raise ConflictException(f"Bed name '{data.name}' already exists in this room")

        bed = Bed(
            room_id=room_id,
            name=data.name,
            type=data.type,
            status=data.status or "Available",
        )
        bed = await self.repo.create_bed(bed)

        log = BedActivityLog(
            type="crud",
            message=f"Created bed {bed.name} in room {room.name}.",
            floor_id=room.floor_id,
            room_id=room.id,
            bed_id=bed.id,
        )
        await self.repo.create_activity_log(log)

        return await self.get_bed(bed.id)

    async def update_bed(self, bed_id: int, data: BedUpdate) -> Bed:
        bed = await self.get_bed(bed_id)

        if data.name is not None and data.name != bed.name:
            existing = await self.repo.get_bed_by_name(bed.room_id, data.name)
            if existing:
                raise ConflictException(f"Bed name '{data.name}' already exists in this room")
            bed.name = data.name

        if data.type is not None:
            bed.type = data.type

        if data.status is not None:
            is_occupied = (bed.patient_id is not None) or (bed.status == "Occupied")
            if is_occupied and data.status != bed.status:
                raise ConflictException("Cannot change bed status while the bed is occupied.")
            if data.status == "Occupied" and not bed.patient_id:
                raise BadRequestException("Cannot set bed status to Occupied without an associated patient.")
            bed.status = data.status

        await self.db.flush()

        log = BedActivityLog(
            type="crud",
            message=f"Updated bed {bed.name} details (Status: {bed.status}).",
            floor_id=bed.room.floor_id if bed.room else None,
            room_id=bed.room_id,
            bed_id=bed.id,
            patient_id=bed.patient_id,
        )
        await self.repo.create_activity_log(log)

        return await self.get_bed(bed.id)

    async def delete_bed(self, bed_id: int) -> None:
        bed = await self.get_bed(bed_id)

        if bed.status == "Occupied":
            raise BadRequestException("Cannot delete bed because it is currently occupied.")

        log = BedActivityLog(
            type="crud",
            message=f"Deleted bed {bed.name} from room {bed.room.name if bed.room else ''}.",
            floor_id=bed.room.floor_id if bed.room else None,
            room_id=bed.room_id,
            bed_id=bed.id,
        )
        await self.repo.create_activity_log(log)

        await self.repo.delete_bed(bed)

    # Patient Services
    async def get_patient(self, patient_id: int) -> Patient:
        patient = await self.repo.get_patient_by_id(patient_id)
        if not patient:
            raise NotFoundException("Patient not found")
        return patient

    # Bed Allocation Operations
    async def allocate_bed(self, bed_id: int, data: BedAllocationRequest) -> Bed:
        bed = await self.get_bed(bed_id)
        if bed.status != "Available":
            if bed.status == "Occupied":
                raise BadRequestException("Bed is already occupied")
            raise BadRequestException(f"Bed {bed.name} is not available. Current status: {bed.status}.")

        patient = await self.get_patient(data.patientId)

        from app.core.constants import PatientStatus
        if patient.status == PatientStatus.INACTIVE:
            raise BadRequestException(
                "Cannot allocate a bed to an inactive patient. Please activate the patient first."
            )
        from datetime import datetime as dt, timezone as tz, timedelta
        ist_tz = tz(timedelta(hours=5, minutes=30))
        admission_dt = data.admissionDate
        if admission_dt.tzinfo is None:
            admission_dt = admission_dt.replace(tzinfo=tz.utc)
        admission_date_ist = admission_dt.astimezone(ist_tz).date()
        current_date_ist = dt.now(ist_tz).date()

        if admission_date_ist < current_date_ist:
            raise BadRequestException("Admission date cannot be in the past.")

        from app.models.appointment_model import Appointment
        from sqlalchemy import select, desc

        appointment = None
        if getattr(data, "appointmentId", None):
            stmt = select(Appointment).where(
                Appointment.id == data.appointmentId,
                Appointment.patient_id == patient.id
            )
            res = await self.db.execute(stmt)
            appointment = res.scalar_one_or_none()
            if not appointment:
                raise HTTPException(
                    status_code=404,
                    detail=f"Appointment {data.appointmentId} not found for this patient."
                )
        else:
            # 1. Search for appointment where admission was recommended or admitted
            stmt = (
                select(Appointment)
                .where(
                    Appointment.patient_id == patient.id,
                    (Appointment.admission_status.in_(["Admit Recommended", "Admitted"]))
                    | (Appointment.admission_recommended == True)
                    | (Appointment.appointment_status.in_(["Admit Recommended", "Admitted"]))
                )
                .order_by(desc(Appointment.id))
                .limit(1)
            )
            res = await self.db.execute(stmt)
            appointment = res.scalar_one_or_none()

            # 2. Fallback to latest appointment if no recommended appointment found
            if not appointment:
                stmt = (
                    select(Appointment)
                    .where(Appointment.patient_id == patient.id)
                    .order_by(desc(Appointment.id))
                    .limit(1)
                )
                res = await self.db.execute(stmt)
                appointment = res.scalar_one_or_none()

        if not appointment:
            raise HTTPException(
                status_code=404,
                detail="No appointment found for this patient."
            )

        status_norm = (appointment.appointment_status or "").strip().lower()
        adm_status_norm = (appointment.admission_status or "").strip().lower()
        allowed_statuses = {"completed", "admit recommended", "admit_recommended", "admitted"}
        is_recommended = (
            adm_status_norm in ("admit recommended", "admit_recommended", "admitted")
            or bool(appointment.admission_recommended)
            or status_norm in ("admit recommended", "admit_recommended", "admitted")
        )

        if not is_recommended and status_norm == "pending":
            raise HTTPException(
                status_code=400,
                detail="Cannot allocate bed for a pending appointment. Please confirm and check in the patient first."
            )

        if not is_recommended and status_norm not in allowed_statuses:
            if status_norm == "cancelled" or adm_status_norm == "cancelled":
                raise HTTPException(
                    status_code=400,
                    detail="Cannot allocate bed for a cancelled appointment."
                )
            raise HTTPException(
                status_code=400,
                detail=f"Bed allocation is only allowed for patients with a completed appointment. Current appointment status: {appointment.appointment_status}."
            )

        if not appointment.check_in_time and not is_recommended and status_norm not in ("completed", "admitted", "checked-in", "in-progress") and (appointment.queue_status or "").upper() not in ("CHECKED_IN", "IN_CONSULTATION", "COMPLETED"):
            raise HTTPException(
                status_code=400,
                detail="Cannot allocate bed for a patient who has not checked in. Please check in the patient first."
            )

        if status_norm == "cancelled" or adm_status_norm == "cancelled":
            raise HTTPException(
                status_code=400,
                detail="Cannot allocate bed for a cancelled appointment."
            )

        from app.core.constants import AdmissionStatus, AppointmentStatus
        appointment.admission_status = AdmissionStatus.ADMITTED
        appointment.appointment_type = "IPD"
        appointment.queue_status = "COMPLETED"
        if status_norm in ("admit recommended", "admit_recommended"):
            appointment.appointment_status = AppointmentStatus.COMPLETED

        bed.status = "Occupied"
        bed.patient_id = patient.id
        bed.patient = patient
        bed.allocation_time = utc_now()
        bed.admission_date = data.admissionDate

        floor_name = bed.room.floor.name if bed.room and bed.room.floor else ''
        admission_note = f"\n[Bed Admission]: Admitted to Bed {bed.name} (Room: {bed.room.name if bed.room else ''}, Floor: {floor_name}) on {data.admissionDate.strftime('%Y-%m-%d')}. Notes: {data.notes or 'None'}"
        patient.medical_history = f"{patient.medical_history or ''}{admission_note}".strip()

        await self.db.flush()

        log = BedActivityLog(
            type="allocation",
            message=f"Patient {patient.first_name} {patient.last_name} admitted and allocated to Bed {bed.name} (Room: {bed.room.name if bed.room else ''}).",
            floor_id=bed.room.floor_id if bed.room else None,
            room_id=bed.room_id,
            bed_id=bed.id,
            patient_id=patient.id,
        )
        await self.repo.create_activity_log(log)

        return await self.get_bed(bed.id)

    async def release_bed(self, bed_id: int, data: BedReleaseRequest) -> Bed:
        bed = await self.get_bed(bed_id)
        if bed.status != "Occupied" or not bed.patient_id:
            raise BadRequestException(f"Bed {bed.name} is not currently occupied.")

        patient = await self.get_patient(bed.patient_id)

        floor_name = bed.room.floor.name if bed.room and bed.room.floor else ''
        room_name = bed.room.name if bed.room else ''
        discharge_note = f"\n[Bed Discharge]: Discharged from Bed {bed.name} (Room: {room_name}, Floor: {floor_name}) on {utc_now().strftime('%Y-%m-%d')}. Discharge Notes: {data.dischargeNotes or 'None'}"
        patient.medical_history = f"{patient.medical_history or ''}{discharge_note}".strip()

        floor_id = bed.room.floor_id if bed.room else None
        room_id = bed.room_id
        patient_id = patient.id

        bed.status = "Available"
        bed.patient_id = None
        bed.patient = None
        bed.allocation_time = None
        bed.admission_date = None

        from app.models.appointment_model import Appointment
        from app.core.constants import AdmissionStatus
        from sqlalchemy import select, desc
        app_stmt = (
            select(Appointment)
            .where(
                Appointment.patient_id == patient_id,
                Appointment.admission_status == AdmissionStatus.ADMITTED,
            )
            .order_by(desc(Appointment.id))
            .limit(1)
        )
        app_res = await self.db.execute(app_stmt)
        patient_app = app_res.scalar_one_or_none()
        if patient_app:
            patient_app.admission_status = AdmissionStatus.DISCHARGED

        await self.db.flush()

        log = BedActivityLog(
            type="release",
            message=f"Patient {patient.first_name} {patient.last_name} discharged and released from Bed {bed.name}.",
            floor_id=floor_id,
            room_id=room_id,
            bed_id=bed.id,
            patient_id=patient_id,
        )
        await self.repo.create_activity_log(log)

        return await self.get_bed(bed.id)

    async def transfer_bed(self, data: BedTransferRequest) -> Bed:
        if data.sourceBedId == data.targetBedId:
            raise BadRequestException("Source and target beds cannot be the same.")

        source_bed = await self.get_bed(data.sourceBedId)
        if source_bed.status == "Maintenance":
            raise BadRequestException(f"Source bed '{source_bed.name}' is under maintenance.")
        elif source_bed.status == "Cleaning":
            raise BadRequestException(f"Source bed '{source_bed.name}' is currently under cleaning.")
        elif source_bed.status in ("Inactive", "Blocked", "Unavailable", "Reserved"):
            raise BadRequestException(f"Source bed '{source_bed.name}' is currently unavailable.")
        elif source_bed.status != "Occupied" or not source_bed.patient_id:
            raise BadRequestException(f"Source bed '{source_bed.name}' is not occupied.")

        target_bed = await self.get_bed(data.targetBedId)
        if target_bed.status == "Occupied":
            raise BadRequestException(f"Target bed '{target_bed.name}' is already occupied.")
        elif target_bed.status == "Maintenance":
            raise BadRequestException(f"Target bed '{target_bed.name}' is under maintenance.")
        elif target_bed.status == "Cleaning":
            raise BadRequestException(f"Target bed '{target_bed.name}' is currently under cleaning.")
        elif target_bed.status in ("Inactive", "Blocked", "Unavailable", "Reserved") or target_bed.status != "Available":
            raise BadRequestException(f"Target bed '{target_bed.name}' is currently unavailable.")

        patient = await self.get_patient(source_bed.patient_id)

        allocation_time = source_bed.allocation_time
        admission_date = source_bed.admission_date
        source_room_name = source_bed.room.name if source_bed.room else ""
        target_room_name = target_bed.room.name if target_bed.room else ""

        target_bed.status = "Occupied"
        target_bed.patient_id = patient.id
        target_bed.patient = patient
        target_bed.allocation_time = allocation_time
        target_bed.admission_date = admission_date

        source_bed.status = "Available"
        source_bed.patient_id = None
        source_bed.patient = None
        source_bed.allocation_time = None
        source_bed.admission_date = None

        old_room_name = source_bed.room.name if source_bed.room else "None"
        old_floor_name = source_bed.room.floor.name if source_bed.room and source_bed.room.floor else "None"
        new_room_name = target_bed.room.name if target_bed.room else "None"
        new_floor_name = target_bed.room.floor.name if target_bed.room and target_bed.room.floor else "None"

        transfer_note = f"\n[Bed Transfer]: Transferred from Bed {source_bed.name} to Bed {target_bed.name} on {utc_now().strftime('%Y-%m-%d')}. From Room {old_room_name}, Floor {old_floor_name} to Room {new_room_name}, Floor {new_floor_name}"
        patient.medical_history = f"{patient.medical_history or ''}{transfer_note}".strip()

        await self.db.flush()

        log = BedActivityLog(
            type="transfer",
            message=(
                f"Patient {patient.first_name} {patient.last_name} transferred from Bed {source_bed.name} ({source_room_name}) "
                f"to Bed {target_bed.name} ({target_room_name})."
            ),
            floor_id=target_bed.room.floor_id if target_bed.room else None,
            room_id=target_bed.room_id,
            bed_id=target_bed.id,
            patient_id=patient.id,
        )
        await self.repo.create_activity_log(log)

        return await self.get_bed(target_bed.id)

    # Activity Log Services
    async def list_activity_logs(self, limit: int = 50) -> List[BedActivityLog]:
        return await self.repo.list_activity_logs(limit)

    # Analytics Services
    async def get_analytics_summary(self) -> BedAnalyticsSummaryResponse:
        total_floors = await self.repo.count_floors()
        total_rooms = await self.repo.count_rooms()
        total_beds = await self.repo.count_beds()
        occupied_beds = await self.repo.count_occupied_beds()
        available_beds = await self.repo.count_available_beds()
        reserved_beds = await self.repo.count_reserved_beds()
        maint_clean_beds = await self.repo.count_maint_clean_beds()

        utilization_percentage = 0.0
        if total_beds > 0:
            utilization_percentage = round((occupied_beds / total_beds) * 100, 2)

        return BedAnalyticsSummaryResponse(
            total_floors=total_floors,
            total_rooms=total_rooms,
            total_beds=total_beds,
            occupied_beds=occupied_beds,
            available_beds=available_beds,
            reserved_beds=reserved_beds,
            maint_clean_beds=maint_clean_beds,
            utilization_percentage=utilization_percentage,
        )


    async def get_icu_analytics(self) -> ICUAnalyticsResponse:
        total, occupied, available = await self.repo.get_icu_bed_stats()

        utilization_percentage = 0.0
        if total > 0:
            utilization_percentage = round((occupied / total) * 100, 2)

        return ICUAnalyticsResponse(
            total_icu_beds=total,
            occupied_icu_beds=occupied,
            available_icu_beds=available,
            icu_utilization_percentage=utilization_percentage,
        )

    # Housekeeping & Cleaning Lifecycle Services
    async def get_cleaning_queue(self) -> List[Bed]:
        result = await self.db.execute(
            select(Bed)
            .where(Bed.status == BedStatus.CLEANING.value)
            .options(
                selectinload(Bed.room).selectinload(Room.floor)
            )
        )
        return list(result.scalars().all())

    async def mark_cleaning_complete(self, bed_id: int, user_id: int, notes: str | None = None) -> Bed:
        bed = await self.get_bed(bed_id)
        if bed.status != BedStatus.CLEANING.value:
            raise BadRequestException(f"Bed is not in 'Cleaning' status (Current status: {bed.status})")

        bed.status = BedStatus.AVAILABLE.value
        bed.patient_id = None
        bed.patient = None
        bed.allocation_time = None
        bed.admission_date = None

        log = BedActivityLog(
            type="maintenance",
            message=f"Housekeeping sanitization completed for Bed {bed.name}. Status set to Available.{(' Notes: ' + notes) if notes else ''}",
            floor_id=bed.room.floor_id if bed.room else None,
            room_id=bed.room_id,
            bed_id=bed.id,
        )
        await self.repo.create_activity_log(log)
        await self.db.flush()
        return bed

