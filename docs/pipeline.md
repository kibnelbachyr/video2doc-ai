# Pipeline — Step-by-Step Reference

The documentation pipeline has five sequential steps. Each step is implemented
as a Python module in `src/` and called in order by `api/pipeline_runner.py`.
Every step updates the job state in Blob Storage so the UI can show live progress.

---

## Pipeline runner (`api/pipeline_runner.py`)

The runner is started as a **daemon thread** immediately after the video upload
completes. It receives the `job_id` and reads the job state from Blob Storage
to find the video filename.

```python
threading.Thread(target=run_pipeline, args=(state.job_id,), daemon=True).start()
```

The runner uses a `try / except / finally` block:

- **try** — runs all five steps sequentially; any exception jumps to `except`
- **except** — logs the full traceback and writes `status=FAILED` + `error` to Blob
- **finally** — always deletes the temporary directory, preventing disk leaks

### Temporary directory

Each job gets a private temp directory:

```
/tmp/v2doc_<first-8-chars-of-job-id>_<random>/
├── <video_filename>        ← downloaded from Blob Storage
└── frames/
    ├── frame_000001.png
    ├── frame_000002.png
    └── ...
```

The directory is created with `tempfile.mkdtemp()` and removed with
`shutil.rmtree()` in the `finally` block regardless of success or failure.

### Mock mode

When **both** `MOCK_TRANSCRIPTION=true` and `MOCK_VISION=true` are set, the
runner skips the Blob download and uses hard-coded sample data throughout.
Results are stored in a process-level Python dict (`_MOCK_RESULTS`) instead
of Blob Storage, making the API fully functional with no Azure credentials.

---

## Step 1 — Audio transcription (`src/transcribe.py`)

**Purpose:** Convert spoken words in the video to text.

**Tools used:** `ffmpeg` (audio extraction) + Azure AI Speech REST API.

### Why ffmpeg first?

The Azure AI Speech REST API accepts only PCM/WAV audio. Rather than using
the Speech SDK (which requires audio platform init — broken in headless
containers), the audio is extracted first using ffmpeg.

### Audio extraction

```python
cmd = [
    "ffmpeg", "-y", "-i", video_path,
    "-ac", "1",       # mono
    "-ar", "16000",   # 16 kHz — optimal for Speech API
    "-vn",            # drop video stream
    wav_path,
]
```

This produces a temporary `.wav` file that works with any video container
or codec (MP4/H.264, MKV/AV1, WebM/VP9, etc.).

### WAV chunking

The Speech REST API's synchronous endpoint has a practical limit of ~60 seconds
of audio per request. The WAV file is split into **55-second chunks**, each
being a self-contained WAV byte string (with its own RIFF header).

```python
frames_per_chunk = rate * 55          # e.g. 16000 * 55 = 880,000 frames
```

Each chunk is sent as a separate POST request and the returned `DisplayText`
strings are joined with spaces.

### REST API call

```
POST https://{region}.stt.speech.microsoft.com
     /speech/recognition/conversation/cognitiveservices/v1
     ?language=en-US&format=simple
Content-Type: audio/wav; codecs=audio/pcm; samplerate=16000
Ocp-Apim-Subscription-Key: {key}
```

A successful response contains `{ "RecognitionStatus": "Success", "DisplayText": "..." }`.

### Mock mode

`MOCK_TRANSCRIPTION=true` returns a hard-coded product demo transcript
immediately without calling any Azure service or requiring `ffmpeg`.

---

## Step 2 — Frame extraction (`src/extract_frames.py`)

**Purpose:** Sample representative screenshots from the video for visual analysis.

**Tools used:** `ffmpeg` (local subprocess).

### Extraction strategy

Frames are extracted at a uniform rate controlled by `FRAMES_PER_MINUTE`
(default: `2`, meaning one frame every 30 seconds).

```python
interval_sec = 60.0 / frames_per_minute    # e.g. 30.0 seconds
cmd = [
    "ffmpeg", "-y",
    "-i", video_path,
    "-vf", f"fps=1/{interval_sec:.6f}",    # e.g. fps=1/30.000000
    "-vsync", "vfr",                        # variable frame rate output
    "frames/frame_%06d.png",
]
```

Output files are zero-padded PNGs: `frame_000001.png`, `frame_000002.png`, …

### Why ffmpeg instead of OpenCV?

OpenCV's bundled FFmpeg does not decode AV1 video (a modern codec used by
screen recorders and some cameras) without additional platform libraries.
The system `ffmpeg` package in the container handles all codecs natively,
including AV1 (`libaom-av1`), HEVC/H.265, VP9, H.264, and MPEG-4.

### Tuning `FRAMES_PER_MINUTE`

- **Higher values** → more frames → richer visual context → more Vision API
  calls → higher cost and slower pipeline.
- **Lower values** → fewer frames → cheaper → may miss important screens.
- Default `2` works well for most product demo videos (5–15 min).
- For slide-heavy recordings, try `4–6`. For long technical recordings, `1`.

### Mock mode

`MOCK_VISION=true` causes this step to return an empty list immediately.
The subsequent analysis step returns pre-canned mock data in that case.

---

## Step 3 — Image analysis (`src/analyze_images.py`)

**Purpose:** Extract semantic descriptions and on-screen text from each frame.

**Tools used:** Azure AI Vision 4.0 Image Analysis SDK.

### What is extracted per frame

For each PNG the Vision API is called with two `VisualFeatures`:

| Feature | What it returns |
|---------|----------------|
| `CAPTION` | One natural-language sentence describing the whole image |
| `READ` | All text visible in the image (OCR), line by line |

Example result for a single frame:

```python
{
    "frame": "frame_000003.png",
    "caption": "A CRM dashboard showing sales KPI cards and a navigation sidebar.",
    "ocr_text": "Total Leads: 1,240 | Active Deals: 87 | Revenue MTD: $142,500",
}
```

### Format for the LLM

The `format_image_context()` function converts the list of frame results into
a compact text block that is injected into the LLM prompt:

```
[frame_000001.png]
  Visual: A product onboarding welcome screen with a company logo.
  Text on screen: Welcome to ContosoCRM | Version 3.2 | Get Started

[frame_000002.png]
  Visual: A navigation sidebar with menu items highlighted.
  Text on screen: Dashboard | Leads | Deals | Reports | Settings
```

### Mock mode

`MOCK_VISION=true` returns three hard-coded frame results (dashboard, filter
panel, export wizard) without calling the Vision API or needing frame files.

---

## Step 4 — Documentation generation (`src/generate_docs.py`)

**Purpose:** Transform the transcript and visual context into structured
Markdown documentation.

**Tools used:** Azure AI Foundry (GPT-4.1) via the `openai` Python package.

### Language auto-detection

The system prompt contains a mandatory language rule:

> Detect the primary language of the transcript.  
> Generate ALL documentation in that same detected language.  
> French transcript → French output. English transcript → English output.  
> Empty or indeterminate transcript → English.

GPT-4.1 is highly reliable at language detection from transcript text
and at generating fluent documentation in both French and English.
No additional library or pre-processing is needed.

### Diátaxis output format

The system prompt requires exactly four sections:

| Section | Purpose |
|---------|---------|
| **Tutorial** | Step-by-step learning walkthrough for new users |
| **How-to Guide** | Task-oriented numbered instructions for common tasks |
| **Reference** | Tables of all UI elements, parameters, and terms |
| **Explanation** | Conceptual background, architecture, trade-offs |

### System prompt design

The system prompt uses three named blocks:

```
━━━ LANGUAGE RULE ━━━     — mandatory language detection + output rule
━━━ OUTPUT FORMAT ━━━     — section structure and what each section must contain
━━━ QUALITY RULES ━━━     — Markdown formatting, backticks, blockquotes, depth
```

Key rules enforced:

- Use `backticks` for UI element names, code, and technical terms
- Use `>` blockquotes for tips and warnings
- Never leave a section empty; draw from visual context if transcript is sparse
- Target production-quality depth, not a summary

### API call parameters

```python
client.chat.completions.create(
    model=deployment,           # gpt-4.1 (Azure AI Foundry deployment name)
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": user_message},
    ],
    temperature=0.2,            # low — factual, deterministic output
    max_tokens=8192,            # supports long documents
)
```

Temperature `0.2` is deliberately low to minimise hallucination and keep the
output grounded in the provided transcript and visual context.

### User message structure

```
## Video Transcript
{transcript}

---

## Visual Context from Video Frames
[frame_000001.png]
  Visual: ...
  Text on screen: ...
...

---

Detect the language of the transcript above, then generate the full Markdown
documentation in that same language.
```

---

## Step 5 — Result persistence

After `generate_documentation()` returns, the Markdown string is uploaded to
Blob Storage:

```
jobs/{job_id}/result.md
```

The job state is then updated to `status=DONE, step=done`. The next poll from
the browser will see `status: "done"` and the `result_url` field populated,
triggering a `GET /api/jobs/{id}/result` call to retrieve the Markdown.

---

## Log output

The pipeline emits structured log lines at every step. In Container Apps
these appear in the log stream (`az containerapp logs show --follow`):

```
[pipeline] Job abc123: thread started
[pipeline] Job abc123: video=demo.mp4 mock=False
[pipeline] Job abc123: downloading video from blob …
[pipeline] Job abc123: download complete → /tmp/v2doc_abc12300_xxxx/demo.mp4
[speech]   Extracting audio from '/tmp/.../demo.mp4' …
[speech]   Audio extraction complete
[speech]   Transcribing 4 chunk(s) via REST API …
[speech]   Chunk 1/4 – 312 chars
[speech]   Chunk 2/4 – 287 chars
[speech]   Chunk 3/4 – 341 chars
[speech]   Chunk 4/4 – 195 chars
[speech]   Transcription complete – 1135 characters
[frames]   Extracted 16 frame(s) → '/tmp/.../frames/'
[vision]   Analysing 'frame_000001.png' …
...
[vision]   Analysed 16 frame(s)
[llm]      Calling Azure AI Foundry deployment 'gpt-4.1' …
[llm]      Generation complete – 4474 tokens used, 18342 chars output
[pipeline] Job abc123: DONE
```

Each prefix (`[pipeline]`, `[speech]`, `[frames]`, `[vision]`, `[llm]`)
makes it easy to `grep` for failures in a specific step.
