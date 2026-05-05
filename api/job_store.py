"""
job_store.py
------------
Thin persistence layer for job state using Azure Blob Storage.

Layout inside the 'jobs' container:
  {job_id}/state.json   – JobState as JSON
  {job_id}/{filename}   – uploaded video file (temp during processing)
  {job_id}/result.md    – generated Markdown (written when status == done)
"""

import os
from datetime import datetime, timezone
from uuid import uuid4

from azure.storage.blob import BlobServiceClient

from api.models import JobState, JobStatus, JobStep

_CONTAINER = "jobs"

# In-memory job state store — used when MOCK_TRANSCRIPTION + MOCK_VISION are
# both true so the API runs without any Azure credentials.
_MEM_STORE: dict[str, JobState] = {}


def _blob_client() -> BlobServiceClient:
    return BlobServiceClient.from_connection_string(
        os.environ["AZURE_STORAGE_CONNECTION_STRING"]
    )


# ── Job lifecycle ─────────────────────────────────────────────────────────────

def create_job(video_filename: str, *, in_memory: bool = False) -> JobState:
    now = datetime.now(timezone.utc)
    state = JobState(
        job_id=str(uuid4()),
        status=JobStatus.PENDING,
        step=JobStep.UPLOADING,
        video_filename=video_filename,
        created_at=now,
        updated_at=now,
    )
    if in_memory:
        _MEM_STORE[state.job_id] = state
    else:
        _write_state(state)
    return state


def get_job(job_id: str) -> JobState:
    if job_id in _MEM_STORE:
        return _MEM_STORE[job_id]
    data = (
        _blob_client()
        .get_blob_client(_CONTAINER, f"{job_id}/state.json")
        .download_blob()
        .readall()
    )
    return JobState.model_validate_json(data)


def update_job(job_id: str, **kwargs) -> JobState:
    state = get_job(job_id)
    for key, value in kwargs.items():
        setattr(state, key, value)
    state.updated_at = datetime.now(timezone.utc)
    if job_id in _MEM_STORE:
        _MEM_STORE[job_id] = state
    else:
        _write_state(state)
    return state


def _write_state(state: JobState) -> None:
    (
        _blob_client()
        .get_blob_client(_CONTAINER, f"{state.job_id}/state.json")
        .upload_blob(state.model_dump_json(), overwrite=True)
    )


# ── Video / result blobs ──────────────────────────────────────────────────────

def upload_video(job_id: str, video_bytes: bytes, filename: str) -> None:
    (
        _blob_client()
        .get_blob_client(_CONTAINER, f"{job_id}/{filename}")
        .upload_blob(video_bytes, overwrite=True)
    )


def download_video(job_id: str, filename: str, local_path: str) -> None:
    data = (
        _blob_client()
        .get_blob_client(_CONTAINER, f"{job_id}/{filename}")
        .download_blob()
        .readall()
    )
    with open(local_path, "wb") as f:
        f.write(data)


def save_result(job_id: str, markdown: str) -> None:
    (
        _blob_client()
        .get_blob_client(_CONTAINER, f"{job_id}/result.md")
        .upload_blob(markdown.encode("utf-8"), overwrite=True)
    )


def get_result(job_id: str) -> str:
    return (
        _blob_client()
        .get_blob_client(_CONTAINER, f"{job_id}/result.md")
        .download_blob()
        .readall()
        .decode("utf-8")
    )
