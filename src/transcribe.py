"""
transcribe.py
-------------
Transcribe a local video file using the Azure AI Speech REST API.

Two modes:
  • Real  – ffmpeg extracts a 16 kHz mono WAV. The audio is split into
            chunks at natural silences (so words/sentences are never cut
            mid-way) of at most ~55 s each, then each chunk is sent to the
            Azure Speech REST API. No Speech SDK required — pure HTTP calls
            via requests.
  • Mock  – returns a hard-coded, timestamped transcript so the rest of
            the pipeline can run without Azure credentials during local dev.

Using the REST API instead of the SDK avoids ALSA / audio platform
initialisation failures that occur in headless containers.

Each returned segment carries the absolute timestamp (seconds from the
start of the video) at which that speech was recognised, so the LLM can
later correlate narration with the video frame showing on screen at the
same moment.

NOTE: For files longer than ~10 minutes the recommended production approach
is the Azure Batch Transcription REST API, which is asynchronous and handles
large files natively without chunking.
"""

import io
import os
import subprocess
import tempfile
import wave

import requests

from src.timestamps import format_timestamp

MAX_CHUNK_SECONDS = 55       # stays under the Speech REST API's ~60 s limit
MIN_CHUNK_SECONDS = 5        # never cut a chunk shorter than this
SILENCE_NOISE_DB = "-30dB"   # ffmpeg silencedetect threshold
SILENCE_MIN_DURATION = 0.4   # seconds of quiet required to count as a pause


# ── Mock ──────────────────────────────────────────────────────────────────────

MOCK_TRANSCRIPT_SEGMENTS = [
    {"start": 0.0, "text": (
        "Welcome to the product onboarding video for ContosoCRM version 3.2. "
        "In this video we will walk you through the three main features "
        "introduced in this release: the new Dashboard, Smart Filters, and "
        "the Export Wizard."
    )},
    {"start": 18.0, "text": (
        "Step one: open the Dashboard from the left navigation panel. "
        "You will see four KPI cards at the top showing total leads, active "
        "deals, revenue this month, and tasks due today."
    )},
    {"start": 40.0, "text": (
        "Step two: click on Smart Filters in the top-right corner. You can "
        "combine up to five filter criteria. Filters are saved per user and "
        "persist across sessions."
    )},
    {"start": 62.0, "text": (
        "Step three: to export data, click Export Wizard in the toolbar. "
        "Choose your date range, select the columns you need, and pick a "
        "format: CSV, Excel, or PDF. The export runs in the background and "
        "you will receive an email when it is ready."
    )},
    {"start": 90.0, "text": (
        "That concludes the overview. For detailed API documentation see "
        "the developer portal at docs.contoso.com."
    )},
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_wav(video_path: str, wav_path: str) -> None:
    """Extract mono 16 kHz PCM WAV from a video file using ffmpeg."""
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-ac", "1",      # mono
        "-ar", "16000",  # 16 kHz — optimal for Speech API
        "-vn",           # drop video stream
        wav_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extraction failed:\n{result.stderr}")


def _detect_silence_points(wav_path: str) -> list[float]:
    """Return timestamps (seconds) where a silence ends, via ffmpeg silencedetect.

    These are used as natural cut points so chunk boundaries fall between
    sentences/words instead of slicing audio at a blind fixed interval.
    """
    cmd = [
        "ffmpeg", "-i", wav_path,
        "-af", f"silencedetect=noise={SILENCE_NOISE_DB}:d={SILENCE_MIN_DURATION}",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    points: list[float] = []
    for line in result.stderr.splitlines():
        if "silence_end:" not in line:
            continue
        try:
            chunk = line.split("silence_end:")[1].strip()
            points.append(float(chunk.split("|")[0].strip()))
        except (IndexError, ValueError):
            continue
    return points


def _chunk_boundaries(total_seconds: float, silence_points: list[float]) -> list[float]:
    """Pick chunk cut points, preferring a nearby silence over a hard cut."""
    boundaries = [0.0]
    cursor = 0.0
    while cursor < total_seconds:
        target = cursor + MAX_CHUNK_SECONDS
        if target >= total_seconds:
            boundaries.append(total_seconds)
            break
        candidates = [
            p for p in silence_points
            if cursor + MIN_CHUNK_SECONDS <= p <= target
        ]
        cut = max(candidates) if candidates else target
        boundaries.append(cut)
        cursor = cut
    return boundaries


def _wav_chunks(wav_path: str) -> list[tuple[float, bytes]]:
    """Split a WAV file into (start_timestamp, wav_bytes) chunks.

    Chunks are cut at natural silences where possible (see
    _detect_silence_points), falling back to a hard cut at
    MAX_CHUNK_SECONDS when no pause is found in range.
    """
    silence_points = _detect_silence_points(wav_path)

    with wave.open(wav_path, "rb") as wf:
        rate = wf.getframerate()
        nchannels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        total_seconds = wf.getnframes() / float(rate)

        boundaries = _chunk_boundaries(total_seconds, silence_points)

        chunks: list[tuple[float, bytes]] = []
        for start, end in zip(boundaries[:-1], boundaries[1:]):
            wf.setpos(int(start * rate))
            frames = wf.readframes(int((end - start) * rate))
            if not frames:
                continue
            buf = io.BytesIO()
            with wave.open(buf, "wb") as out:
                out.setnchannels(nchannels)
                out.setsampwidth(sampwidth)
                out.setframerate(rate)
                out.writeframes(frames)
            chunks.append((start, buf.getvalue()))

    return chunks


def _transcribe_chunk(chunk_bytes: bytes, key: str, region: str, language: str) -> tuple[str, float]:
    """Send one WAV chunk to the Speech REST API.

    Returns (display_text, offset_seconds) where offset_seconds is how far
    into the chunk recognised speech actually started (skips leading
    silence), used to refine the absolute timestamp of the segment.
    """
    url = (
        f"https://{region}.stt.speech.microsoft.com"
        "/speech/recognition/conversation/cognitiveservices/v1"
    )
    headers = {
        "Ocp-Apim-Subscription-Key": key,
        "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
    }
    params = {"language": language, "format": "detailed"}

    response = requests.post(
        url, headers=headers, params=params, data=chunk_bytes, timeout=120
    )
    if response.status_code != 200:
        print(f"[speech] API error {response.status_code}: {response.text[:200]}")
        return "", 0.0

    result = response.json()
    if result.get("RecognitionStatus") != "Success":
        print(f"[speech] Chunk status: {result.get('RecognitionStatus')}")
        return "", 0.0

    nbest = result.get("NBest") or []
    text = nbest[0].get("Display", "") if nbest else result.get("DisplayText", "")
    offset_ticks = nbest[0].get("Offset", 0) if nbest else 0
    return text, offset_ticks / 1e7  # 100-ns ticks -> seconds


# ── Public API ────────────────────────────────────────────────────────────────

def transcribe_file(video_path: str) -> list[dict]:
    """
    Transcribe a local video file using the Azure AI Speech REST API.

    Extracts audio to a temporary WAV file via ffmpeg, splits it into
    silence-aware chunks (at most ~55 s, cut at pauses when possible), and
    transcribes each chunk via the REST API.

    Returns a list of {"start": float_seconds, "text": str} segments,
    ordered by time, so the LLM can later correlate narration with the
    matching video frame.
    """
    if os.environ.get("MOCK_TRANSCRIPTION", "false").lower() == "true":
        print("[speech] MOCK mode – returning sample transcript")
        return MOCK_TRANSCRIPT_SEGMENTS

    key = os.environ["AZURE_SPEECH_KEY"]
    region = os.environ["AZURE_SPEECH_REGION"]
    language = os.environ.get("SPEECH_LANGUAGE", "en-US")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name

    try:
        print(f"[speech] Extracting audio from '{video_path}' …")
        _extract_wav(video_path, wav_path)
        print("[speech] Audio extraction complete")

        chunks = _wav_chunks(wav_path)
        print(f"[speech] Transcribing {len(chunks)} chunk(s) via REST API "
              f"(language={language}) …")

        segments: list[dict] = []
        for i, (chunk_start, chunk_bytes) in enumerate(chunks, 1):
            text, offset_sec = _transcribe_chunk(chunk_bytes, key, region, language)
            if text:
                segments.append({"start": chunk_start + offset_sec, "text": text})
            print(f"[speech] Chunk {i}/{len(chunks)} "
                  f"[{format_timestamp(chunk_start)}] – {len(text)} chars")

    finally:
        try:
            os.unlink(wav_path)
        except OSError:
            pass

    total_chars = sum(len(s["text"]) for s in segments)
    print(f"[speech] Transcription complete – {len(segments)} segment(s), "
          f"{total_chars} characters")
    return segments


def format_transcript(segments: list[dict]) -> str:
    """Render timed transcript segments as a '[MM:SS] text' block for the LLM."""
    return "\n".join(
        f"[{format_timestamp(s['start'])}] {s['text']}" for s in segments
    )
