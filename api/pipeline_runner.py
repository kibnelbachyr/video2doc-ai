"""
pipeline_runner.py
------------------
Runs the video-to-documentation pipeline inside a background thread.

Called by the jobs router after a video has been uploaded to Blob Storage.
Updates job state at each step so the UI can show live progress.

Error handling: any exception is caught, logged, and stored in the job state.
The temp directory is always cleaned up in the finally block.
"""

import os
import pathlib
import shutil
import tempfile
import traceback

from api import job_store
from api.models import JobStatus, JobStep
from src.analyze_images import analyze_frames, format_image_context
from src.extract_frames import extract_frames
from src.generate_docs import generate_documentation
from src.transcribe import transcribe_file


# In-memory result cache used when MOCK_TRANSCRIPTION=true AND MOCK_VISION=true.
# Avoids the need for Azure Storage during local development.
_MOCK_RESULTS: dict[str, str] = {}


def get_mock_result(job_id: str) -> str | None:
    return _MOCK_RESULTS.get(job_id)


def _full_mock() -> bool:
    return (
        os.environ.get("MOCK_TRANSCRIPTION", "false").lower() == "true"
        and os.environ.get("MOCK_VISION", "false").lower() == "true"
    )


def run_pipeline(job_id: str) -> None:
    """Execute the full pipeline for *job_id*. Designed to run in a thread."""
    tmp_dir = tempfile.mkdtemp(prefix=f"v2doc_{job_id[:8]}_")

    try:
        state = job_store.get_job(job_id)

        # ── Download video from Blob to temp dir ──────────────────────────────
        # Skipped in full mock mode so the API works without Azure Storage.
        video_path = str(pathlib.Path(tmp_dir) / state.video_filename)
        if _full_mock():
            print(f"[pipeline] Full mock mode – skipping blob download for job {job_id}")
        else:
            job_store.download_video(job_id, state.video_filename, video_path)

        # ── Transcribe ────────────────────────────────────────────────────────
        job_store.update_job(
            job_id, status=JobStatus.PROCESSING, step=JobStep.TRANSCRIBING
        )
        transcript = transcribe_file(video_path)

        # ── Extract keyframes ─────────────────────────────────────────────────
        frames_dir = str(pathlib.Path(tmp_dir) / "frames")
        job_store.update_job(job_id, step=JobStep.EXTRACTING_FRAMES)
        frame_paths = extract_frames(video_path, output_dir=frames_dir)

        # ── Analyse frames ────────────────────────────────────────────────────
        job_store.update_job(job_id, step=JobStep.ANALYZING_IMAGES)
        vision_results = analyze_frames(frame_paths)
        image_context = format_image_context(vision_results)

        # ── Generate documentation ────────────────────────────────────────────
        job_store.update_job(job_id, step=JobStep.GENERATING_DOCS)
        markdown = generate_documentation(transcript, image_context)

        # ── Persist result ────────────────────────────────────────────────────
        if _full_mock():
            # In mock mode store the result in memory so get_result() can serve it
            # without needing Azure Storage.
            _MOCK_RESULTS[job_id] = markdown
        else:
            job_store.save_result(job_id, markdown)
        job_store.update_job(job_id, status=JobStatus.DONE, step=JobStep.DONE)

    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        print(f"[pipeline] Job {job_id} failed: {error_detail}")
        job_store.update_job(
            job_id,
            status=JobStatus.FAILED,
            error=f"{type(exc).__name__}: {exc}",
        )

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
