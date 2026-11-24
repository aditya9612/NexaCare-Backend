import asyncio
import json
import time
from typing import Optional, Set
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException
from app.core.logger import logger
from app.repositories.module_repository import ModuleRepository
from app.utils.helpers import utc_now
from app.utils.redis_service import get_redis


FOUNDATIONAL_MODULES = [
    "PATIENT_MGMT",
    "DOCTOR_MGMT",
    "NURSE_MGMT",
    "STAFF_MGMT",
    "APPOINTMENTS",
    "BILLING",
    "PHARMACY",
    "LABORATORY",
    "INVENTORY",
    "BED_MGMT",
    "ICU_TELEMETRY",
    "REPORTS",
    "SETTINGS",
    "NOTIFICATIONS",
]

COMMERCIAL_MODULES = [
    "VOICE_REMIND",
    "VOICE_ASSISTANT",
    "AI_ASSISTANT",
    "WHATSAPP",
]

ALL_MODULES = FOUNDATIONAL_MODULES + COMMERCIAL_MODULES

PREREQUISITES: dict[str, list[str]] = {
    "APPOINTMENTS": ["PATIENT_MGMT", "DOCTOR_MGMT"],
    "BED_MGMT": ["PATIENT_MGMT"],
    "ICU_TELEMETRY": ["BED_MGMT", "PATIENT_MGMT"],
    "BILLING": ["PATIENT_MGMT"],
    "PHARMACY": ["INVENTORY", "PATIENT_MGMT"],
    "LABORATORY": ["PATIENT_MGMT"],
    "VOICE_REMIND": ["APPOINTMENTS"],
    "VOICE_ASSISTANT": ["VOICE_REMIND"],
    "AI_ASSISTANT": ["PATIENT_MGMT"],
    "WHATSAPP": ["PATIENT_MGMT"],
}

RESOURCE_MODULE_MAP: dict[str, str] = {
    "patients": "PATIENT_MGMT",
    "clinical_records": "PATIENT_MGMT",
    "patient_documents": "PATIENT_MGMT",
    "vitals": "PATIENT_MGMT",
    "doctors": "DOCTOR_MGMT",
    "doctor_schedules": "DOCTOR_MGMT",
    "nurses": "NURSE_MGMT",
    "nurse": "NURSE_MGMT",
    "nurse_stations": "NURSE_MGMT",
    "staff": "STAFF_MGMT",
    "departments": "STAFF_MGMT",
    "appointments": "APPOINTMENTS",
    "tokens": "APPOINTMENTS",
    "queues": "APPOINTMENTS",
    "discharges": "APPOINTMENTS",
    "billing": "BILLING",
    "invoices": "BILLING",
    "payments": "BILLING",
    "transactions": "BILLING",
    "tariffs": "BILLING",
    "pharmacy": "PHARMACY",
    "prescriptions": "PHARMACY",
    "medicines": "PHARMACY",
    "lab": "LABORATORY",
    "lab_orders": "LABORATORY",
    "lab_reports": "LABORATORY",
    "inventory": "INVENTORY",
    "vendors": "INVENTORY",
    "beds": "BED_MGMT",
    "bed_allocation": "BED_MGMT",
    "icu": "ICU_TELEMETRY",
    "icu_telemetry": "ICU_TELEMETRY",
    "reports": "REPORTS",
    "analytics": "REPORTS",
    "dashboard": "REPORTS",
    "settings": "SETTINGS",
    "users": "SETTINGS",
    "roles": "SETTINGS",
    "permissions": "SETTINGS",
    "admin": "SETTINGS",
    "notifications": "NOTIFICATIONS",
    "voice_reminder": "VOICE_REMIND",
    "voice_assistant": "VOICE_ASSISTANT",
    "ai": "AI_ASSISTANT",
    "ai_chat": "AI_ASSISTANT",
    "whatsapp": "WHATSAPP",
    "expenses": "INVENTORY",
    "expense": "INVENTORY",
}


class L1ModuleCacheEntry:
    def __init__(self, modules: set[str], version: int):
        self.modules = modules
        self.version = version
        self.cached_at = time.monotonic()


# Local in-process memory cache: hospital_id -> L1ModuleCacheEntry
_l1_module_cache: dict[int, L1ModuleCacheEntry] = {}
L1_TTL_SECONDS = 15.0


class ModuleService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ModuleRepository(db)

    async def get_active_modules(self, hospital_id: int) -> set[str]:
        """
        Retrieves active modules for a hospital using two-tier caching:
        Tier 1: L1 local process memory (15s hard TTL)
        Tier 2: L2 Redis with atomic version checking (150ms timeout fail-fast)
        Tier 3: PostgreSQL/MySQL database query with grandfathered fallback
        """
        now = time.monotonic()
        l1 = _l1_module_cache.get(hospital_id)
        if l1 and (now - l1.cached_at) < L1_TTL_SECONDS:
            return l1.modules

        # Try Tier 2: Redis
        redis = await get_redis()
        current_version = 0
        if redis:
            try:
                pipe = redis.pipeline()
                pipe.get(f"hosp_ver:{hospital_id}")
                pipe.smembers(f"hosp:{hospital_id}:modules")
                ver_raw, members_raw = await asyncio.wait_for(pipe.execute(), timeout=0.15)
                if ver_raw:
                    current_version = int(ver_raw)
                if members_raw:
                    active_mods = {m.decode() if isinstance(m, bytes) else str(m) for m in members_raw}
                    _l1_module_cache[hospital_id] = L1ModuleCacheEntry(active_mods, current_version)
                    return active_mods
            except Exception as exc:
                logger.warning("Redis L2 read error for hospital %s: %s", hospital_id, exc)

        # Fallback Tier 3: Database
        db_mods = await self.repo.get_active_module_codes(hospital_id)
        if not db_mods:
            # If no rows exist yet for this hospital, safely grandfather foundational modules
            db_mods = set(FOUNDATIONAL_MODULES)

        # Update L1
        _l1_module_cache[hospital_id] = L1ModuleCacheEntry(db_mods, current_version)

        # Asynchronously update L2 Redis if available
        if redis:
            try:
                pipe = redis.pipeline()
                key = f"hosp:{hospital_id}:modules"
                pipe.delete(key)
                if db_mods:
                    pipe.sadd(key, *list(db_mods))
                    pipe.expire(key, 3600)
                await asyncio.wait_for(pipe.execute(), timeout=0.20)
            except Exception as exc:
                logger.warning("Failed to populate Redis L2 cache for hospital %s: %s", hospital_id, exc)

        return db_mods

    async def is_module_active(self, hospital_id: int | None, module_code: str) -> bool:
        """
        Returns True if the specified module is active for the hospital.
        Global requests (hospital_id is None) always return True.
        """
        if hospital_id is None:
            return True
        active_mods = await self.get_active_modules(hospital_id)
        return module_code in active_mods

    def validate_prerequisites(self, target_module_code: str, currently_active: set[str]) -> None:
        """
        Validates the DAG prerequisites for activating a module.
        Raises BadRequestException if any required prerequisite is inactive.
        """
        required = PREREQUISITES.get(target_module_code, [])
        missing = [req for req in required if req not in currently_active]
        if missing:
            raise BadRequestException(
                f"Cannot activate module '{target_module_code}': Missing required prerequisites: {', '.join(missing)}"
            )

    async def set_hospital_module_status(
        self,
        hospital_id: int,
        module_code: str,
        is_active: bool,
        status: str = "ACTIVE",
    ) -> None:
        """
        Activates or deactivates a module for a hospital, validating prerequisites,
        updating the database, and immediately invalidating L1 and L2 caches.
        """
        if module_code not in ALL_MODULES:
            raise BadRequestException(f"Invalid module code: '{module_code}'")

        if is_active:
            active_now = await self.get_active_modules(hospital_id)
            self.validate_prerequisites(module_code, active_now)

        await self.repo.set_hospital_module_status(
            hospital_id=hospital_id,
            module_code=module_code,
            is_active=is_active,
            status=status,
        )

        await self.invalidate_cache(hospital_id)

    async def invalidate_cache(self, hospital_id: int) -> None:
        """
        Atomically increments version counter and purges L1 and L2 caches.
        """
        # Purge local L1
        _l1_module_cache.pop(hospital_id, None)

        # Invalidate L2 Redis
        redis = await get_redis()
        if redis:
            try:
                pipe = redis.pipeline()
                pipe.incr(f"hosp_ver:{hospital_id}")
                pipe.delete(f"hosp:{hospital_id}:modules")
                pipe.publish(
                    "hms:cache:flush",
                    json.dumps({"type": "MODULE_CACHE_FLUSH", "hospital_id": hospital_id}),
                )
                await asyncio.wait_for(pipe.execute(), timeout=0.20)
            except Exception as exc:
                logger.warning("Redis cache invalidation failed for hospital %s: %s", hospital_id, exc)

    @classmethod
    def get_module_for_resource(cls, resource: str) -> str | None:
        """
        Returns the canonical module owning a resource, or None if resource is not module-gated.
        """
        return RESOURCE_MODULE_MAP.get(resource)
