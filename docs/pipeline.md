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

Frame extraction is a two-phase process that picks the `MAX_FRAMES`
(default: `12`) **most visually-distinct moments** in the video, instead of
blindly sampling on a fixed time grid:

**1. Dense candidate sampling** — a pool of roughly `MAX_FRAMES * 10`
candidate frames is sampled uniformly across the video:

```python
duration = _get_duration(video_path)                       # via ffprobe
candidate_interval = max(1.0, duration / (max_frames * 10))
```

The 1-second floor means short videos always yield at least one candidate
per second, so a video shorter than `MAX_FRAMES * 10` seconds never produces
zero frames.

**2. Greedy diversity selection (farthest-point / k-center)** — each
candidate is also rendered as a tiny 8×8 grayscale thumbnail. Starting from
candidate 0 (the establishing frame), the algorithm repeatedly picks the
candidate whose nearest already-selected neighbour is the most different
(largest sum of absolute pixel differences across the thumbnail), until
`MAX_FRAMES` are selected or all candidates are exhausted. If there are
fewer candidates than `MAX_FRAMES`, all of them are kept.

Both the full-resolution candidate PNGs and the grayscale thumbnails are
produced by a **single ffmpeg invocation** using `filter_complex` + `split`,
so the video is decoded only once:

```python
cmd = [
    "ffmpeg", "-y", "-i", video_path,
    "-filter_complex",
    f"[0:v]fps=1/{candidate_interval:.6f},split=2[full][thumbsrc];"
    f"[thumbsrc]scale=8:8:flags=area,format=gray[thumb]",
    "-map", "[full]", "-vsync", "vfr", "frames/frame_%06d.png",
    "-map", "[thumb]", "-vsync", "vfr",
    "-f", "rawvideo", "-pix_fmt", "gray", "frames/thumbs.raw",
]
```

Candidates that aren't selected are deleted; the remaining PNGs (sorted by
time) are returned. Output files are zero-padded: `frame_000001.png`,
`frame_000002.png`, …

If the dual-output pass produces no candidates at all (an unreadable or
zero-frame video), a final fallback extracts just the first frame so visual
context is never empty.

### Why diversity selection instead of uniform sampling or scene detection?

- **Uniform sampling** (one frame every N seconds) is "random" with respect
  to content — it can repeatedly land on the same static screen while
  missing one that only appears briefly between two sample points.
- **ffmpeg's `scene` change metric** (tried previously) fires constantly on
  continuous motion in animated/cartoon content regardless of threshold,
  producing frames that don't correspond to meaningful topic changes.
- **Diversity selection** compares actual frame content (via thumbnails) and
  keeps the set of `MAX_FRAMES` candidates that look most different from
  each other — robust to both static screen recordings and animated video,
  and always bounded by `MAX_FRAMES` regardless of how much motion there is.

### Why ffmpeg instead of OpenCV?

OpenCV's bundled FFmpeg does not decode AV1 video (a modern codec used by
screen recorders and some cameras) without additional platform libraries.
The system `ffmpeg` package in the container handles all codecs natively,
including AV1 (`libaom-av1`), HEVC/H.265, VP9, H.264, and MPEG-4.

### Tuning `MAX_FRAMES`

- **Higher values** → more key frames → richer visual context → more Vision
  API calls → higher cost and slower pipeline.
- **Lower values** → fewer key frames → cheaper → may miss important screens.
- Default `12` works well for most product demo videos (5–15 min).
- For slide-heavy or highly visual recordings, try `16–24`. For short or
  simple recordings, `6–8` is often enough.

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

### Inline key frames

A fourth named block, `━━━ VISUAL REFERENCES ━━━`, instructs the model to
embed the most relevant frames directly inside the Tutorial, How-to Guide,
or Explanation sections — right next to the step or concept they illustrate —
using standard Markdown image syntax with the **exact** filename from the
visual context:

```markdown
Click the **Export** button in the top-right corner.

![Export wizard dialog with format options](frame_003000.png)
```

Rules enforced by the prompt:

- Use the exact `frame_XXXXXX.png` filename from the visual context — never
  an invented name.
- Reference each frame at most once, only where it adds real value.
- Never embed images inside Reference tables.

---

## Step 4.5 — Inline image embedding (`src/frame_embed.py`)

**Purpose:** Turn the LLM's `![alt](frame_XXXXXX.png)` references into a
self-contained document by inlining the actual frame as a base64 `data:` URI.

```python
frame_images = load_frame_images(frame_paths)        # before generation
markdown      = generate_documentation(transcript, image_context)
markdown      = embed_inline_images(markdown, frame_images)  # after generation
```

- `load_frame_images()` reads each extracted frame, **downscaling it via
  ffmpeg to `FRAME_EMBED_MAX_WIDTH`** (default `640px`, never upscaled,
  aspect ratio preserved), keyed by filename (e.g. `frame_000003.png`).
  Vision analysis already ran on the full-resolution original — only the
  copy embedded in the document is shrunk.
- `embed_inline_images()` regex-matches `![alt](frame_XXXXXX.png)` references
  in the generated Markdown and replaces the `src` with
  `data:image/png;base64,<...>`.
- Any reference to a frame that doesn't exist (a hallucinated filename) is
  **silently removed**, so the document never shows a broken image icon.

Because the images are embedded as data URIs, the resulting `result.md` is
fully self-contained — it renders correctly in the web preview, when
downloaded, and in any standard Markdown viewer, with no extra files or
endpoints required. The web preview additionally caps the display size via
CSS (`#markdown-preview img`, max `480px` wide) so images sit comfortably
alongside the surrounding text.

### Mock mode

`MOCK_VISION=true` has no real frame files on disk. `load_frame_images()`
instead returns three small generated placeholder PNGs (different solid
colours) keyed by the same filenames as `analyze_images.MOCK_IMAGE_RESULTS`
(`frame_000000.png`, `frame_001500.png`, `frame_003000.png`), so the inline
embedding feature works end-to-end even without ffmpeg or Azure AI Vision.

---

## Step 5 — Result persistence

After `generate_documentation()` returns and inline images are embedded, the
Markdown string is uploaded to Blob Storage:

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
[frames]   Extracted 12 key frame(s) from 87 candidate(s) → '/tmp/.../frames/'
[vision]   Analysing 'frame_000001.png' …
...
[vision]   Analysed 12 frame(s)
[llm]      Calling Azure AI Foundry deployment 'gpt-4.1' …
[llm]      Generation complete – 4474 tokens used, 18342 chars output
[embed]    Embedded 4 inline frame image(s)
[pipeline] Job abc123: DONE
```

Each prefix (`[pipeline]`, `[speech]`, `[frames]`, `[vision]`, `[llm]`, `[embed]`)
makes it easy to `grep` for failures in a specific step.
