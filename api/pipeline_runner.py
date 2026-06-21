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
from src.generate_docs import embed_frame_images, generate_documentation
from src.transcribe import format_transcript, transcribe_file


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
    print(f"[pipeline] Job {job_id}: thread started")
    tmp_dir = tempfile.mkdtemp(prefix=f"v2doc_{job_id[:8]}_")

    try:
        state = job_store.get_job(job_id)
        print(f"[pipeline] Job {job_id}: video={state.video_filename} mock={_full_mock()}")

        # ── Download video from Blob to temp dir ──────────────────────────────
        video_path = str(pathlib.Path(tmp_dir) / state.video_filename)
        if _full_mock():
            print(f"[pipeline] Job {job_id}: full mock mode – skipping blob download")
        else:
            print(f"[pipeline] Job {job_id}: downloading video from blob …")
            job_store.download_video(job_id, state.video_filename, video_path)
            print(f"[pipeline] Job {job_id}: download complete → {video_path}")

        # ── Transcribe ────────────────────────────────────────────────────────
        job_store.update_job(job_id, status=JobStatus.PROCESSING, step=JobStep.TRANSCRIBING)
        print(f"[pipeline] Job {job_id}: transcribing …")
        transcript_segments = transcribe_file(video_path)
        transcript = format_transcript(transcript_segments)
        print(f"[pipeline] Job {job_id}: transcript "
              f"{len(transcript_segments)} segment(s), {len(transcript)} chars")

        # ── Extract keyframes ─────────────────────────────────────────────────
        frames_dir = str(pathlib.Path(tmp_dir) / "frames")
        job_store.update_job(job_id, step=JobStep.EXTRACTING_FRAMES)
        print(f"[pipeline] Job {job_id}: extracting frames …")
        frames = extract_frames(video_path, output_dir=frames_dir)
        print(f"[pipeline] Job {job_id}: {len(frames)} frames extracted")

        # ── Analyse frames ────────────────────────────────────────────────────
        job_store.update_job(job_id, step=JobStep.ANALYZING_IMAGES)
        print(f"[pipeline] Job {job_id}: analysing frames …")
        vision_results = analyze_frames(frames)
        image_context = format_image_context(vision_results)

        # ── Generate documentation ────────────────────────────────────────────
        job_store.update_job(job_id, step=JobStep.GENERATING_DOCS)
        print(f"[pipeline] Job {job_id}: generating docs …")
        markdown = generate_documentation(transcript, image_context)
        markdown = embed_frame_images(markdown, frames_dir)

        # ── Persist result ────────────────────────────────────────────────────
        if _full_mock():
            _MOCK_RESULTS[job_id] = markdown
        else:
            job_store.save_result(job_id, markdown)
        job_store.update_job(job_id, status=JobStatus.DONE, step=JobStep.DONE)
        print(f"[pipeline] Job {job_id}: DONE")

    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        print(f"[pipeline] Job {job_id} FAILED: {error_detail}")
        try:
            job_store.update_job(
                job_id,
                status=JobStatus.FAILED,
                error=f"{type(exc).__name__}: {exc}",
            )
        except Exception as update_exc:
            print(f"[pipeline] Job {job_id}: could not write FAILED state: {update_exc}")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
