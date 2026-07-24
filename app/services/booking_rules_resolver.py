from dataclasses import dataclass
from datetime import date, time
from typing import Optional

from app.core.constants import OperationMode
from app.models.appointment_setting import AppointmentSetting
from app.models.doctor_model import DoctorSchedule


@dataclass
class AppointmentBookingRules:
    slot_duration_minutes: int
    working_start_time: time
    working_end_time: time
    lunch_break_enabled: bool
    lunch_start_time: Optional[time]
    lunch_end_time: Optional[time]
    buffer_between_slots_minutes: int
    allow_overlapping: bool
    max_advance_booking_days: int
    weekend_booking_enabled: bool
    operation_mode: OperationMode


class BookingRulesResolver:
    @staticmethod
    def resolve(
        settings: AppointmentSetting,
        target_date: date,
        doctor_schedule: Optional[DoctorSchedule] = None,
    ) -> AppointmentBookingRules:
        """
        Pure business logic resolver for Appointment Settings.
        Takes hospital settings, an optional doctor's schedule, and a target date,
        and returns the consolidated booking rules.
        """
        
        # 1. Enforce reserved operation modes
        if settings.operation_mode in (OperationMode.SHIFT_BASED, OperationMode.CUSTOM):
            from fastapi import HTTPException
            raise HTTPException(status_code=501, detail=f"{settings.operation_mode.value.upper()} mode is reserved for a future release.")

        # 2. Determine base working hours
        if settings.operation_mode == OperationMode.TWENTY_FOUR_SEVEN:
            base_start = time(0, 0)
            base_end = time(23, 59, 59)
        else:
            base_start = settings.working_start_time
            base_end = settings.working_end_time
            
        from datetime import timedelta, time as dt_time, datetime
        
        def to_time(val):
            if isinstance(val, timedelta):
                return (datetime.min + val).time()
            elif isinstance(val, str):
                parts = val.split(":")
                return dt_time(int(parts[0]), int(parts[1]), int(parts[2][:2]) if len(parts)>2 else 0)
            return val
            
        base_start = to_time(base_start)
        base_end = to_time(base_end)

        # 3. Trim to doctor's schedule (Hospital boundaries win)
        effective_start = base_start
        effective_end = base_end
        
        if doctor_schedule:
            # Doctor schedule is trimmed to the hospital's base working hours.
            # If Doctor starts earlier than hospital, they start when hospital opens.
            doc_start = doctor_schedule.start_time
            doc_end = doctor_schedule.end_time
            
            from datetime import timedelta, time as dt_time, datetime
            if isinstance(doc_start, timedelta):
                doc_start = (datetime.min + doc_start).time()
            elif isinstance(doc_start, str):
                parts = doc_start.split(":")
                doc_start = dt_time(int(parts[0]), int(parts[1]), int(parts[2][:2]) if len(parts)>2 else 0)
                
            if isinstance(doc_end, timedelta):
                doc_end = (datetime.min + doc_end).time()
            elif isinstance(doc_end, str):
                parts = doc_end.split(":")
                doc_end = dt_time(int(parts[0]), int(parts[1]), int(parts[2][:2]) if len(parts)>2 else 0)
            
            # Find intersection
            effective_start = max(base_start, doc_start)
            effective_end = min(base_end, doc_end)
            
            # If there is no overlap, effective_start > effective_end, which means no slots.
            if effective_start > effective_end:
                effective_start = base_start
                effective_end = base_start  # 0 duration
            
        return AppointmentBookingRules(
            slot_duration_minutes=settings.slot_duration_minutes,
            working_start_time=effective_start,
            working_end_time=effective_end,
            lunch_break_enabled=settings.lunch_break_enabled,
            lunch_start_time=to_time(settings.lunch_start_time),
            lunch_end_time=to_time(settings.lunch_end_time),
            buffer_between_slots_minutes=settings.buffer_between_slots_minutes,
            allow_overlapping=settings.allow_overlapping,
            max_advance_booking_days=settings.max_advance_booking_days,
            weekend_booking_enabled=settings.weekend_booking_enabled,
            operation_mode=settings.operation_mode,
        )
