"""
analyze_images.py
-----------------
Analyse extracted video frames with Azure AI Vision (Image Analysis 4.0).

For each image the service returns:
  • A natural-language caption
  • Dense captions (regions)
  • OCR text (read feature)

Each result keeps the frame's timestamp (seconds from the start of the
video) so the LLM prompt can present a single, time-ordered narrative of
what was said and what was on screen at the same moment.

Mock mode returns pre-canned data so the pipeline runs without credentials.

Production upgrade path:
  • Use Azure AI Document Intelligence (Form Recognizer) when frames
    contain structured documents, tables, or forms – it returns richer
    layout information.
  • Use Azure AI Video Indexer's built-in OCR / visual content moderation
    for full-video analysis in a single API call.
"""

import os
import pathlib
from typing import Any

from azure.ai.vision.imageanalysis import ImageAnalysisClient
from azure.ai.vision.imageanalysis.models import VisualFeatures
from azure.core.credentials import AzureKeyCredential

from src.timestamps import format_timestamp


# ── Mock ──────────────────────────────────────────────────────────────────────

MOCK_IMAGE_RESULTS: list[dict[str, Any]] = [
    {
        "frame": "frame_000000.png",
        "timestamp": 5.0,
        "caption": "A product dashboard showing KPI cards for leads, deals, and revenue.",
        "ocr_text": "Total Leads: 1,240  Active Deals: 87  Revenue MTD: $142,500  Tasks Due: 12",
    },
    {
        "frame": "frame_000001.png",
        "timestamp": 42.0,
        "caption": "A filter configuration panel with dropdown menus and a search bar.",
        "ocr_text": "Smart Filters  Status: Active  Owner: Any  Date Range: Last 30 days  Apply",
    },
    {
        "frame": "frame_000002.png",
        "timestamp": 75.0,
        "caption": "An export wizard dialog with format options CSV, Excel, and PDF.",
        "ocr_text": "Export Wizard  Format: CSV  Columns: All  Date Range: Q1 2024  Export",
    },
]


# ── Real analysis ─────────────────────────────────────────────────────────────

def analyze_frames(frames: list[dict]) -> list[dict[str, Any]]:
    """
    Analyse each frame and return a list of result dicts.

    *frames* is the list produced by extract_frames(): dicts with
    "path", "filename", and "timestamp".

    Each returned dict contains:
      - frame:     filename
      - timestamp: seconds from the start of the video
      - caption:   top-level image caption
      - ocr_text:  all text detected in the image
    """
    if os.environ.get("MOCK_VISION", "false").lower() == "true":
        print("[vision] MOCK mode – returning sample image analysis")
        return MOCK_IMAGE_RESULTS

    endpoint = os.environ["AZURE_VISION_ENDPOINT"]
    key = os.environ["AZURE_VISION_KEY"]

    vision_client = ImageAnalysisClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(key),
    )

    results: list[dict[str, Any]] = []

    for frame in frames:
        print(f"[vision] Analysing '{frame['filename']}' "
              f"[{format_timestamp(frame['timestamp'])}] …")
        with open(frame["path"], "rb") as f:
            image_data = f.read()

        response = vision_client.analyze(
            image_data=image_data,
            visual_features=[VisualFeatures.CAPTION, VisualFeatures.READ],
            language="en",
        )

        caption = (
            response.caption.text
            if response.caption
            else "No caption available"
        )

        ocr_lines: list[str] = []
        if response.read and response.read.blocks:
            for block in response.read.blocks:
                for line in block.lines:
                    ocr_lines.append(line.text)
        ocr_text = " | ".join(ocr_lines) if ocr_lines else ""

        results.append(
            {
                "frame": frame["filename"],
                "timestamp": frame["timestamp"],
                "caption": caption,
                "ocr_text": ocr_text,
            }
        )

    print(f"[vision] Analysed {len(results)} frame(s)")
    return results


def format_image_context(results: list[dict[str, Any]]) -> str:
    """Convert vision results to a time-ordered text block for the LLM prompt."""
    lines: list[str] = []
    for r in results:
        lines.append(f"[{format_timestamp(r['timestamp'])}] {r['frame']}")
        lines.append(f"  Visual: {r['caption']}")
        if r.get("ocr_text"):
            lines.append(f"  Text on screen: {r['ocr_text']}")
    return "\n".join(lines)
