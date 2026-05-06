"""
transcribe.py
-------------
Transcribe a local video file using the Azure AI Speech REST API.

Two modes:
  • Real  – ffmpeg extracts a 16 kHz mono WAV, then the audio is sent to the
            Azure Speech REST API in 55-second chunks (avoids the ~60 s limit).
            No Speech SDK required — pure HTTP calls via requests.
  • Mock  – returns a hard-coded transcript so the rest of the pipeline
            can run without Azure credentials during local dev.

Using the REST API instead of the SDK avoids ALSA / audio platform
initialisation failures that occur in headless containers.

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


# ── Mock ──────────────────────────────────────────────────────────────────────

MOCK_TRANSCRIPT = """
Welcome to the product onboarding video for ContosoCRM version 3.2.

In this video we will walk you through the three main features introduced
in this release: the new Dashboard, Smart Filters, and the Export Wizard.

Step one: open the Dashboard from the left navigation panel.
You will see four KPI cards at the top showing total leads, active deals,
revenue this month, and tasks due today.

Step two: click on Smart Filters in the top-right corner.
You can combine up to five filter criteria. Filters are saved per user
and persist across sessions.

Step three: to export data, click Export Wizard in the toolbar.
Choose your date range, select the columns you need, and pick a format:
CSV, Excel, or PDF. The export runs in the background and you will receive
an email when it is ready.

That concludes the overview. For detailed API documentation see the
developer portal at docs.contoso.com.
"""


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


def _wav_chunks(wav_path: str, chunk_seconds: int = 55) -> list[bytes]:
    """Split a WAV file into chunks of at most chunk_seconds each.

    Each chunk is a self-contained WAV byte string so it can be sent
    directly to the Speech REST API.
    """
    chunks: list[bytes] = []
    with wave.open(wav_path, "rb") as wf:
        rate = wf.getframerate()
        nchannels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        frames_per_chunk = rate * chunk_seconds

        while True:
            frames = wf.readframes(frames_per_chunk)
            if not frames:
                break
            buf = io.BytesIO()
            with wave.open(buf, "wb") as out:
                out.setnchannels(nchannels)
                out.setsampwidth(sampwidth)
                out.setframerate(rate)
                out.writeframes(frames)
            chunks.append(buf.getvalue())

    return chunks


def _transcribe_chunk(chunk_bytes: bytes, key: str, region: str) -> str:
    """Send one WAV chunk to the Speech REST API and return the display text."""
    url = (
        f"https://{region}.stt.speech.microsoft.com"
        "/speech/recognition/conversation/cognitiveservices/v1"
    )
    headers = {
        "Ocp-Apim-Subscription-Key": key,
        "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
    }
    params = {"language": "en-US", "format": "simple"}

    response = requests.post(
        url, headers=headers, params=params, data=chunk_bytes, timeout=120
    )
    if response.status_code != 200:
        print(f"[speech] API error {response.status_code}: {response.text[:200]}")
        return ""

    result = response.json()
    if result.get("RecognitionStatus") == "Success":
        return result.get("DisplayText", "")
    print(f"[speech] Chunk status: {result.get('RecognitionStatus')}")
    return ""


# ── Public API ────────────────────────────────────────────────────────────────

def transcribe_file(video_path: str) -> str:
    """
    Transcribe a local video file using the Azure AI Speech REST API.

    Extracts audio to a temporary WAV file via ffmpeg, splits it into
    55-second chunks, and transcribes each chunk via the REST API.

    Returns the full transcript as a single string.
    """
    if os.environ.get("MOCK_TRANSCRIPTION", "false").lower() == "true":
        print("[speech] MOCK mode – returning sample transcript")
        return MOCK_TRANSCRIPT.strip()

    key = os.environ["AZURE_SPEECH_KEY"]
    region = os.environ["AZURE_SPEECH_REGION"]

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name

    try:
        print(f"[speech] Extracting audio from '{video_path}' …")
        _extract_wav(video_path, wav_path)
        print("[speech] Audio extraction complete")

        chunks = _wav_chunks(wav_path)
        print(f"[speech] Transcribing {len(chunks)} chunk(s) via REST API …")

        parts: list[str] = []
        for i, chunk in enumerate(chunks, 1):
            text = _transcribe_chunk(chunk, key, region)
            if text:
                parts.append(text)
            print(f"[speech] Chunk {i}/{len(chunks)} – {len(text)} chars")

    finally:
        try:
            os.unlink(wav_path)
        except OSError:
            pass

    transcript = " ".join(parts)
    print(f"[speech] Transcription complete – {len(transcript)} characters")
    return transcript
