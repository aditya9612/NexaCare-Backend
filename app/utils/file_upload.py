import os
import uuid
from pathlib import Path

import aiofiles
from fastapi import HTTPException, UploadFile, status

from app.core.config import settings

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx"}


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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File too large")

    async with aiofiles.open(filepath, "wb") as f:
        await f.write(content)

    return str(filepath).replace(os.sep, "/")


async def save_upload_file(file: UploadFile, upload_dir: str | None = None, subfolder: str = "patients") -> str:
    return await save_upload(file, subfolder)
