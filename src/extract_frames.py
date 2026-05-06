"""
extract_frames.py
-----------------
Extract keyframes from a local video file using ffmpeg.

Strategy: sample one frame every N seconds (configurable via FRAMES_PER_MINUTE).
Returns a list of file paths to the saved PNG images.

Uses ffmpeg instead of OpenCV so all codecs (including AV1, HEVC, VP9) work
without additional platform dependencies.
"""

import os
import pathlib
import subprocess


def extract_frames(video_path: str, output_dir: str = "frames") -> list[str]:
    """
    Extract frames from *video_path* at a rate of FRAMES_PER_MINUTE.

    Returns a list of absolute paths to saved PNG files.
    Creates *output_dir* if it does not exist.

    When MOCK_VISION=true returns an empty list so the rest of the pipeline
    can run without a real video file.
    """
    if os.environ.get("MOCK_VISION", "false").lower() == "true":
        print("[frames] MOCK mode – skipping frame extraction")
        return []

    frames_per_minute = int(os.environ.get("FRAMES_PER_MINUTE", "1"))
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

    saved = sorted(str(p) for p in out_dir.glob("frame_*.png"))
    print(f"[frames] Extracted {len(saved)} frame(s) → '{output_dir}/'")
    return saved
