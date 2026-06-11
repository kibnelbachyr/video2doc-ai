"""
extract_frames.py
-----------------
Extract key frames from a local video file using ffmpeg.

Strategy: sample a dense pool of candidate frames at a uniform interval
(scaled to the video's duration so longer videos yield proportionally more
candidates), then greedily keep the MAX_FRAMES candidates that are most
visually different from one another — a "farthest-point" diversity search
over tiny grayscale thumbnails.

This picks frames that actually look different from each other, instead of
blindly sampling on a fixed time grid (which can land repeatedly on the same
static screen) or relying on ffmpeg's `scene` change metric (which fires
constantly on animated/cartoon content regardless of threshold).

Both the full-resolution candidates and their thumbnails are produced by a
single ffmpeg invocation (`filter_complex` + `split`), so the video is
decoded only once.

Returns a list of file paths to the saved PNG images.

Uses ffmpeg instead of OpenCV so all codecs (including AV1, HEVC, VP9) work
without additional platform dependencies.
"""

import os
import pathlib
import subprocess

THUMB_SIZE = 8  # NxN grayscale thumbnail used to compare candidate frames


def extract_frames(video_path: str, output_dir: str = "frames") -> list[str]:
    """
    Extract key frames from *video_path*.

    A dense pool of candidate frames is sampled uniformly across the video,
    then up to MAX_FRAMES of the most visually-distinct candidates are kept.

    Returns a list of absolute paths to saved PNG files, sorted by time.
    Creates *output_dir* if it does not exist.

    When MOCK_VISION=true returns an empty list so the rest of the pipeline
    can run without a real video file.
    """
    if os.environ.get("MOCK_VISION", "false").lower() == "true":
        print("[frames] MOCK mode – skipping frame extraction")
        return []

    max_frames = int(os.environ.get("MAX_FRAMES", "12"))

    out_dir = pathlib.Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "frame_%06d.png")
    thumbs_path = out_dir / "thumbs.raw"

    # Spread roughly MAX_FRAMES * 10 candidates across the video, with a
    # 1-second floor so very short videos still produce a few candidates
    # (and never zero, regardless of duration).
    duration = _get_duration(video_path)
    candidate_interval = max(1.0, duration / (max_frames * 10))

    _run_ffmpeg([
        "ffmpeg", "-y",
        "-i", video_path,
        "-filter_complex",
        f"[0:v]fps=1/{candidate_interval:.6f},split=2[full][thumbsrc];"
        f"[thumbsrc]scale={THUMB_SIZE}:{THUMB_SIZE}:flags=area,format=gray[thumb]",
        "-map", "[full]", "-vsync", "vfr", pattern,
        "-map", "[thumb]", "-vsync", "vfr", "-f", "rawvideo", "-pix_fmt", "gray", str(thumbs_path),
    ])

    candidates = sorted(out_dir.glob("frame_*.png"))

    if not candidates:
        # Unreadable/zero-frame video: fall back to the first frame only.
        print("[frames] No candidates extracted – falling back to first frame")
        _run_ffmpeg(["ffmpeg", "-y", "-i", video_path, "-frames:v", "1", pattern])
        candidates = sorted(out_dir.glob("frame_*.png"))
        thumbs_path.unlink(missing_ok=True)
        saved = [str(p) for p in candidates]
        print(f"[frames] Extracted {len(saved)} key frame(s) → '{output_dir}/'")
        return saved

    thumb_bytes = THUMB_SIZE * THUMB_SIZE
    raw = thumbs_path.read_bytes()
    thumbs_path.unlink()
    thumbnails = [raw[i * thumb_bytes:(i + 1) * thumb_bytes] for i in range(len(candidates))]

    if len(candidates) <= max_frames:
        keep = set(range(len(candidates)))
    else:
        keep = set(_select_diverse(thumbnails, max_frames))

    for i, path in enumerate(candidates):
        if i not in keep:
            path.unlink()

    saved = sorted(str(p) for i, p in enumerate(candidates) if i in keep)
    print(f"[frames] Extracted {len(saved)} key frame(s) from {len(candidates)} candidate(s) → '{output_dir}/'")
    return saved


def _select_diverse(thumbnails: list[bytes], max_frames: int) -> list[int]:
    """
    Greedily pick *max_frames* indices whose thumbnails are maximally
    different from one another (farthest-point / k-center search).

    Index 0 (the first candidate) is always kept as an establishing frame.
    Each subsequent pick is the candidate whose nearest already-selected
    neighbour is the most different, so near-duplicate frames are skipped
    in favour of genuinely new visual content.
    """
    selected = [0]
    min_dist = [_distance(thumbnails[0], t) for t in thumbnails]

    while len(selected) < max_frames:
        next_idx = max(range(len(thumbnails)), key=lambda i: min_dist[i])
        selected.append(next_idx)
        for i, t in enumerate(thumbnails):
            min_dist[i] = min(min_dist[i], _distance(thumbnails[next_idx], t))

    return selected


def _distance(a: bytes, b: bytes) -> int:
    """Sum of absolute pixel-value differences between two thumbnails."""
    return sum(abs(x - y) for x, y in zip(a, b))


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


def _run_ffmpeg(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg frame extraction failed:\n{result.stderr}")
