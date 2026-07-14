from pathlib import Path
import shutil
import uuid

from fastapi import APIRouter, UploadFile, File, HTTPException

from ..core.config import UPLOAD_STORAGE_PATH

router = APIRouter(tags=["Upload"])


def _resolve_upload_dir() -> Path:
    base = Path(UPLOAD_STORAGE_PATH or "py/S3")
    if not base.is_absolute():
        base = Path.cwd() / base
    base.mkdir(parents=True, exist_ok=True)
    return base


def _infer_attachment_type(filename: str, mime: str) -> str:
    lowered_name = (filename or "").lower()
    lowered_mime = (mime or "").lower()
    if lowered_mime.startswith("image/") or lowered_name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        return "image"
    if lowered_name.endswith(".pdf"):
        return "pdf"
    if lowered_name.endswith(".docx"):
        return "docx"
    if lowered_name.endswith((".xlsx", ".xls", ".csv")):
        return "spreadsheet"
    return "file"


@router.post("")
async def upload_file(file: UploadFile = File(...)):
    upload_dir = _resolve_upload_dir()
    safe_name = Path(file.filename).name or uuid.uuid4().hex
    target = upload_dir / f"{uuid.uuid4().hex}_{safe_name}"
    mime = file.content_type or "application/octet-stream"
    try:
        with target.open("wb") as out_file:
            shutil.copyfileobj(file.file, out_file)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Unable to save upload: {exc}")
    attachment = {
        "type": _infer_attachment_type(safe_name, mime),
        "filename": safe_name,
        "path": str(target.resolve()),
        "mime": mime,
        "url": None,
        "size": target.stat().st_size,
        "extracted_text": None,
        "ocr_status": "pending",
        "image_classification_status": "pending",
    }
    return {
        "ok": True,
        **attachment,
        "attachment": attachment,
    }
