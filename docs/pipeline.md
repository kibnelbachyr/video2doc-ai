# Pipeline — Step-by-Step Reference

The documentation pipeline has five sequential steps, plus a deterministic
image-embedding pass right after generation. Each step is implemented as a
Python module in `src/` and called in order by `api/pipeline_runner.py`.
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

### Silence-aware WAV chunking

The Speech REST API's synchronous endpoint has a practical limit of ~60 seconds
of audio per request. Rather than cutting the WAV file at a blind fixed
interval (which can slice a sentence — or a word — in half right at a chunk
boundary), `ffmpeg`'s `silencedetect` filter is run first to find natural
pauses in the audio:

```python
cmd = [
    "ffmpeg", "-i", wav_path,
    "-af", "silencedetect=noise=-30dB:d=0.4",
    "-f", "null", "-",
]
```

Chunk boundaries then prefer the nearest detected silence inside the window
`[cursor + MIN_CHUNK_SECONDS, cursor + MAX_CHUNK_SECONDS]` (5–55 s), falling
back to a hard cut at 55 s only when no pause is found in range. Each chunk
is a self-contained WAV byte string (own RIFF header) tagged with its
absolute start time in the source video.

### REST API call

```
POST https://{region}.stt.speech.microsoft.com
     /speech/recognition/conversation/cognitiveservices/v1
     ?language={SPEECH_LANGUAGE}&format=detailed
Content-Type: audio/wav; codecs=audio/pcm; samplerate=16000
Ocp-Apim-Subscription-Key: {key}
```

`language` comes from the `SPEECH_LANGUAGE` env var (default `en-US`) — set
it to match the spoken language of the source video (e.g. `fr-FR`), otherwise
recognition quality degrades sharply. `format=detailed` (rather than `simple`)
is required to get the `NBest[0].Offset` field: the offset, in 100-ns ticks,
of where recognised speech actually starts within the chunk. Adding that
offset to the chunk's start time gives each transcript segment a precise
absolute timestamp, which is what lets the documentation generator later
align narration with the matching on-screen frame.

A successful response contains
`{ "RecognitionStatus": "Success", "NBest": [{ "Display": "...", "Offset": 12345000 }] }`.

### Output shape

`transcribe_file()` returns a list of `{"start": float_seconds, "text": str}`
segments (not a single string). `format_transcript()` renders them as a
`[MM:SS] text` block for the LLM prompt — the same timestamp format used for
the visual context, so both inputs share one timeline.

### Mock mode

`MOCK_TRANSCRIPTION=true` returns a hard-coded, timestamped product demo
transcript immediately without calling any Azure service or requiring `ffmpeg`.

---

## Step 2 — Frame extraction (`src/extract_frames.py`)

**Purpose:** Sample representative screenshots from the video for visual analysis.

**Tools used:** `ffmpeg` (local subprocess).

### Extraction strategy

Frames are extracted at a uniform rate controlled by `FRAMES_PER_MINUTE`
(default: `12`, meaning one frame every 5 seconds). Each extracted frame
keeps its absolute timestamp (`i * interval_sec`) alongside its path and
filename, so it can be matched against the transcript timeline later.

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
- Default `12` (1 every 5 s) favours a richly illustrated, well-synchronized
  document — the LLM is instructed to skip near-duplicate or blank frames
  rather than cluster them, so a denser sample rate improves coverage without
  forcing every frame into the output.
- For long, low-change technical recordings, `4–6` is usually enough.

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
    "timestamp": 75.0,
    "caption": "A CRM dashboard showing sales KPI cards and a navigation sidebar.",
    "ocr_text": "Total Leads: 1,240 | Active Deals: 87 | Revenue MTD: $142,500",
}
```

The `timestamp` is carried straight through from `extract_frames()` — it is
what lets `format_image_context()` place each frame on the same timeline as
the transcript.

### Format for the LLM

The `format_image_context()` function converts the list of frame results into
a compact, timestamped text block that is injected into the LLM prompt:

```
[00:05] frame_000001.png
  Visual: A product onboarding welcome screen with a company logo.
  Text on screen: Welcome to ContosoCRM | Version 3.2 | Get Started

[00:42] frame_000002.png
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

The system prompt uses five named blocks:

```
━━━ LANGUAGE RULE ━━━          — mandatory language detection + output rule
━━━ FIDELITY RULE ━━━          — stay faithful to transcript + visual context
━━━ IMAGE PLACEMENT RULE ━━━   — where and how to reference frames inline
━━━ OUTPUT FORMAT ━━━          — section structure and what each section must contain
━━━ QUALITY RULES ━━━          — Markdown formatting, backticks, blockquotes, depth
```

**Fidelity rule** — preserve exact terminology, menu names, and labels as
spoken or shown on screen rather than "improving" them into generic terms;
polish grammar and flow but never alter meaning or invent a step/UI element
that wasn't in the inputs; when the transcript and visual context disagree,
trust the visual context for what's on screen and the transcript for intent;
say so when information is genuinely missing rather than inventing detail.

**Image placement rule** — for every step or concept where a frame clearly
shows the screen being described, insert it inline immediately after the
sentence it illustrates, using the exact filename from the visual context:

```markdown
![Short, specific caption](frame_000004.png)
```

Frames are matched to text by timestamp proximity (both inputs share the
same `[MM:SS]` timeline — see below). The model is told to use as many
distinct frames as add real value, favouring a richly illustrated document,
but to skip near-duplicates or blank/transition frames, and to distribute
images at the point they're relevant instead of clustering them at the end
of a section.

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

### Retry on rate limiting

A large visual context (many frames × captions/OCR) can push a single
request's token count close to the GPT-4.1 deployment's TPM quota, especially
under concurrent jobs. Rather than failing the whole pipeline on the first
`429`, the call is retried with increasing backoff:

```python
max_attempts = 5
base_delay_seconds = 15   # Azure TPM quotas reset on a rolling 60s window
for attempt in range(1, max_attempts + 1):
    try:
        response = client.chat.completions.create(...)
        break
    except RateLimitError as exc:
        if attempt == max_attempts:
            raise
        time.sleep(base_delay_seconds * attempt)   # 15s, 30s, 45s, 60s
```

If all 5 attempts are exhausted, the `RateLimitError` propagates and the job
is marked `FAILED` as usual. See [Infrastructure](infrastructure.md#adjusting-capacity-without-a-redeploy)
for how to raise the deployment's TPM quota if this happens regularly.

### User message structure

```
## Timestamped Video Transcript
[00:00] {transcript}
...

---

## Timestamped Visual Context from Video Frames
[00:05] frame_000001.png
  Visual: ...
  Text on screen: ...
...

---

Detect the language of the transcript above, then generate the full Markdown
documentation in that same language, placing frames inline per the IMAGE
PLACEMENT RULE.
```

### Image embedding (post-processing)

The LLM only ever sees frame **filenames** as text — it has no way to emit
actual image bytes, and `max_tokens=8192` makes that mathematically
impossible for base64-sized payloads anyway. `embed_frame_images()` is what
turns the model's `![caption](frame_NNNNNN.png)` references into real,
self-contained images:

```python
encoded = base64.b64encode(frame_file.read_bytes()).decode("ascii")
return f"![{caption}](data:image/png;base64,{encoded})"
```

It runs once, right after `generate_documentation()` returns, by scanning the
Markdown for `![...](frame_NNNNNN.png)` patterns and resolving each one
against the real extracted frame file in the job's temp `frames/` directory.
A reference to a filename that doesn't exist (e.g. a hallucinated one) is
dropped rather than left as a broken image link. The result is a single
self-contained Markdown document with no external image dependencies.

---

## Step 5 — Result persistence

After the Markdown is generated and frame images embedded, the string is
uploaded to Blob Storage:

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
[speech]   Transcribing 4 chunk(s) via REST API (language=en-US) …
[speech]   Chunk 1/4 [00:00] – 312 chars
[speech]   Chunk 2/4 [00:52] – 287 chars
[speech]   Chunk 3/4 [01:38] – 341 chars
[speech]   Chunk 4/4 [02:21] – 195 chars
[speech]   Transcription complete – 4 segment(s), 1135 characters
[frames]   Extracted 36 frame(s) → '/tmp/.../frames/' (1 every 5.0s)
[vision]   Analysing 'frame_000001.png' [00:05] …
...
[vision]   Analysed 36 frame(s)
[llm]      Calling Azure AI Foundry deployment 'gpt-4.1' …
[llm]      Generation complete – 6210 tokens used, 24871 chars output
[embed]    Inlined 14 frame image(s) into the Markdown
[pipeline] Job abc123: DONE
```

Each prefix (`[pipeline]`, `[speech]`, `[frames]`, `[vision]`, `[llm]`, `[embed]`)
makes it easy to `grep` for failures in a specific step.

If the GPT-4.1 deployment is rate limited, `[llm]` logs a retry line per
attempt instead of immediately failing:

```
[llm]      Calling Azure AI Foundry deployment 'gpt-4.1' …
[llm]      Rate limited (attempt 1/5), retrying in 15s … (Error code: 429 - ...)
[llm]      Generation complete – 6210 tokens used, 24871 chars output
```
