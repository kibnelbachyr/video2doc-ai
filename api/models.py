"""
models.py
---------
Pydantic models for job state tracking.

A Job represents one video-to-documentation pipeline run.
State is persisted as JSON in Azure Blob Storage (jobs/{job_id}/state.json).
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class JobStatus(str, Enum):
    PENDING    = "pending"
    PROCESSING = "processing"
    DONE       = "done"
    FAILED     = "failed"


class JobStep(str, Enum):
    UPLOADING          = "uploading"
    TRANSCRIBING       = "transcribing"
    EXTRACTING_FRAMES  = "extracting_frames"
    ANALYZING_IMAGES   = "analyzing_images"
    GENERATING_DOCS    = "generating_docs"
    DONE               = "done"


# Labels shown in the UI for each step
STEP_LABELS: dict[JobStep, str] = {
    JobStep.UPLOADING:         "Uploading video",
    JobStep.TRANSCRIBING:      "Transcribing audio",
    JobStep.EXTRACTING_FRAMES: "Extracting keyframes",
    JobStep.ANALYZING_IMAGES:  "Analysing images",
    JobStep.GENERATING_DOCS:   "Generating documentation",
    JobStep.DONE:              "Done",
}


class JobState(BaseModel):
    """Full job state stored in Blob Storage."""
    job_id:         str
    status:         JobStatus
    step:           Optional[JobStep]  = None
    error:          Optional[str]      = None
    video_filename: str
    created_at:     datetime
    updated_at:     datetime


class JobResponse(BaseModel):
    """API response payload for job status queries."""
    job_id:     str
    status:     JobStatus
    step:       Optional[str]      = None
    step_label: Optional[str]      = None
    error:      Optional[str]      = None
    created_at: str
    updated_at: str
    result_url: Optional[str]      = None
