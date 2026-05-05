"""
routers/jobs.py
---------------
REST endpoints for the video-to-documentation pipeline.

  POST   /api/jobs                – upload a video, start the pipeline
  GET    /api/jobs/{job_id}       – poll job status
  GET    /api/jobs/{job_id}/result – fetch the generated Markdown
"""

import os
import threading

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import PlainTextResponse

from api import job_store
from api.models import JobStatus, STEP_LABELS
from api.pipeline_runner import run_pipeline, get_mock_result

router = APIRouter()

_MAX_UPLOAD_MB = 500
_ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv"}


@router.post("/jobs", status_code=202)
async def create_job(file: UploadFile = File(...)):
    """
    Upload a video file and immediately start the documentation pipeline.

    In full mock mode (MOCK_TRANSCRIPTION + MOCK_VISION both true) the file
    bytes are discarded immediately — only the filename is used — so this
    works with any tiny placeholder file and avoids proxy size limits.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(_ALLOWED_EXTENSIONS)}",
        )

    full_mock = (
        os.environ.get("MOCK_TRANSCRIPTION", "false").lower() == "true"
        and os.environ.get("MOCK_VISION", "false").lower() == "true"
    )

    if full_mock:
        # Discard the body immediately — nothing reads the video in mock mode.
        await file.close()
        state = job_store.create_job(file.filename, in_memory=True)
    else:
        video_bytes = await file.read()
        if len(video_bytes) > _MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds maximum size of {_MAX_UPLOAD_MB} MB.",
            )
        state = job_store.create_job(file.filename)
        job_store.upload_video(state.job_id, video_bytes, file.filename)

    threading.Thread(target=run_pipeline, args=(state.job_id,), daemon=True).start()

    return {
        "job_id": state.job_id,
        "status": state.status,
        "message": "Processing started. Poll /api/jobs/{job_id} for progress.",
    }


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    """Return the current status and step for a job."""
    try:
        state = job_store.get_job(job_id)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    return {
        "job_id":     state.job_id,
        "status":     state.status,
        "step":       state.step,
        "step_label": STEP_LABELS.get(state.step, "") if state.step else "",
        "error":      state.error,
        "created_at": state.created_at.isoformat(),
        "updated_at": state.updated_at.isoformat(),
        "result_url": f"/api/jobs/{job_id}/result" if state.status == JobStatus.DONE else None,
    }


@router.get("/jobs/{job_id}/result", response_class=PlainTextResponse)
async def get_job_result(job_id: str):
    """Return the generated Markdown document for a completed job."""
    try:
        state = job_store.get_job(job_id)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    if state.status == JobStatus.FAILED:
        raise HTTPException(status_code=422, detail=f"Job failed: {state.error}")

    if state.status != JobStatus.DONE:
        raise HTTPException(
            status_code=409,
            detail=f"Job is not finished yet. Current status: {state.status}",
        )

    # Try in-memory cache first (mock mode), then fall back to Blob Storage.
    mock_md = get_mock_result(job_id)
    if mock_md is not None:
        return mock_md
    try:
        return job_store.get_result(job_id)
    except Exception:
        raise HTTPException(status_code=500, detail="Result blob not found.")
