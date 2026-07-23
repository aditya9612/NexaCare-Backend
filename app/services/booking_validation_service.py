from datetime import date, time
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.exceptions import ConflictException, NotFoundException, BadRequestException
from app.repositories.doctor_repository import DoctorRepository
from app.repositories.appointment_repository import AppointmentRepository
from app.services.settings_service import SettingsService
from app.services.booking_rules_resolver import BookingRulesResolver
from app.models.doctor_model import DoctorSchedule

class BookingValidationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.doctor_repo = DoctorRepository(db)
        self.appointment_repo = AppointmentRepository(db)

    async def validate(self, doctor_id: int, appointment_date: date, appointment_time: time = None, exclude_id=None):
        doctor = await self.doctor_repo.get_by_id(doctor_id)
        if not doctor:
            raise NotFoundException("Doctor not found")
            
        hospital_id = await self.doctor_repo.get_doctor_hospital_id(doctor_id)
        settings_dict = await SettingsService(self.db).get_appointment_settings(hospital_id)
        from app.models.appointment_setting import AppointmentSetting
        from datetime import time
        
        for field in ["working_start_time", "working_end_time", "lunch_start_time", "lunch_end_time"]:
            val = settings_dict.get(field)
            if isinstance(val, str):
                parts = val.split(":")
                settings_dict[field] = time(int(parts[0]), int(parts[1]), int(parts[2][:2]) if len(parts)>2 else 0)
                
        settings = AppointmentSetting(**settings_dict)
        
        self._validate_max_advance_booking(appointment_date, settings)
        
        schedules = await self._validate_schedule(doctor_id, appointment_date)
        
        rules = BookingRulesResolver.resolve(settings, appointment_date, schedules[0])
        self._validate_weekend(appointment_date.weekday(), rules)
        
        if appointment_time:
            valid_time = False
            for sched in schedules:
                sched_rules = BookingRulesResolver.resolve(settings, appointment_date, sched)
                if self._validate_working_hours(appointment_time, sched_rules):
                    if self._validate_lunch(appointment_time, sched_rules):
                        valid_time = True
                        break
            if not valid_time:
                raise ConflictException("Appointment time is outside working hours or during lunch break")
                
            await self._validate_conflict(doctor_id, appointment_date, appointment_time, rules, exclude_id)
            
        return rules

    def _validate_max_advance_booking(self, appointment_date: date, settings):
        from datetime import timedelta
        today = date.today()
        if appointment_date > today + timedelta(days=settings.max_advance_booking_days):
            raise BadRequestException(f"Cannot book more than {settings.max_advance_booking_days} days in advance")

    async def _validate_schedule(self, doctor_id: int, appointment_date: date):
        day_of_week = appointment_date.weekday()
        schedule_res = await self.db.execute(
            select(DoctorSchedule).where(
                DoctorSchedule.doctor_id == doctor_id,
                DoctorSchedule.day_of_week == day_of_week,
                DoctorSchedule.is_active.is_(True)
            )
        )
        schedules = schedule_res.scalars().all()
        if not schedules:
            raise ConflictException("Doctor is not scheduled to work on this day")
        return schedules

    def _validate_weekend(self, day_of_week: int, rules):
        if not rules.weekend_booking_enabled and day_of_week in (5, 6):
            raise ConflictException("Weekend booking is not enabled")

    def _validate_working_hours(self, appointment_time: time, sched_rules):
        return sched_rules.working_start_time <= appointment_time <= sched_rules.working_end_time

    def _validate_lunch(self, appointment_time: time, sched_rules):
        if sched_rules.lunch_break_enabled and sched_rules.lunch_start_time and sched_rules.lunch_end_time:
            if sched_rules.lunch_start_time <= appointment_time < sched_rules.lunch_end_time:
                return False
        return True

    async def _validate_conflict(self, doctor_id: int, appointment_date: date, appointment_time: time, rules, exclude_id=None):
        if rules.allow_overlapping:
            return
        if await self.appointment_repo.exists_conflict(doctor_id, appointment_date, appointment_time, exclude_id):
            raise ConflictException("Doctor already has an appointment at this slot")
