"""
frame_embed.py
---------------
Embed key video frames as inline base64 images in the generated Markdown.

The LLM is instructed (see src/generate_docs.py) to reference relevant
frames inline using their exact filename, e.g. ![alt text](frame_000003.png).
This module turns those references into self-contained `data:` URIs so the
final document carries its own images — no extra files, blobs, or endpoints
needed for the CLI output or the web preview.

Mock mode:
  When MOCK_VISION=true no real frames exist on disk, so small generated
  placeholder images are returned for the filenames used by
  src.analyze_images.MOCK_IMAGE_RESULTS, keeping the feature demoable without
  Azure credentials or ffmpeg.
"""

import base64
import os
import pathlib
import re
import struct
import subprocess
import zlib

from src.analyze_images import MOCK_IMAGE_RESULTS

# Distinct colours so the mock frames are visually distinguishable.
_MOCK_COLORS: list[tuple[int, int, int]] = [
    (91, 155, 213),   # blue
    (237, 125, 49),   # orange
    (112, 173, 71),   # green
]

# Default max width (px) for frames embedded in the generated document.
# Frames are extracted at full video resolution for accurate Vision
# analysis; this only affects the copy embedded in the Markdown output.
_DEFAULT_EMBED_MAX_WIDTH = 640

_IMAGE_REF_RE = re.compile(r"!\[([^\]\n]*)\]\((frame_\d+\.\w+)\)")
_MIME_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def _solid_color_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """Generate a minimal solid-colour PNG with no external dependencies."""
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    row = b"\x00" + bytes(rgb) * width  # filter type 0 (None)
    raw = row * height
    idat = zlib.compress(raw, 9)
    return (
        signature
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )


def _resize_for_embed(path: str, max_width: int) -> bytes:
    """
    Return PNG bytes for *path* downscaled so its width is at most
    *max_width* (never upscaled, aspect ratio preserved). Falls back to the
    original file bytes if ffmpeg fails for any reason.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", path,
        "-vf", f"scale='min({max_width},iw)':-2",
        "-frames:v", "1",
        "-f", "image2pipe", "-vcodec", "png",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0 or not result.stdout:
        with open(path, "rb") as f:
            return f.read()
    return result.stdout


def load_frame_images(frame_paths: list[str]) -> dict[str, bytes]:
    """
    Return a mapping of frame filename -> raw image bytes, used to embed
    key frames inline in the generated documentation.

    Real frames are downscaled to FRAME_EMBED_MAX_WIDTH (default 640px) so
    the embedded copies stay compact and readable inline with the text —
    Vision analysis already ran on the full-resolution originals.

    In MOCK_VISION mode, returns small generated placeholder images keyed
    by the same filenames as analyze_images.MOCK_IMAGE_RESULTS.
    """
    if os.environ.get("MOCK_VISION", "false").lower() == "true":
        return {
            result["frame"]: _solid_color_png(480, 270, color)
            for result, color in zip(MOCK_IMAGE_RESULTS, _MOCK_COLORS)
        }

    max_width = int(os.environ.get("FRAME_EMBED_MAX_WIDTH", str(_DEFAULT_EMBED_MAX_WIDTH)))
    images: dict[str, bytes] = {}
    for path in frame_paths:
        images[pathlib.Path(path).name] = _resize_for_embed(path, max_width)
    return images


def embed_inline_images(markdown: str, frame_images: dict[str, bytes]) -> str:
    """
    Replace inline ![alt](frame_XXXXXX.png) references with base64 data URIs
    for frames present in *frame_images*.

    References to frames that are unavailable (or hallucinated by the LLM)
    are stripped so the document never shows a broken image icon.
    """
    embedded = 0
    dropped = 0

    def _replace(match: re.Match) -> str:
        nonlocal embedded, dropped
        alt_text, filename = match.group(1), match.group(2)
        image_bytes = frame_images.get(filename)
        if image_bytes is None:
            dropped += 1
            return ""
        embedded += 1
        mime = _MIME_TYPES.get(pathlib.Path(filename).suffix.lower(), "image/png")
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"![{alt_text}](data:{mime};base64,{encoded})"

    result = _IMAGE_REF_RE.sub(_replace, markdown)
    result = re.sub(r"\n{3,}", "\n\n", result)  # collapse gaps left by drops

    suffix = f", dropped {dropped} unresolved reference(s)" if dropped else ""
    print(f"[embed] Embedded {embedded} inline frame image(s){suffix}")

    return result
