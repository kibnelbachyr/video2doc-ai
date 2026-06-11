"""
extract_frames.py
-----------------
Extract key frames from a local video file using ffmpeg.

Strategy: always keep the very first frame (the starting screen, used as an
establishing shot) plus every frame where ffmpeg's scene-change detection
(`select='gt(scene,SCENE_THRESHOLD)'`) fires — i.e. a new screen, dialog,
slide, or other significant visual transition. This targets actual visual
transitions instead of blindly sampling on a fixed time grid, so the
extracted frames are genuinely representative "key frames" of the video.

Including frame 0 unconditionally also means a single static slide with
voice-over naturally yields exactly one key frame (the slide itself) without
needing a separate fallback pass.

If, for some unexpected reason (e.g. an unreadable file) this still yields
nothing, falls back to uniform sampling at FRAMES_PER_MINUTE — clamped to the
video's duration so short videos still produce at least one frame — and as a
last resort extracts the first frame on its own. This guarantees visual
context is never empty.

The result is capped at MAX_FRAMES evenly-spread frames to bound Vision/LLM
cost and keep the generated document focused on the most representative
moments.

Returns a list of file paths to the saved PNG images.

Uses ffmpeg instead of OpenCV so all codecs (including AV1, HEVC, VP9) work
without additional platform dependencies.
"""

import os
import pathlib
import subprocess


def extract_frames(video_path: str, output_dir: str = "frames") -> list[str]:
    """
    Extract key frames from *video_path*.

    Returns a list of absolute paths to saved PNG files, sorted by time.
    Creates *output_dir* if it does not exist.

    When MOCK_VISION=true returns an empty list so the rest of the pipeline
    can run without a real video file.
    """
    if os.environ.get("MOCK_VISION", "false").lower() == "true":
        print("[frames] MOCK mode – skipping frame extraction")
        return []

    scene_threshold = float(os.environ.get("SCENE_THRESHOLD", "0.2"))
    max_frames = int(os.environ.get("MAX_FRAMES", "12"))

    out_dir = pathlib.Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "frame_%06d.png")

    # ── Primary: first frame + scene-change detection ─────────────────────────
    # Frame 0 establishes the starting screen; `gt(scene,X)` then picks up
    # every subsequent frame where the visual content changes significantly.
    # Together these are what "key frames" should mean.
    _run_ffmpeg(video_path, pattern, f"select='eq(n,0)+gt(scene,{scene_threshold})'")
    saved = sorted(out_dir.glob("frame_*.png"))

    # ── Fallback: uniform sampling ────────────────────────────────────────────
    # In the unlikely case the above produced nothing, sample on a fixed time
    # grid so we still have visual context for the LLM. The interval is
    # clamped to the video duration so short videos still yield a frame.
    if not saved:
        print("[frames] No frames from scene detection – falling back to uniform sampling")
        frames_per_minute = int(os.environ.get("FRAMES_PER_MINUTE", "1"))
        interval_sec = 60.0 / frames_per_minute
        duration = _get_duration(video_path)
        if duration > 0:
            interval_sec = min(interval_sec, duration)
        _run_ffmpeg(video_path, pattern, f"fps=1/{interval_sec:.6f}")
        saved = sorted(out_dir.glob("frame_*.png"))

    # ── Last resort: single first frame ───────────────────────────────────────
    if not saved:
        print("[frames] Uniform sampling yielded nothing – extracting first frame only")
        _run_ffmpeg(video_path, pattern, "select='eq(n,0)'")
        saved = sorted(out_dir.glob("frame_*.png"))

    # ── Cap ────────────────────────────────────────────────────────────────────
    # Keep at most MAX_FRAMES, evenly spread across the detected set, to bound
    # Vision/LLM cost and avoid an overly long document.
    if len(saved) > max_frames:
        step = len(saved) / max_frames
        keep = {int(i * step) for i in range(max_frames)}
        for i, path in enumerate(saved):
            if i not in keep:
                path.unlink()
        saved = sorted(out_dir.glob("frame_*.png"))

    result = [str(p) for p in saved]
    print(f"[frames] Extracted {len(result)} key frame(s) → '{output_dir}/'")
    return result


def _get_duration(video_path: str) -> float:
    """Return the duration of *video_path* in seconds, or 0.0 if unknown."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def _run_ffmpeg(video_path: str, pattern: str, video_filter: str) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", video_filter,
        "-vsync", "vfr",
        pattern,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg frame extraction failed:\n{result.stderr}")
