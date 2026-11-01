import sys
import os
import asyncio
import uuid
import pytest
from io import BytesIO
from PIL import Image as PILImage
from fastapi import UploadFile
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, delete

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from app.main import app
from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.core.dependencies import get_current_active_user, get_current_user
from app.core.exceptions import BadRequestException
from app.models.hospital_model import Hospital
from app.models.appointment_model import Appointment
from app.models.patient_model import Patient
from app.models.doctor_model import Doctor
from app.services.hospital_service import HospitalService
from app.services.appointment_service import AppointmentService
from app.services.doctor_service import save_doctor_image
from app.utils.file_upload import save_upload_file, save_upload
from app.utils.helpers import get_today_ist, utc_now


@pytest.fixture(autouse=True)
async def cleanup_engine():
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    await engine.dispose()
    yield
    await engine.dispose()


def _make_dummy_image(format="PNG"):
    buf = BytesIO()
    img = PILImage.new("RGB", (64, 64), color="red")
    img.save(buf, format=format)
    buf.seek(0)
    return buf.getvalue()


def _make_fake_user(user_id: int, hospital_id: int | None = None, role_name: str = "Super Admin"):
    class FakeRole:
        name = role_name

    class FakeUser:
        def __init__(self):
            self.id = user_id
            self.role_id = 1
            self.hospital_id = hospital_id
            self.active_hospital_id = None
            self.is_active = True
            self.is_verified = True
            self.email = f"user_{user_id}@test.com"
            self.role = FakeRole()

    return FakeUser()


@pytest.mark.asyncio
async def test_hospital_logo_upload_destination_and_db_path():
    """Verify hospital logo is saved in app/uploads/hospitals/ and Hospital.logo_path is updated."""
    uid = uuid.uuid4().hex[:8]
    files_to_clean = []
    hosp_id = None

    async with AsyncSessionLocal() as db:
        try:
            hosp = Hospital(
                name=f"Logo Test Hosp {uid}",
                email=f"logo_{uid}@hosp.com",
                phone="9876543210",
                address="100 Logo Way",
                is_active=True,
            )
            db.add(hosp)
            await db.commit()
            await db.refresh(hosp)
            hosp_id = hosp.id

            img_bytes = _make_dummy_image("PNG")
            upload_file = UploadFile(
                file=BytesIO(img_bytes),
                filename="hospital_brand.png",
                headers={"content-type": "image/png"},
            )

            service = HospitalService(db)
            res = await service.upload_logo(id=hosp.id, file=upload_file, user_id=1)
            files_to_clean.append(res.logo_path)

            # 1. Hospital logo is saved inside app/uploads/hospitals/
            assert res.logo_path is not None
            assert "app/uploads/hospitals/" in res.logo_path or "app/uploads\\hospitals" in res.logo_path
            assert "app/uploads/patients/" not in res.logo_path
            assert os.path.exists(res.logo_path)

            # 2. Hospital.logo_path in DB stores the correct path
            await db.refresh(hosp)
            assert hosp.logo_path == res.logo_path
        finally:
            for f in files_to_clean:
                if f and os.path.exists(f):
                    try:
                        os.remove(f)
                    except Exception:
                        pass
            if hosp_id:
                await db.execute(delete(Hospital).where(Hospital.id == hosp_id))
                await db.commit()


@pytest.mark.asyncio
async def test_patient_and_doctor_upload_destinations_preserved():
    """Verify patient upload uses patients directory and doctor upload uses doctors directory."""
    files_to_clean = []
    try:
        # 3. Patient upload still uses the patients directory
        patient_img = _make_dummy_image("PNG")
        patient_file = UploadFile(
            file=BytesIO(patient_img),
            filename="patient_doc.png",
            headers={"content-type": "image/png"},
        )
        patient_path = await save_upload_file(patient_file, settings.UPLOAD_DIR)
        files_to_clean.append(patient_path)

        assert "app/uploads/patients/" in patient_path or "app/uploads\\patients" in patient_path
        assert os.path.exists(patient_path)

        # 4. Existing doctor upload behavior remains unchanged
        doctor_img = _make_dummy_image("JPEG")
        doctor_file = UploadFile(
            file=BytesIO(doctor_img),
            filename="doctor_avatar.jpg",
            headers={"content-type": "image/jpeg"},
        )
        doctor_path = await save_doctor_image(doctor_file)
        files_to_clean.append(doctor_path)

        assert "app/uploads/doctors/" in doctor_path or "app/uploads\\doctors" in doctor_path
        assert os.path.exists(doctor_path)
    finally:
        for f in files_to_clean:
            if f and os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass


@pytest.mark.asyncio
async def test_unsupported_file_extensions_rejected():
    """Verify unsupported file extensions are rejected by upload_logo."""
    uid = uuid.uuid4().hex[:8]
    hosp_id = None

    async with AsyncSessionLocal() as db:
        try:
            hosp = Hospital(
                name=f"Reject Test Hosp {uid}",
                email=f"reject_{uid}@hosp.com",
                is_active=True,
            )
            db.add(hosp)
            await db.commit()
            await db.refresh(hosp)
            hosp_id = hosp.id

            service = HospitalService(db)

            # Test .pdf rejection
            pdf_file = UploadFile(file=BytesIO(b"%PDF-1.4 test"), filename="document.pdf")
            with pytest.raises(BadRequestException) as exc:
                await service.upload_logo(id=hosp.id, file=pdf_file, user_id=1)
            assert "File format not supported" in str(exc.value)

            # Test .exe rejection
            exe_file = UploadFile(file=BytesIO(b"MZ test"), filename="bad.exe")
            with pytest.raises(BadRequestException):
                await service.upload_logo(id=hosp.id, file=exe_file, user_id=1)

            # Test .txt rejection
            txt_file = UploadFile(file=BytesIO(b"plain text"), filename="notes.txt")
            with pytest.raises(BadRequestException):
                await service.upload_logo(id=hosp.id, file=txt_file, user_id=1)
        finally:
            if hosp_id:
                await db.execute(delete(Hospital).where(Hospital.id == hosp_id))
                await db.commit()


@pytest.mark.asyncio
async def test_replacing_existing_hospital_logo_cleans_up_old_file():
    """Verify replacing an existing hospital logo deletes the old file and saves the new one."""
    uid = uuid.uuid4().hex[:8]
    files_to_clean = []
    hosp_id = None

    async with AsyncSessionLocal() as db:
        try:
            hosp = Hospital(
                name=f"Cleanup Hosp {uid}",
                email=f"cleanup_{uid}@hosp.com",
                is_active=True,
            )
            db.add(hosp)
            await db.commit()
            await db.refresh(hosp)
            hosp_id = hosp.id

            service = HospitalService(db)

            # 1. Upload Logo 1
            f1 = UploadFile(file=BytesIO(_make_dummy_image("PNG")), filename="logo_v1.png")
            res1 = await service.upload_logo(id=hosp.id, file=f1, user_id=1)
            path1 = res1.logo_path
            files_to_clean.append(path1)

            assert os.path.exists(path1)
            assert "app/uploads/hospitals/" in path1 or "app/uploads\\hospitals" in path1

            # 2. Upload Logo 2 (Replacement)
            f2 = UploadFile(file=BytesIO(_make_dummy_image("JPEG")), filename="logo_v2.jpg")
            res2 = await service.upload_logo(id=hosp.id, file=f2, user_id=1)
            path2 = res2.logo_path
            files_to_clean.append(path2)

            assert os.path.exists(path2)
            assert path1 != path2
            # 6. Old file must be cleaned up from disk
            assert not os.path.exists(path1)

            await db.refresh(hosp)
            assert hosp.logo_path == path2
        finally:
            for f in files_to_clean:
                if f and os.path.exists(f):
                    try:
                        os.remove(f)
                    except Exception:
                        pass
            if hosp_id:
                await db.execute(delete(Hospital).where(Hospital.id == hosp_id))
                await db.commit()


@pytest.mark.asyncio
async def test_pdf_export_renders_actual_uploaded_logo_and_fallback():
    """Verify PDF export embeds actual uploaded logo, and fallback is used when no logo exists."""
    uid = uuid.uuid4().hex[:8]
    today = get_today_ist()
    files_to_clean = []
    hosp_with_logo_id = None
    hosp_no_logo_id = None

    async with AsyncSessionLocal() as db:
        try:
            # 1. Hospital with custom uploaded logo
            hosp1 = Hospital(
                name=f"Custom Logo Hosp {uid}",
                email=f"cust_{uid}@hosp.com",
                phone="1234567890",
                address="100 Brand Blvd",
                is_active=True,
            )
            # 2. Hospital without logo
            hosp2 = Hospital(
                name=f"Fallback Hosp {uid}",
                email=f"fall_{uid}@hosp.com",
                phone="0987654321",
                address="200 Default Ave",
                is_active=True,
                logo_path=None,
            )
            db.add_all([hosp1, hosp2])
            await db.commit()
            await db.refresh(hosp1)
            await db.refresh(hosp2)
            hosp_with_logo_id = hosp1.id
            hosp_no_logo_id = hosp2.id

            # Upload real logo to hosp1
            service_h = HospitalService(db)
            logo_f = UploadFile(file=BytesIO(_make_dummy_image("PNG")), filename="real_logo.png")
            upload_res = await service_h.upload_logo(id=hosp1.id, file=logo_f, user_id=1)
            files_to_clean.append(upload_res.logo_path)
            assert os.path.exists(upload_res.logo_path)
            assert "app/uploads/hospitals/" in upload_res.logo_path or "app/uploads\\hospitals" in upload_res.logo_path

            # Create patient, doctor, and appointment in hosp1
            doc1 = Doctor(
                first_name=f"Doc_{uid}",
                last_name="Test",
                doctor_code=f"D_{uid}"[:50],
                license_number=f"L_{uid}"[:100],
                specialization="General",
                hospital_id=hosp1.id,
            )
            pat1 = Patient(
                first_name=f"Pat_{uid}",
                last_name="Test",
                patient_code=f"P_{uid}"[:50],
                hospital_id=hosp1.id,
                gender="Female",
            )
            db.add_all([doc1, pat1])
            await db.flush()

            apt1 = Appointment(
                appointment_number=f"APT_LOGO_{uid}",
                patient_id=pat1.id,
                doctor_id=doc1.id,
                hospital_id=hosp1.id,
                appointment_date=today,
                appointment_time=utc_now().time(),
                appointment_status="Confirmed",
            )
            db.add(apt1)
            await db.commit()

            # 7. PDF export renders the selected hospital's actual uploaded logo
            super_admin = _make_fake_user(user_id=1, hospital_id=None, role_name="Super Admin")
            appt_service = AppointmentService(db)
            pdf_bytes_custom, media_custom = await appt_service.export_appointments(
                format_type="pdf", current_user=super_admin, x_hospital_id=hosp1.id
            )
            assert media_custom == "application/pdf"
            assert len(pdf_bytes_custom) > 1000
            assert pdf_bytes_custom.startswith(b"%PDF")

            # 8. Missing custom logo uses the existing NexaCare fallback
            pdf_bytes_fallback, media_fallback = await appt_service.export_appointments(
                format_type="pdf", current_user=super_admin, x_hospital_id=hosp2.id
            )
            assert media_fallback == "application/pdf"
            assert len(pdf_bytes_fallback) > 1000
            assert pdf_bytes_fallback.startswith(b"%PDF")
        finally:
            for f in files_to_clean:
                if f and os.path.exists(f):
                    try:
                        os.remove(f)
                    except Exception:
                        pass
            if hosp_with_logo_id:
                await db.execute(delete(Appointment).where(Appointment.hospital_id == hosp_with_logo_id))
                await db.execute(delete(Doctor).where(Doctor.hospital_id == hosp_with_logo_id))
                await db.execute(delete(Patient).where(Patient.hospital_id == hosp_with_logo_id))
                await db.execute(delete(Hospital).where(Hospital.id == hosp_with_logo_id))
            if hosp_no_logo_id:
                await db.execute(delete(Hospital).where(Hospital.id == hosp_no_logo_id))
            await db.commit()


@pytest.mark.asyncio
async def test_save_upload_file_path_containment_and_escape_rejection():
    """Verify upload helper path containment, root inputs, and directory escape rejections."""
    import tempfile
    from pathlib import Path
    from unittest.mock import patch
    from fastapi import HTTPException

    with tempfile.TemporaryDirectory() as tmp_root:
        with patch.object(settings, "UPLOAD_DIR", tmp_root):
            # 1. Path(settings.UPLOAD_DIR) root input -> preserves patients destination
            f1 = UploadFile(filename="doc1.png", file=BytesIO(_make_dummy_image("PNG")))
            p1 = await save_upload_file(f1, Path(settings.UPLOAD_DIR))
            assert "patients" in p1
            assert os.path.exists(p1)

            # 2. Trailing slash root input -> preserves patients destination
            f2 = UploadFile(filename="doc2.png", file=BytesIO(_make_dummy_image("PNG")))
            p2 = await save_upload_file(f2, settings.UPLOAD_DIR + "/")
            assert "patients" in p2
            assert os.path.exists(p2)

            # 3. Valid hospitals subdirectory
            f3 = UploadFile(filename="logo.png", file=BytesIO(_make_dummy_image("PNG")))
            p3 = await save_upload_file(f3, Path(settings.UPLOAD_DIR) / "hospitals", subfolder="hospitals")
            assert "hospitals" in p3
            assert os.path.exists(p3)

            # 4. Explicit subfolder='patient_reports' with upload_dir=None
            f4 = UploadFile(filename="report.png", file=BytesIO(_make_dummy_image("PNG")))
            p4 = await save_upload_file(f4, subfolder="patient_reports")
            assert "patient_reports" in p4
            assert os.path.exists(p4)

            # 5. Escapes outside upload root must be rejected with HTTP 400
            reject_targets = [
                "/etc",
                "C:/Windows/Temp",
                "../outside",
                "app/uploads/../outside",
                "D:/data",
            ]
            for target in reject_targets:
                bad_file = UploadFile(filename="evil.png", file=BytesIO(_make_dummy_image("PNG")))
                with pytest.raises(HTTPException) as exc_info:
                    await save_upload_file(bad_file, target)
                assert exc_info.value.status_code == 400
                assert "Invalid upload destination" in exc_info.value.detail

            # 6. Symlink pointing outside root must be rejected if symlinks supported
            outside_tmp = tempfile.mkdtemp()
            symlink_dir = os.path.join(tmp_root, "symlink_escape")
            try:
                os.symlink(outside_tmp, symlink_dir, target_is_directory=True)
                has_symlink = True
            except (OSError, NotImplementedError):
                has_symlink = False

            if has_symlink:
                sym_file = UploadFile(filename="sym.png", file=BytesIO(_make_dummy_image("PNG")))
                with pytest.raises(HTTPException) as exc_info:
                    await save_upload_file(sym_file, symlink_dir)
                assert exc_info.value.status_code == 400

            # 7. Verify no files were created in outside directories
            assert len(os.listdir(outside_tmp)) == 0
            try:
                os.rmdir(outside_tmp)
            except Exception:
                pass


@pytest.mark.asyncio
async def test_hospital_logo_atomic_replacement_failure_and_success():
    """Verify atomic hospital logo replacement: failures preserve old logo, DB failure cleans up new file."""
    import tempfile
    from datetime import datetime
    from unittest.mock import patch, AsyncMock

    with tempfile.TemporaryDirectory() as tmp_root:
        with patch.object(settings, "UPLOAD_DIR", tmp_root):
            hosp_dir = os.path.join(tmp_root, "hospitals")
            os.makedirs(hosp_dir, exist_ok=True)
            old_logo = os.path.join(hosp_dir, "existing_brand.png")
            with open(old_logo, "wb") as f:
                f.write(b"old_logo_bytes")

            hosp = Hospital(
                id=888,
                name="Atomic Hosp",
                email="atomic@hosp.com",
                logo_path=old_logo,
                is_active=True,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )

            mock_db = AsyncMock()
            service = HospitalService(mock_db)
            service.repo.get_by_id = AsyncMock(return_value=hosp)
            service.audit_repo.create = AsyncMock()

            # Case A: New upload failure (invalid file format) -> Old logo preserved
            bad_file = UploadFile(filename="bad.exe", file=BytesIO(b"MZ bad"))
            with pytest.raises(BadRequestException):
                await service.upload_logo(id=888, file=bad_file, user_id=1)
            assert os.path.exists(old_logo), "Old logo must survive upload validation failure"

            # Case B: DB update failure -> Old logo preserved, new file cleaned up
            service.repo.update = AsyncMock(side_effect=RuntimeError("DB connection failed"))
            good_file = UploadFile(filename="new_logo.png", file=BytesIO(_make_dummy_image("PNG")))
            with pytest.raises(RuntimeError):
                await service.upload_logo(id=888, file=good_file, user_id=1)
            assert os.path.exists(old_logo), "Old logo must survive DB update failure"
            assert hosp.logo_path == old_logo, "hospital.logo_path must be restored on failure"
            # Check only existing_brand.png remains in hosp_dir
            assert os.listdir(hosp_dir) == ["existing_brand.png"], "New file must be cleaned up on DB failure"

            # Case C: Successful update -> Old logo unlinked, new logo exists
            service.repo.update = AsyncMock(side_effect=lambda h: h)
            good_file2 = UploadFile(filename="new_logo2.png", file=BytesIO(_make_dummy_image("PNG")))
            res = await service.upload_logo(id=888, file=good_file2, user_id=1)
            assert not os.path.exists(old_logo), "Old logo must be removed after successful update"
            assert os.path.exists(res.logo_path), "New logo must exist on disk"
            assert hosp.logo_path == res.logo_path

