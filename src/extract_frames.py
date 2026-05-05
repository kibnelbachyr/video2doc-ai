"""
extract_frames.py
-----------------
Extract keyframes from a local video file using OpenCV.

Strategy: sample one frame every N seconds (configurable via FRAMES_PER_MINUTE).
Returns a list of file paths to the saved PNG images.

Production upgrade path:
  • Replace OpenCV sampling with Azure AI Video Indexer's shot/scene detection.
  • Video Indexer automatically detects scene boundaries, OCR on screen content,
    detected objects, and can export thumbnails via its REST API.
  • See: https://learn.microsoft.com/azure/azure-video-indexer/
"""

import os
import pathlib
import cv2


def extract_frames(video_path: str, output_dir: str = "frames") -> list[str]:
    """
    Extract frames from *video_path* at a rate of FRAMES_PER_MINUTE.

    Returns a list of absolute paths to saved PNG files.
    Creates *output_dir* if it does not exist.
    """
    frames_per_minute = int(os.environ.get("FRAMES_PER_MINUTE", "1"))
    pathlib.Path(output_dir).mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video file: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = total_frames / fps
    interval_sec = 60.0 / frames_per_minute  # seconds between captures

    saved: list[str] = []
    next_capture_sec = 0.0
    frame_idx = 0

    print(f"[frames] Video: {duration_sec:.1f}s @ {fps:.1f} fps – "
          f"extracting every {interval_sec:.0f}s")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        current_sec = frame_idx / fps
        if current_sec >= next_capture_sec:
            out_path = str(pathlib.Path(output_dir) / f"frame_{frame_idx:06d}.png")
            cv2.imwrite(out_path, frame)
            saved.append(out_path)
            next_capture_sec += interval_sec

        frame_idx += 1

    cap.release()
    print(f"[frames] Extracted {len(saved)} frame(s) → '{output_dir}/'")
    return saved
