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
        
        # 1. Normalize settings attributes
        if isinstance(settings, dict):
            op_mode = settings.get("operation_mode", OperationMode.FIXED_HOURS)
            ws_time = settings.get("working_start_time", time(9, 0))
            we_time = settings.get("working_end_time", time(18, 0))
            lunch_enabled = settings.get("lunch_break_enabled", False)
            lunch_start = settings.get("lunch_start_time")
            lunch_end = settings.get("lunch_end_time")
            slot_dur = settings.get("slot_duration_minutes", 30)
            buf = settings.get("buffer_between_slots_minutes", 0)
            allow_overlap = settings.get("allow_overlapping", False)
            max_adv = settings.get("max_advance_booking_days", 30)
            weekend_enabled = settings.get("weekend_booking_enabled", False)
        else:
            op_mode = settings.operation_mode
            ws_time = settings.working_start_time
            we_time = settings.working_end_time
            lunch_enabled = settings.lunch_break_enabled
            lunch_start = settings.lunch_start_time
            lunch_end = settings.lunch_end_time
            slot_dur = settings.slot_duration_minutes
            buf = settings.buffer_between_slots_minutes
            allow_overlap = settings.allow_overlapping
            max_adv = settings.max_advance_booking_days
            weekend_enabled = settings.weekend_booking_enabled

        if isinstance(op_mode, str):
            try:
                op_mode = OperationMode(op_mode)
            except ValueError:
                pass

        # 2. Enforce reserved operation modes
        if op_mode in (OperationMode.SHIFT_BASED, OperationMode.CUSTOM, "shift_based", "custom"):
            from fastapi import HTTPException
            mode_val = op_mode.value if hasattr(op_mode, "value") else str(op_mode)
            raise HTTPException(status_code=501, detail=f"{mode_val.upper()} mode is reserved for a future release.")

        # 3. Determine base working hours
        if op_mode in (OperationMode.TWENTY_FOUR_SEVEN, "twenty_four_seven"):
            base_start = time(0, 0)
            base_end = time(23, 59, 59)
        else:
            base_start = ws_time
            base_end = we_time
            
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

        # 4. Determine working hours and slot duration (Doctor's schedule takes precedence if provided)
        slot_duration = slot_dur
        if doctor_schedule:
            effective_start = to_time(doctor_schedule.start_time)
            effective_end = to_time(doctor_schedule.end_time)
            if doctor_schedule.slot_duration_minutes:
                slot_duration = doctor_schedule.slot_duration_minutes
        else:
            effective_start = base_start
            effective_end = base_end
            
        return AppointmentBookingRules(
            slot_duration_minutes=slot_duration,
            working_start_time=effective_start,
            working_end_time=effective_end,
            lunch_break_enabled=lunch_enabled,
            lunch_start_time=to_time(lunch_start),
            lunch_end_time=to_time(lunch_end),
            buffer_between_slots_minutes=buf,
            allow_overlapping=allow_overlap,
            max_advance_booking_days=max_adv,
            weekend_booking_enabled=weekend_enabled,
            operation_mode=op_mode if isinstance(op_mode, OperationMode) else OperationMode.FIXED_HOURS,
        )
