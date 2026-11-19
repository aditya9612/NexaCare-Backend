import base64
import mimetypes
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException, NotFoundException
from app.core.logger import logger
from app.models.user_model import User
from app.repositories.hospital_repository import HospitalRepository


@dataclass
class HospitalBrandingContext:
    """Context object encapsulating verified hospital branding and identity."""
    hospital_id: Optional[int] = None
    hospital_name: str = "NexaCare Hospital"
    hospital_address: Optional[str] = None
    hospital_phone: Optional[str] = None
    hospital_email: Optional[str] = None
    hospital_website: Optional[str] = None
    logo_path: Optional[str] = None          # Absolute OS path to image file (verified to exist, for ReportLab)
    logo_base64: Optional[str] = None        # Raw base64 string
    logo_data_uri: Optional[str] = None      # Ready-to-use data:image/...;base64,... URI (for HTML/Playwright)
    is_platform_branding: bool = False       # True if consolidated or default NexaCare identity
    report_title_prefix: str = ""            # Contextual title prefix
    contact_line: str = ""                   # Single-line formatted contact info for banners

    # Compatibility aliases
    logo_file_path: Optional[str] = None
    is_consolidated: Optional[bool] = None

    def __post_init__(self):
        if self.logo_file_path and not self.logo_path:
            self.logo_path = self.logo_file_path
        elif self.logo_path and not self.logo_file_path:
            self.logo_file_path = self.logo_path

        if self.is_consolidated is not None:
            self.is_platform_branding = self.is_consolidated
        else:
            self.is_consolidated = self.is_platform_branding

        if not self.contact_line:
            parts = []
            if self.hospital_address:
                parts.append(self.hospital_address.strip())
            if self.hospital_phone:
                parts.append(f"Phone: {self.hospital_phone.strip()}")
            if self.hospital_email:
                parts.append(f"Email: {self.hospital_email.strip()}")
            if self.hospital_website:
                parts.append(f"Web: {self.hospital_website.strip()}")
            self.contact_line = " • ".join(parts) if parts else "NexaCare Healthcare Management System" 

    @property
    def address(self) -> Optional[str]:
        return self.hospital_address

    @property
    def phone(self) -> Optional[str]:
        return self.hospital_phone

    @property
    def email(self) -> Optional[str]:
        return self.hospital_email

    @property
    def website(self) -> Optional[str]:
        return self.hospital_website


# In-memory cache with TTL (seconds) to eliminate redundant disk I/O and base64 conversions
_BRANDING_CACHE: dict[Any, tuple[float, HospitalBrandingContext]] = {}
_CACHE_TTL_SECONDS = 60.0


def clear_branding_cache(hospital_id: Optional[int] = None) -> None:
    """Invalidates branding cache for a specific hospital or completely."""
    global _BRANDING_CACHE
    if hospital_id is not None:
        _BRANDING_CACHE.pop(hospital_id, None)
    else:
        _BRANDING_CACHE.clear()


class BrandingResolverService:
    """
    Centralized service responsible for resolving, validating, and formatting
    multi-tenant hospital branding across all document generation engines.
    """

    def __init__(self, db: Optional[AsyncSession] = None):
        self.db = db

    @staticmethod
    def _resolve_image_base64_and_path(raw_path: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Takes a potential file path or candidate, verifies existence, and returns
        (absolute_file_path, raw_base64, data_uri).
        """
        if not raw_path:
            return None, None, None

        cleaned = str(raw_path).replace("\\", "/").strip()
        candidates = [
            cleaned,
            os.path.abspath(cleaned).replace("\\", "/"),
            os.path.join(os.getcwd(), cleaned).replace("\\", "/"),
            os.path.join("app", cleaned).replace("\\", "/"),
            os.path.abspath(os.path.join("app", cleaned)).replace("\\", "/"),
        ]

        # If path starts with uploads/, check with app/uploads/ and vice-versa
        if cleaned.startswith("uploads/"):
            candidates.append(os.path.abspath(os.path.join("app", cleaned)).replace("\\", "/"))
        elif cleaned.startswith("app/uploads/"):
            candidates.append(os.path.abspath(cleaned[4:]).replace("\\", "/"))

        matched_path = None
        for cand in candidates:
            if os.path.isfile(cand):
                matched_path = os.path.abspath(cand).replace("\\", "/")
                break

        if not matched_path:
            return None, None, None

        try:
            with open(matched_path, "rb") as f:
                content = f.read()
            if not content:
                return None, None, None

            mime_type, _ = mimetypes.guess_type(matched_path)
            if not mime_type:
                mime_type = "image/png"

            b64_str = base64.b64encode(content).decode("utf-8")
            data_uri = f"data:{mime_type};base64,{b64_str}"
            return matched_path, b64_str, data_uri
        except Exception as e:
            logger.warning("Failed to read/encode logo from %s: %s", matched_path, e)
            return None, None, None

    @classmethod
    def _resolve_fallback_logo(cls) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """Resolves system default NexaCare logo from static directories."""
        for cand in ["app/static/images/logo.png", "app/static/logo.png"]:
            p, b64, uri = cls._resolve_image_base64_and_path(cand)
            if p:
                return p, b64, uri
        return None, None, None

    @staticmethod
    def _build_contact_line(
        address: Optional[str], phone: Optional[str], email: Optional[str], website: Optional[str]
    ) -> str:
        parts = []
        if address:
            parts.append(address.strip())
        if phone:
            parts.append(f"Phone: {phone.strip()}")
        if email:
            parts.append(f"Email: {email.strip()}")
        if website:
            parts.append(f"Web: {website.strip()}")
        return " • ".join(parts) if parts else "NexaCare Healthcare Management System"

    @classmethod
    async def resolve_branding(
        cls,
        db: Optional[Any] = None,
        current_user: Optional[Any] = None,
        hospital_id: Optional[int] = None,
        x_hospital_id: Optional[int] = None,
        **kwargs,
    ) -> HospitalBrandingContext:
        """
        Resolves tenant-authorized hospital branding context.
        Supports calling both as:
        - await BrandingResolverService.resolve_branding(db, current_user, hospital_id=...)
        - await BrandingResolverService(db).resolve_branding(current_user=..., hospital_id=...)
        """
        session = None
        if isinstance(db, BrandingResolverService):
            session = db.db
        elif db is not None and (hasattr(db, "execute") or hasattr(db, "get")):
            session = db
        elif db is not None:
            if hasattr(db, "role") or hasattr(db, "is_superuser"):
                current_user = db
            elif isinstance(db, int):
                hospital_id = db
        """
        Resolves tenant-authorized hospital branding context.

        Security rules:
        - If current_user is provided and is a non-super-admin, hospital_id MUST match current_user.hospital_id.
        - Super Admin may specify x_hospital_id or hospital_id. If omitted, consolidated branding is produced.
        """
        # 1. Enforce Tenant Authorization via current_user if provided
        effective_hosp_id = hospital_id or x_hospital_id

        if current_user is not None:
            role = getattr(current_user, "role", None)
            role_name = ""
            if hasattr(role, "name"):
                role_name = str(role.name).lower().strip()
            elif isinstance(role, str):
                role_name = role.lower().strip()
            elif getattr(current_user, "is_superuser", False):
                role_name = "super admin"

            role_norm = role_name.replace("_", " ").strip()

            if role_norm in ("super admin", "super_admin"):
                # Super Admin can scope to specified hospital or view consolidated
                if effective_hosp_id is None:
                    effective_hosp_id = getattr(current_user, "active_hospital_id", None)
            else:
                user_hosp_id = getattr(current_user, "hospital_id", None)
                if effective_hosp_id is not None and user_hosp_id is not None and effective_hosp_id != user_hosp_id:
                    raise ForbiddenException("Access denied: You cannot access branding or data for another hospital")
                effective_hosp_id = user_hosp_id

        # 2. Check Cache
        cache_key = effective_hosp_id
        now = time.time()
        if cache_key in _BRANDING_CACHE:
            ts, cached_ctx = _BRANDING_CACHE[cache_key]
            if now - ts < _CACHE_TTL_SECONDS:
                return cached_ctx

        # 3. Resolve Platform / Consolidated Branding if no hospital ID
        if not effective_hosp_id:
            fb_path, fb_b64, fb_uri = cls._resolve_fallback_logo()
            platform_ctx = HospitalBrandingContext(
                hospital_id=None,
                hospital_name="NexaCare Healthcare Network",
                hospital_address="Consolidated Network — All Hospitals",
                hospital_phone=None,
                hospital_email=None,
                hospital_website="www.nexacare.com",
                logo_path=fb_path,
                logo_base64=fb_b64,
                logo_data_uri=fb_uri,
                is_platform_branding=True,
                report_title_prefix="Consolidated",
                contact_line="NexaCare Healthcare Network • Enterprise Multi-Hospital System • www.nexacare.com",
            )
            _BRANDING_CACHE[None] = (now, platform_ctx)
            return platform_ctx

        # 4. Query Hospital Model
        hospital = None
        if session is not None:
            repo = HospitalRepository(session)
            hospital = await repo.get_by_id(effective_hosp_id)

        if not hospital:
            # If hospital not found in DB, use safe fallback with ID noted
            fb_path, fb_b64, fb_uri = cls._resolve_fallback_logo()
            fallback_ctx = HospitalBrandingContext(
                hospital_id=effective_hosp_id,
                hospital_name="NexaCare Hospital",
                hospital_address=None,
                hospital_phone=None,
                hospital_email=None,
                hospital_website="www.nexacare.com",
                logo_path=fb_path,
                logo_base64=fb_b64,
                logo_data_uri=fb_uri,
                is_platform_branding=True,
                report_title_prefix="Hospital Report",
                contact_line="NexaCare Hospital Management System",
            )
            return fallback_ctx

        # 5. Extract Hospital Fields
        hosp_name = (hospital.name or "NexaCare Hospital").strip()
        hosp_addr = hospital.address.strip() if hospital.address else None
        hosp_phone = hospital.phone.strip() if hospital.phone else None
        hosp_email = hospital.email.strip() if hospital.email else None
        hosp_web = hospital.website.strip() if getattr(hospital, "website", None) else None

        # 6. Resolve Hospital Logo with Fallback
        logo_attr = (
            getattr(hospital, "logo_path", None)
            or getattr(hospital, "logo", None)
            or getattr(hospital, "logo_url", None)
        )
        l_path, l_b64, l_uri = cls._resolve_image_base64_and_path(logo_attr)

        if not l_path:
            # Fall back to default logo
            l_path, l_b64, l_uri = cls._resolve_fallback_logo()

        contact_str = cls._build_contact_line(hosp_addr, hosp_phone, hosp_email, hosp_web)

        ctx = HospitalBrandingContext(
            hospital_id=hospital.id,
            hospital_name=hosp_name,
            hospital_address=hosp_addr,
            hospital_phone=hosp_phone,
            hospital_email=hosp_email,
            hospital_website=hosp_web,
            logo_path=l_path,
            logo_base64=l_b64,
            logo_data_uri=l_uri,
            is_platform_branding=False,
            report_title_prefix=hosp_name,
            contact_line=contact_str,
        )

        _BRANDING_CACHE[effective_hosp_id] = (now, ctx)
        return ctx
