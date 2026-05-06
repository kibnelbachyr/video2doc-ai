"""
transcribe.py
-------------
Transcribe a local video/audio file using Azure AI Speech SDK.

Two modes:
  • Real  – uses azure-cognitiveservices-speech for continuous recognition
            on a WAV/MP3/MP4 file (Speech SDK supports compressed audio via GStreamer).
  • Mock  – returns a hard-coded transcript so the rest of the pipeline
            can run without Azure credentials during local dev.

NOTE: For files longer than a few minutes the recommended production approach
is Azure Batch Transcription REST API, which is asynchronous and handles large
files natively. See `_batch_transcription_stub()` below for guidance.
"""

import os
import subprocess
import tempfile
import threading
import azure.cognitiveservices.speech as speechsdk


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


# ── Real transcription ────────────────────────────────────────────────────────

def _extract_wav(video_path: str, wav_path: str) -> None:
    """Extract mono 16 kHz PCM WAV from a video file using ffmpeg."""
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-ac", "1",         # mono
        "-ar", "16000",     # 16 kHz – optimal for Speech SDK
        "-vn",              # drop video stream
        wav_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extraction failed:\n{result.stderr}")


def transcribe_file(video_path: str) -> str:
    """
    Transcribe a local video file using Azure AI Speech continuous recognition.

    Extracts audio to a temporary WAV file via ffmpeg, then feeds it to the
    Speech SDK. WAV/PCM is supported natively without GStreamer.

    Returns the full transcript as a single string.
    """
    if os.environ.get("MOCK_TRANSCRIPTION", "false").lower() == "true":
        print("[speech] MOCK mode – returning sample transcript")
        return MOCK_TRANSCRIPT.strip()

    key = os.environ["AZURE_SPEECH_KEY"]
    region = os.environ["AZURE_SPEECH_REGION"]

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name

    print(f"[speech] Extracting audio from '{video_path}' → '{wav_path}' …")
    _extract_wav(video_path, wav_path)
    print("[speech] Audio extraction complete")

    speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
    speech_config.speech_recognition_language = "en-US"
    speech_config.output_format = speechsdk.OutputFormat.Detailed

    audio_config = speechsdk.audio.AudioConfig(filename=wav_path)
    recognizer = speechsdk.SpeechRecognizer(
        speech_config=speech_config,
        audio_config=audio_config,
    )

    transcript_parts: list[str] = []
    done = threading.Event()

    def on_recognized(evt: speechsdk.SpeechRecognitionEventArgs) -> None:
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            transcript_parts.append(evt.result.text)

    def on_session_stopped(evt) -> None:  # noqa: ANN001
        done.set()

    def on_canceled(evt: speechsdk.SpeechRecognitionCanceledEventArgs) -> None:
        if evt.result.reason == speechsdk.ResultReason.Canceled:
            details = evt.result.cancellation_details
            print(f"[speech] Recognition canceled: {details.reason} – {details.error_details}")
        done.set()

    recognizer.recognized.connect(on_recognized)
    recognizer.session_stopped.connect(on_session_stopped)
    recognizer.canceled.connect(on_canceled)

    print(f"[speech] Starting transcription …")
    recognizer.start_continuous_recognition()
    done.wait(timeout=600)  # 10-minute safety cap
    recognizer.stop_continuous_recognition()

    try:
        os.unlink(wav_path)
    except OSError:
        pass

    transcript = " ".join(transcript_parts)
    print(f"[speech] Transcription complete – {len(transcript)} characters")
    return transcript


# ── Production stub ───────────────────────────────────────────────────────────

def _batch_transcription_stub(blob_sas_url: str) -> None:
    """
    STUB – shows how to trigger Azure Batch Transcription for long files.

    Production steps:
    1. Upload video to Blob Storage and generate a SAS URL.
    2. POST to https://<region>.api.cognitive.microsoft.com/speechtotext/v3.2/transcriptions
       with a JSON body pointing at the SAS URL.
    3. Poll GET on the returned transcription URL until status == "Succeeded".
    4. Download the result JSON and extract the Display text.

    Reference:
      https://learn.microsoft.com/azure/ai-services/speech-service/batch-transcription
    """
    raise NotImplementedError(
        "Batch transcription is not implemented in this POC. "
        "See the docstring for production guidance."
    )
