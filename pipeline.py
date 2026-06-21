#!/usr/bin/env python3
"""
pipeline.py
-----------
Main orchestration script for the video2doc-ai POC.

Flow:
  1. Load environment variables from .env
  2. (Optional) Upload video to Azure Blob Storage
  3. Transcribe audio using Azure AI Speech
  4. Extract keyframes from the video (OpenCV)
  5. Analyse frames with Azure AI Vision
  6. Generate Markdown documentation via Azure OpenAI
  7. Save output locally and (optional) upload to Blob Storage

Usage:
  python pipeline.py --video path/to/video.mp4 [--output output/doc.md] [--upload]

Flags:
  --video    Path to the local video file  (required)
  --output   Where to write the Markdown   (default: output/<video_stem>.md)
  --upload   Upload input video + output doc to Azure Blob Storage
  --frames   Directory to store extracted frames (default: frames/)
"""

import argparse
import os
import pathlib
import shutil
import sys

from dotenv import load_dotenv

# Load .env before importing modules that read env vars at import time
load_dotenv()

from src.transcribe import format_transcript, transcribe_file
from src.extract_frames import extract_frames
from src.analyze_images import analyze_frames, format_image_context
from src.generate_docs import embed_frame_images, generate_documentation, save_markdown


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate product documentation from a video using Azure AI."
    )
    parser.add_argument("--video", required=True, help="Path to the input video file")
    parser.add_argument("--output", default=None, help="Output Markdown file path")
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload video and result to Azure Blob Storage",
    )
    parser.add_argument(
        "--frames",
        default="frames",
        help="Directory to store extracted frames (default: frames/)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    video_path = pathlib.Path(args.video).resolve()
    full_mock = (
        os.environ.get("MOCK_TRANSCRIPTION", "false").lower() == "true"
        and os.environ.get("MOCK_VISION", "false").lower() == "true"
    )
    if not video_path.exists():
        if full_mock:
            print(f"[mock] Video file not found but running in full mock mode – continuing.")
        else:
            print(f"ERROR: Video file not found: {video_path}", file=sys.stderr)
            sys.exit(1)

    output_path = pathlib.Path(
        args.output or f"output/{video_path.stem}.md"
    ).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  video2doc-ai  –  POC Pipeline")
    print("=" * 60)
    print(f"  Input  : {video_path}")
    print(f"  Output : {output_path}")
    print("=" * 60)

    # ── Step 1: Upload video to Blob (optional) ───────────────────────────────
    if args.upload:
        from src.blob_storage import upload_video
        upload_video(str(video_path))

    # ── Step 2: Transcribe ────────────────────────────────────────────────────
    print("\n[1/4] Transcribing video …")
    transcript_segments = transcribe_file(str(video_path))
    transcript = format_transcript(transcript_segments)

    # ── Step 3: Extract frames ────────────────────────────────────────────────
    print("\n[2/4] Extracting frames …")
    frames = extract_frames(str(video_path), output_dir=args.frames)

    # ── Step 4: Analyse frames with Vision ───────────────────────────────────
    print("\n[3/4] Analysing frames with Azure AI Vision …")
    vision_results = analyze_frames(frames)
    image_context = format_image_context(vision_results)

    # ── Step 5: Generate documentation ───────────────────────────────────────
    print("\n[4/4] Generating documentation with Azure OpenAI …")
    markdown = generate_documentation(transcript, image_context)
    markdown = embed_frame_images(markdown, args.frames)

    # ── Step 6: Save output ───────────────────────────────────────────────────
    save_markdown(markdown, str(output_path))

    # ── Step 7: Upload result (optional) ─────────────────────────────────────
    if args.upload:
        from src.blob_storage import upload_markdown
        upload_markdown(str(output_path), output_path.name)

    # ── Cleanup frames directory ──────────────────────────────────────────────
    if pathlib.Path(args.frames).exists():
        shutil.rmtree(args.frames)
        print(f"[cleanup] Removed '{args.frames}/' directory")

    print("\n" + "=" * 60)
    print(f"  Done!  Documentation saved to: {output_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
