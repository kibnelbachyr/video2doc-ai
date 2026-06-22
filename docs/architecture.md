# Architecture

This page explains the design decisions, component interactions, and data flow
of the video2doc-ai solution.

---

## Overview

video2doc-ai is a **cloud-native documentation pipeline** composed of three layers:

| Layer | Technology | Responsibility |
|-------|-----------|----------------|
| Frontend | Azure Static Web Apps (vanilla JS) | File upload, progress display, Markdown render |
| Backend | Azure Container Apps (FastAPI) | REST API, job orchestration, pipeline execution |
| AI Services | Azure AI Speech · Vision · Foundry | Transcription, image analysis, doc generation |

All state is persisted in **Azure Blob Storage** so the API is stateless and can
scale to zero or run multiple replicas without losing job data.

---

## Component diagram

```
Browser (SWA)
   │
   │  POST /api/jobs  (multipart video upload)
   │  GET  /api/jobs/{id}  (polling, every 2 s)
   │  GET  /api/jobs/{id}/result
   ▼
FastAPI  (Azure Container App)
   │
   ├── api/main.py           ← entry point, CORS, static file mount
   ├── api/routers/jobs.py   ← HTTP endpoints
   ├── api/job_store.py      ← read/write job state to Blob
   └── api/pipeline_runner.py
           │  (background thread)
           │
           ├── src/transcribe.py      ──▶  Azure AI Speech  (REST)
           ├── src/extract_frames.py  ──▶  ffmpeg  (local subprocess)
           ├── src/analyze_images.py  ──▶  Azure AI Vision  (SDK)
           └── src/generate_docs.py   ──▶  Azure AI Foundry / GPT-4.1  (openai SDK)
                                               │
                                               ▼
                                      Azure Blob Storage
                                        jobs/{id}/state.json
                                        jobs/{id}/{video}
                                        jobs/{id}/result.md
```

---

## Request lifecycle

```
1. Browser           POST /api/jobs  (video file as multipart/form-data)
2. FastAPI router    Validate file extension and size
3. job_store         Create JobState (status=pending, step=uploading)
                     Upload video bytes → Blob Storage  jobs/{id}/{filename}
4. FastAPI router    Launch background thread  →  run_pipeline(job_id)
                     Return HTTP 202  { job_id, status: "pending" }

5. Background thread:
   a. download_video()      Blob → local temp directory
   b. update_job(TRANSCRIBING)
   c. transcribe_file()     ffmpeg WAV → Azure AI Speech REST → transcript text
   d. update_job(EXTRACTING_FRAMES)
   e. extract_frames()      ffmpeg → PNG files in temp dir
   f. update_job(ANALYZING_IMAGES)
   g. analyze_frames()      each PNG → Azure AI Vision → caption + OCR text
   h. update_job(GENERATING_DOCS)
   i. generate_documentation()  transcript + vision context → GPT-4.1 → Markdown
   j. save_result()         Markdown → Blob Storage  jobs/{id}/result.md
   k. update_job(DONE)

6. Browser polls GET /api/jobs/{id}  →  reads state.json from Blob
7. Browser GET /api/jobs/{id}/result →  reads result.md from Blob
```

---

## State machine

```
           ┌─────────┐
           │ PENDING │  (created, video uploading)
           └────┬────┘
                │
           ┌────▼──────────┐
           │  PROCESSING   │
           │               │
           │  transcribing │
           │       ↓       │
           │  extracting   │
           │    _frames    │
           │       ↓       │
           │  analyzing    │
           │    _images    │
           │       ↓       │
           │  generating   │
           │     _docs     │
           └────┬──────┬───┘
                │      │
           ┌────▼──┐ ┌─▼──────┐
           │  DONE │ │ FAILED │
           └───────┘ └────────┘
```

Each step update is a write to `jobs/{id}/state.json` in Blob Storage,
so the current step is always durable and visible to any polling client.

---

## Technology choices and trade-offs

### Why FastAPI + background thread (not Azure Functions)?

For a PoC, a background thread inside the same process is simpler to reason about,
deploy, and debug. The downside is that a crash of the Container App kills running
pipelines. For production, the recommended upgrade is **Azure Durable Functions**
or a dedicated worker reading from **Azure Queue Storage**.

### Why Azure Blob Storage for job state (not a database)?

Blob Storage is already required for video and result files. Storing the small
`state.json` document in the same container keeps the infrastructure minimal:
no managed database, no connection pool, no migration scripts. At PoC scale
(one job at a time) the extra read/write latency is negligible.

### Why REST API for Azure AI Speech (not the Speech SDK)?

The Azure AI Speech SDK requires an audio platform (ALSA on Linux) even when
used for file transcription, causing `Failed to initialize platform` errors
in headless containers. The REST API accepts plain HTTP POST with a WAV body
and works in any environment. ffmpeg extracts a 16 kHz mono WAV first, then
the file is split into chunks of at most 55 seconds (the REST API's practical
limit for synchronous calls) — boundaries are chosen at the nearest detected
silence (`ffmpeg silencedetect`) rather than a blind fixed interval, so a
sentence or word is never cut mid-way at a chunk edge.

### Why ffmpeg for frames (not OpenCV)?

OpenCV's bundled FFmpeg does not include hardware-assisted AV1 or HEVC software
decoders on all platforms. The system `ffmpeg` package handles every codec
(AV1, HEVC/H.265, VP9, H.264, MPEG-4) and produces zero-dependency PNGs. This
also removes the heavyweight `opencv-python-headless` package from the container.

### Why Azure AI Foundry (not Azure OpenAI Service)?

Azure AI Foundry (`kind: AIServices`) is Microsoft's 2025 resource model that
unifies model deployment, monitoring, and the ai.azure.com portal experience.
It uses the standard `openai` Python package pointed at a
`*.cognitiveservices.azure.com` endpoint — identical code, future-proof resource.

### Why scale-to-zero on Container Apps?

During a PoC there are long idle periods between jobs. The `minReplicas: 0`
setting means the Container App shuts down completely when idle, incurring
zero compute cost. The trade-off is a cold-start delay (~10–30 s) on the first
request after idle. For production, set `minReplicas: 1`.

### Why Azure Static Web Apps Free SKU?

The Free SKU is sufficient for serving static HTML/CSS/JS files. The UI calls
the Container App API directly using a `window.API_BASE_URL` injected at deploy
time via a gitignored `config.js` file. The Standard SKU's "linked backend"
feature was evaluated but rejected because it installs an auth sidecar on the
Container App that rejects unauthenticated requests.

---

## Security model

```
                      ┌──────────────────────────┐
                      │  Azure Key Vault         │
                      │  (speech-key)            │
                      │  (vision-key)            │
                      │  (openai-key)            │
                      │  (storage-conn)          │
                      └──────────┬───────────────┘
                                 │  Key Vault Secrets User role
                                 │  (RBAC)
                      ┌──────────▼───────────────┐
                      │  User-Assigned Managed   │
                      │  Identity                │
                      │  (id-v2doc-xxx-api)      │
                      └──────────┬───────────────┘
                                 │  assigned to
                      ┌──────────▼───────────────┐
                      │  Container App           │
                      │  (reads secrets at boot) │
                      └──────────────────────────┘
```

No credentials are stored in the container image or environment variable
plain text. The Managed Identity fetches secrets from Key Vault at startup
using Azure's RBAC (`Key Vault Secrets User` role). The Container Registry
is pulled using `AcrPull` role on the same identity — no admin password.

---

## Limitations (PoC scope)

| Concern | Current behaviour | Production upgrade |
|---------|------------------|-------------------|
| Long videos (>10 min) | Chunked 55-s REST calls; quality degrades | Azure Batch Transcription API |
| Concurrent jobs | Shares one Container App process | Worker queue + dedicated workers |
| Authentication | None on the API | Azure Static Web Apps built-in auth (AAD) |
| CORS | Allow-all origins | Restrict to SWA hostname |
| Frame selection | Uniform time sampling | Azure AI Video Indexer scene detection |
| Observability | Container App log stream only | App Insights + Log Analytics |
| Data residency | `GlobalStandard` may route outside France | `DataZoneStandard` SKU in `main.bicep` |
| LLM rate limits | Retries on `429` with increasing backoff (15/30/45/60 s); job fails after 5 attempts | Raise `openAICapacity` further, or move to a dedicated provisioned-throughput deployment |
