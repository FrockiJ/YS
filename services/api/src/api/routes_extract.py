from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from ..core.auth import get_current_user_optional
from ..services import extract_jobs

router = APIRouter(tags=["Admin"])


@router.post("/extract")
async def extract_data(
    payload: extract_jobs.ExtractRequest,
    user: Optional[dict] = Depends(get_current_user_optional),
):
    request = extract_jobs.normalize_extract_request(payload, user=user)
    files = extract_jobs.collect_source_files(request)
    if not files and not extract_jobs.request_uses_virtual_sources(request):
        return {"ok": False, "msg": "no files found for extract request", "request": request.model_dump()}

    if request.execution_mode == "sync":
        return await extract_jobs.run_extract_request(request)

    result = await extract_jobs.enqueue_extract_job(request)
    if not result.get("ok"):
        return result
    return JSONResponse(status_code=202, content=result)


@router.get("/extract/jobs")
async def list_extract_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    user: Optional[dict] = Depends(get_current_user_optional),
):
    _ = user
    return {"ok": True, "rows": await extract_jobs.list_jobs(limit)}


@router.get("/extract/jobs/{job_id}")
async def get_extract_job(
    job_id: str,
    user: Optional[dict] = Depends(get_current_user_optional),
):
    _ = user
    job = await extract_jobs.get_job(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"ok": False, "error": "extract job not found"})
    return {"ok": True, "job": job}


@router.post("/extract/jobs/{job_id}/pause")
async def pause_extract_job(
    job_id: str,
    user: Optional[dict] = Depends(get_current_user_optional),
):
    _ = user
    result = await extract_jobs.pause_job(job_id)
    if not result.get("ok"):
        return JSONResponse(status_code=int(result.get("status_code", 400)), content=jsonable_encoder(result))
    return result


@router.post("/extract/jobs/{job_id}/resume")
async def resume_extract_job(
    job_id: str,
    user: Optional[dict] = Depends(get_current_user_optional),
):
    _ = user
    result = await extract_jobs.resume_job(job_id)
    if not result.get("ok"):
        return JSONResponse(status_code=int(result.get("status_code", 400)), content=jsonable_encoder(result))
    return result


@router.post("/extract/jobs/{job_id}/retry")
async def retry_extract_job(
    job_id: str,
    user: Optional[dict] = Depends(get_current_user_optional),
):
    _ = user
    result = await extract_jobs.retry_job(job_id)
    if not result.get("ok"):
        return JSONResponse(status_code=int(result.get("status_code", 400)), content=jsonable_encoder(result))
    return result
