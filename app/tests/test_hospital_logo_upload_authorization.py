"""
Isolated Unit Tests for Hospital Logo Upload Multi-Role Authorization.

Tests cover:
1. Super Admin uploads for Hospital A (Allowed)
2. Super Admin uploads for Hospital B (Allowed)
3. Hospital Admin A uploads for Hospital A (Allowed)
4. Hospital Admin A requests Hospital B URL (403 Forbidden)
5. Hospital Admin without hospital_id (403 Forbidden)
6. Doctor uploads logo (403 Forbidden)
7. Staff / Receptionist uploads logo (403 Forbidden)
8. Invalid Hospital ID (404 Not Found)
9. Upload failure rollback preservation
10. Existing logo replacement cleanup preservation

NO database connection or mutation occurs (100% in-memory mocks / tempfiles).
"""

from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from httpx import AsyncClient, ASGITransport
from PIL import Image as PILImage

from app.main import app
from app.core.exceptions import ForbiddenException, NotFoundException
from app.api.v1.routes.super_admin_routes import require_hospital_logo_uploader
from app.core.dependencies import get_current_active_user, get_current_user, get_db, bearer_scheme
from app.schemas.hospital_schema import HospitalResponse

AUTH_HEADERS = {"Authorization": "Bearer fake-token"}


def _make_dummy_image(format="PNG"):
    buf = BytesIO()
    img = PILImage.new("RGB", (32, 32), color="blue")
    img.save(buf, format=format)
    buf.seek(0)
    return buf.getvalue()


def _make_user(user_id: int, role_name: str, hospital_id: int | None = None):
    class FakeRole:
        name = role_name

    class FakeUser:
        def __init__(self):
            self.id = user_id
            self.role_id = 1
            self.hospital_id = hospital_id
            self.is_active = True
            self.is_verified = True
            self.email = f"{role_name.lower().replace(' ', '_')}_{user_id}@test.com"
            self.role = FakeRole()

    return FakeUser()


# ==============================================================================
# 1. Direct Tests for require_hospital_logo_uploader Dependency
# ==============================================================================

@pytest.mark.asyncio
async def test_require_hospital_logo_uploader_allows_super_admin():
    user = _make_user(1, "Super Admin")
    res = await require_hospital_logo_uploader(user)
    assert res.id == 1

    # Also test snake_case role name
    user_snake = _make_user(2, "super_admin")
    res_snake = await require_hospital_logo_uploader(user_snake)
    assert res_snake.id == 2


@pytest.mark.asyncio
async def test_require_hospital_logo_uploader_allows_hospital_admin():
    user = _make_user(10, "Hospital Admin", hospital_id=101)
    res = await require_hospital_logo_uploader(user)
    assert res.id == 10

    # Also test snake_case role name
    user_snake = _make_user(11, "hospital_admin", hospital_id=101)
    res_snake = await require_hospital_logo_uploader(user_snake)
    assert res_snake.id == 11


@pytest.mark.asyncio
async def test_require_hospital_logo_uploader_rejects_doctor():
    user = _make_user(20, "Doctor", hospital_id=101)
    with pytest.raises(ForbiddenException) as exc:
        await require_hospital_logo_uploader(user)
    assert "Requires Super Admin or Hospital Admin role" in str(exc.value)


@pytest.mark.asyncio
async def test_require_hospital_logo_uploader_rejects_staff_and_other_roles():
    for role in ["Nurse", "Receptionist", "Accountant", "Pharmacist", "Lab Technician", "Patient"]:
        user = _make_user(30, role, hospital_id=101)
        with pytest.raises(ForbiddenException):
            await require_hospital_logo_uploader(user)


# ==============================================================================
# 2. HTTP Endpoint Multi-Role Integration Tests (In-Memory ASGI Client)
# ==============================================================================

@pytest.mark.asyncio
async def test_super_admin_uploads_for_hospital_a():
    """Scenario 1: Super Admin can upload logo for Hospital A (ID 101)."""
    super_admin = _make_user(1, "Super Admin", hospital_id=None)
    mock_db = AsyncMock()

    app.dependency_overrides[bearer_scheme] = lambda: MagicMock(credentials="fake-token")
    app.dependency_overrides[get_current_active_user] = lambda: super_admin
    app.dependency_overrides[get_current_user] = lambda: super_admin
    app.dependency_overrides[get_db] = lambda: mock_db

    mock_resp = HospitalResponse(
        id=101,
        name="Hospital A",
        email="hosp_a@test.com",
        phone="1234567890",
        address="100 Street A",
        website="https://hospa.com",
        logo_path="app/uploads/hospitals/logo_a.png",
        is_active=True,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )

    try:
        with patch("app.services.hospital_service.HospitalService.upload_logo", new_callable=AsyncMock) as mock_upload:
            mock_upload.return_value = mock_resp

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                files = {"file": ("logo.png", _make_dummy_image("PNG"), "image/png")}
                res = await ac.post("/api/v1/super-admin/hospitals/101/logo", files=files, headers=AUTH_HEADERS)

            assert res.status_code == 200, res.text
            data = res.json()["data"]
            assert data["id"] == 101
            assert data["logo_path"] == "app/uploads/hospitals/logo_a.png"
            mock_upload.assert_called_once()
            assert mock_upload.call_args[0][0] == 101  # effective_hospital_id
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_super_admin_uploads_for_hospital_b():
    """Scenario 2: Super Admin can upload logo for Hospital B (ID 202)."""
    super_admin = _make_user(1, "Super Admin", hospital_id=None)
    mock_db = AsyncMock()

    app.dependency_overrides[bearer_scheme] = lambda: MagicMock(credentials="fake-token")
    app.dependency_overrides[get_current_active_user] = lambda: super_admin
    app.dependency_overrides[get_current_user] = lambda: super_admin
    app.dependency_overrides[get_db] = lambda: mock_db

    mock_resp = HospitalResponse(
        id=202,
        name="Hospital B",
        email="hosp_b@test.com",
        phone="9876543210",
        address="200 Street B",
        website="https://hospb.com",
        logo_path="app/uploads/hospitals/logo_b.png",
        is_active=True,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )

    try:
        with patch("app.services.hospital_service.HospitalService.upload_logo", new_callable=AsyncMock) as mock_upload:
            mock_upload.return_value = mock_resp

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                files = {"file": ("logo_b.png", _make_dummy_image("PNG"), "image/png")}
                res = await ac.post("/api/v1/super-admin/hospitals/202/logo", files=files, headers=AUTH_HEADERS)

            assert res.status_code == 200, res.text
            data = res.json()["data"]
            assert data["id"] == 202
            mock_upload.assert_called_once()
            assert mock_upload.call_args[0][0] == 202
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_hospital_admin_uploads_for_own_hospital():
    """Scenario 3: Hospital Admin A (hospital_id 101) uploads for Hospital A (URL ID 101)."""
    hosp_admin = _make_user(10, "Hospital Admin", hospital_id=101)
    mock_db = AsyncMock()

    app.dependency_overrides[bearer_scheme] = lambda: MagicMock(credentials="fake-token")
    app.dependency_overrides[get_current_active_user] = lambda: hosp_admin
    app.dependency_overrides[get_current_user] = lambda: hosp_admin
    app.dependency_overrides[get_db] = lambda: mock_db

    mock_resp = HospitalResponse(
        id=101,
        name="Hospital A",
        email="hosp_a@test.com",
        phone="1234567890",
        address="100 Street A",
        website="https://hospa.com",
        logo_path="app/uploads/hospitals/logo_a.png",
        is_active=True,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )

    try:
        with patch("app.services.hospital_service.HospitalService.upload_logo", new_callable=AsyncMock) as mock_upload:
            mock_upload.return_value = mock_resp

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                files = {"file": ("logo_a.png", _make_dummy_image("PNG"), "image/png")}
                res = await ac.post("/api/v1/super-admin/hospitals/101/logo", files=files, headers=AUTH_HEADERS)

            assert res.status_code == 200, res.text
            data = res.json()["data"]
            assert data["id"] == 101
            mock_upload.assert_called_once()
            assert mock_upload.call_args[0][0] == 101
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_hospital_admin_requests_other_hospital_url_rejected():
    """Scenario 4: Hospital Admin A (hospital_id 101) requests Hospital B URL (URL ID 202) -> 403 Forbidden."""
    hosp_admin = _make_user(10, "Hospital Admin", hospital_id=101)
    mock_db = AsyncMock()

    app.dependency_overrides[bearer_scheme] = lambda: MagicMock(credentials="fake-token")
    app.dependency_overrides[get_current_active_user] = lambda: hosp_admin
    app.dependency_overrides[get_current_user] = lambda: hosp_admin
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with patch("app.services.hospital_service.HospitalService.upload_logo", new_callable=AsyncMock) as mock_upload:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                files = {"file": ("logo_b.png", _make_dummy_image("PNG"), "image/png")}
                res = await ac.post("/api/v1/super-admin/hospitals/202/logo", files=files, headers=AUTH_HEADERS)

            assert res.status_code == 403, res.text
            assert "Cannot upload logo for another hospital" in res.text
            mock_upload.assert_not_called()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_hospital_admin_without_hospital_id_rejected():
    """Scenario 5: Hospital Admin without hospital_id (hospital_id is None) -> 403 Forbidden."""
    hosp_admin = _make_user(12, "Hospital Admin", hospital_id=None)
    mock_db = AsyncMock()

    app.dependency_overrides[bearer_scheme] = lambda: MagicMock(credentials="fake-token")
    app.dependency_overrides[get_current_active_user] = lambda: hosp_admin
    app.dependency_overrides[get_current_user] = lambda: hosp_admin
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with patch("app.services.hospital_service.HospitalService.upload_logo", new_callable=AsyncMock) as mock_upload:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                files = {"file": ("logo.png", _make_dummy_image("PNG"), "image/png")}
                res = await ac.post("/api/v1/super-admin/hospitals/101/logo", files=files, headers=AUTH_HEADERS)

            assert res.status_code == 403, res.text
            assert "not associated with a valid hospital" in res.text
            mock_upload.assert_not_called()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_doctor_upload_rejected():
    """Scenario 6: Doctor cannot upload logo -> 403 Forbidden."""
    doctor = _make_user(20, "Doctor", hospital_id=101)
    mock_db = AsyncMock()

    app.dependency_overrides[bearer_scheme] = lambda: MagicMock(credentials="fake-token")
    app.dependency_overrides[get_current_active_user] = lambda: doctor
    app.dependency_overrides[get_current_user] = lambda: doctor
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            files = {"file": ("logo.png", _make_dummy_image("PNG"), "image/png")}
            res = await ac.post("/api/v1/super-admin/hospitals/101/logo", files=files, headers=AUTH_HEADERS)

        assert res.status_code == 403, res.text
        assert "Requires Super Admin or Hospital Admin role" in res.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_staff_upload_rejected():
    """Scenario 7: Receptionist / Staff cannot upload logo -> 403 Forbidden."""
    staff = _make_user(25, "Receptionist", hospital_id=101)
    mock_db = AsyncMock()

    app.dependency_overrides[bearer_scheme] = lambda: MagicMock(credentials="fake-token")
    app.dependency_overrides[get_current_active_user] = lambda: staff
    app.dependency_overrides[get_current_user] = lambda: staff
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            files = {"file": ("logo.png", _make_dummy_image("PNG"), "image/png")}
            res = await ac.post("/api/v1/super-admin/hospitals/101/logo", files=files, headers=AUTH_HEADERS)

        assert res.status_code == 403, res.text
        assert "Requires Super Admin or Hospital Admin role" in res.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_invalid_hospital_id_returns_404():
    """Scenario 8: Non-existent hospital ID returns 404 Not Found."""
    super_admin = _make_user(1, "Super Admin", hospital_id=None)
    mock_db = AsyncMock()

    app.dependency_overrides[bearer_scheme] = lambda: MagicMock(credentials="fake-token")
    app.dependency_overrides[get_current_active_user] = lambda: super_admin
    app.dependency_overrides[get_current_user] = lambda: super_admin
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with patch("app.services.hospital_service.HospitalService.upload_logo", new_callable=AsyncMock) as mock_upload:
            mock_upload.side_effect = NotFoundException("Hospital not found")

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                files = {"file": ("logo.png", _make_dummy_image("PNG"), "image/png")}
                res = await ac.post("/api/v1/super-admin/hospitals/99999/logo", files=files, headers=AUTH_HEADERS)

            assert res.status_code == 404, res.text
            assert "Hospital not found" in res.text
    finally:
        app.dependency_overrides.clear()


# ==============================================================================
# 3. Rollback & Replacement Preservation (Tempfile Isolated Tests)
# ==============================================================================

@pytest.mark.asyncio
async def test_upload_failure_preserves_rollback_behavior():
    """Scenario 9: If upload/DB update fails, newly created file is unlinked and old logo is preserved."""
    import tempfile
    import os
    from datetime import datetime
    from app.core.config import settings
    from app.models.hospital_model import Hospital
    from app.services.hospital_service import HospitalService

    with tempfile.TemporaryDirectory() as tmp_root:
        with patch.object(settings, "UPLOAD_DIR", tmp_root):
            hosp_dir = os.path.join(tmp_root, "hospitals")
            os.makedirs(hosp_dir, exist_ok=True)
            old_logo = os.path.join(hosp_dir, "initial_logo.png")
            with open(old_logo, "wb") as f:
                f.write(b"existing_bytes")

            hosp = Hospital(
                id=303,
                name="Rollback Hosp",
                email="rollback@test.com",
                logo_path=old_logo,
                is_active=True,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )

            mock_db = AsyncMock()
            service = HospitalService(mock_db)
            service.repo.get_by_id = AsyncMock(return_value=hosp)
            service.audit_repo.create = AsyncMock()
            service.repo.update = AsyncMock(side_effect=RuntimeError("Database failure during flush"))

            upload_file = MagicMock()
            upload_file.filename = "new_logo.png"
            upload_file.read = AsyncMock(return_value=_make_dummy_image("PNG"))

            with pytest.raises(RuntimeError):
                await service.upload_logo(id=303, file=upload_file, user_id=1)

            # 1. Old logo survives
            assert os.path.exists(old_logo)
            # 2. hospital.logo_path is restored
            assert hosp.logo_path == old_logo
            # 3. Newly created file was removed from disk
            assert os.listdir(hosp_dir) == ["initial_logo.png"]


@pytest.mark.asyncio
async def test_existing_logo_replacement_preserves_cleanup_behavior():
    """Scenario 10: Successful replacement unlinks the old logo and saves the new one."""
    import tempfile
    import os
    from datetime import datetime
    from app.core.config import settings
    from app.models.hospital_model import Hospital
    from app.services.hospital_service import HospitalService

    with tempfile.TemporaryDirectory() as tmp_root:
        with patch.object(settings, "UPLOAD_DIR", tmp_root):
            hosp_dir = os.path.join(tmp_root, "hospitals")
            os.makedirs(hosp_dir, exist_ok=True)
            old_logo = os.path.join(hosp_dir, "old_logo.png")
            with open(old_logo, "wb") as f:
                f.write(b"old_bytes")

            hosp = Hospital(
                id=404,
                name="Replacement Hosp",
                email="replace@test.com",
                logo_path=old_logo,
                is_active=True,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )

            mock_db = AsyncMock()
            service = HospitalService(mock_db)
            service.repo.get_by_id = AsyncMock(return_value=hosp)
            service.audit_repo.create = AsyncMock()
            service.repo.update = AsyncMock(side_effect=lambda h: h)

            upload_file = MagicMock()
            upload_file.filename = "new_brand.png"
            upload_file.read = AsyncMock(return_value=_make_dummy_image("PNG"))

            res = await service.upload_logo(id=404, file=upload_file, user_id=1)

            # 1. Old logo removed from disk
            assert not os.path.exists(old_logo)
            # 2. New logo exists on disk
            assert os.path.exists(res.logo_path)
            assert hosp.logo_path == res.logo_path
            assert os.path.dirname(res.logo_path).replace("\\", "/").endswith("hospitals")
