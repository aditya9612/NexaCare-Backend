import os
import uuid
from pathlib import Path

import aiofiles
from fastapi import HTTPException, UploadFile, status

from app.core.config import settings

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".doc", ".docx"}


async def save_upload(file: UploadFile, subfolder: str) -> str:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File type not allowed")

    upload_dir = Path(settings.UPLOAD_DIR) / subfolder
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = upload_dir / filename

    content = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File size exceeds maximum allowed limit of {settings.MAX_UPLOAD_SIZE_MB}MB"
        )

    async with aiofiles.open(filepath, "wb") as f:
        await f.write(content)

    return str(filepath).replace(os.sep, "/")


async def save_upload_file(file: UploadFile, upload_dir: str | Path | None = None, subfolder: str = "patients") -> str:
    norm_root = Path(settings.UPLOAD_DIR).resolve()
    if upload_dir is not None:
        target_path = Path(upload_dir).resolve()
        try:
            rel = target_path.relative_to(norm_root)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid upload destination",
            )

        if target_path == norm_root:
            target_subfolder = subfolder
        else:
            target_subfolder = str(rel).replace("\\", "/")
    else:
        target_subfolder = subfolder

    return await save_upload(file, target_subfolder)
