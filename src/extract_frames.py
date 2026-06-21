"""
extract_frames.py
-----------------
Extract keyframes from a local video file using ffmpeg.

Strategy: sample one frame every N seconds (configurable via FRAMES_PER_MINUTE).
Returns a list of dicts with the frame's file path, filename, and its
timestamp (seconds from the start of the video) — the timestamp lets the
documentation generator place each frame next to the narration it
illustrates instead of just appending images at random.

Uses ffmpeg instead of OpenCV so all codecs (including AV1, HEVC, VP9) work
without additional platform dependencies.
"""

import os
import pathlib
import subprocess


def extract_frames(video_path: str, output_dir: str = "frames") -> list[dict]:
    """
    Extract frames from *video_path* at a rate of FRAMES_PER_MINUTE.

    Returns a list of {"path": str, "filename": str, "timestamp": float}
    dicts, ordered by time. Creates *output_dir* if it does not exist.

    When MOCK_VISION=true returns an empty list so the rest of the pipeline
    can run without a real video file.
    """
    if os.environ.get("MOCK_VISION", "false").lower() == "true":
        print("[frames] MOCK mode – skipping frame extraction")
        return []

    frames_per_minute = int(os.environ.get("FRAMES_PER_MINUTE", "12"))
    interval_sec = 60.0 / frames_per_minute

    out_dir = pathlib.Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pattern = str(out_dir / "frame_%06d.png")

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", f"fps=1/{interval_sec:.6f}",
        "-vsync", "vfr",
        pattern,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg frame extraction failed:\n{result.stderr}")

    saved = sorted(out_dir.glob("frame_*.png"))
    frames = [
        {
            "path": str(p),
            "filename": p.name,
            "timestamp": i * interval_sec,
        }
        for i, p in enumerate(saved)
    ]
    print(f"[frames] Extracted {len(frames)} frame(s) → '{output_dir}/' "
          f"(1 every {interval_sec:.1f}s)")
    return frames
