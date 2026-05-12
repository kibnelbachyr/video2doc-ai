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

## Detailed architecture

### Service topology and pipeline

```
                ┌──────────────────────────────────────────────────────────────────────┐
                │  Azure Static Web Apps  ·  Free SKU  ·  westeurope                  │
                │  Vanilla JS  ·  French UI  ·  marked.js (CDN)                       │
                │  staticwebapp.config.json  ·  SPA navigation fallback               │
                │                                                                      │
                │  POST /api/jobs              multipart/form-data  (video ≤ 500 MB)  │
                │  GET  /api/jobs/{id}          poll every 2 s → { status, step }     │
                │  GET  /api/jobs/{id}/result   fetch Markdown when status = "done"   │
                └──────────────────────────────┬───────────────────────────────────────┘
                                               │ HTTP  (window.API_BASE_URL from ui/config.js)
                                               ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│  Azure Container Apps  ·  Consumption  ·  francecentral  ·  0–3 replicas  ·  port 8000        │
│  Image: python:3.11-slim + ffmpeg  ·  2 uvicorn workers  ·  non-root user (appuser:1000)      │
│                                                                                                 │
│  api/main.py         CORS middleware  ·  static file mount (ui/)  ·  GET /health → 200        │
│  api/routers/jobs.py                                                                            │
│    POST /api/jobs              → 202  (.mp4 .mov .avi .mkv .webm .wmv  ·  max 500 MB)         │
│    GET  /api/jobs/{id}         → 200 | 404  (status · step · result_url)                      │
│    GET  /api/jobs/{id}/result  → 200 | 409 | 422 | 500  (raw Markdown text)                   │
│  api/job_store.py    BlobServiceClient (conn str from KV)  ·  in-mem fallback (mock mode)     │
│                      state.json written to Blob after every pipeline step                      │
│                                                                                                 │
│  ─── api/pipeline_runner.py · daemon thread · tmp = mkdtemp(/tmp/v2doc_{id[:8]}_xxx) ───────  │
│                                                                                                 │
│  ┄ uploading ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄  │
│    video bytes ──▶ Blob  jobs/{id}/{filename}                                                  │
│    Blob  jobs/{id}/{filename} ──▶ tmp/{filename}                                               │
│                                                                                                 │
│  ┄ transcribing ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄  │
│    src/transcribe.py                                                                            │
│    ffmpeg: video ──▶ 16 kHz mono WAV ──▶ split into 55-second chunks                          │
│    POST each chunk ──────────────────────────────────────────────────────────────────────────▶ │ Azure AI Speech  S0
│    https://{region}.stt.speech.microsoft.com  ·  Ocp-Apim-Subscription-Key                    │ francecentral · REST
│    collect DisplayText ──▶ join with spaces ──▶ transcript string                ◀──────────── │ transcript text
│                                                                                                 │
│  ┄ extracting_frames ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄  │
│    src/extract_frames.py                                                                        │
│    ffmpeg -vf fps=1/{interval} ──▶ tmp/frames/frame_%06d.png         (local subprocess)        │
│    FRAMES_PER_MINUTE env var  (default: 2 = 1 frame per 30 s)                                  │
│                                                                                                 │
│  ┄ analyzing_images ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄  │
│    src/analyze_images.py                                                                        │
│    per PNG: ImageAnalysisClient.analyze(image_bytes, [CAPTION, READ], language="en")           │
│    ────────────────────────────────────────────────────────────────────────────────────────▶   │ Azure AI Vision 4.0  S1
│    caption text + OCR lines ──▶ format_image_context()               ◀────────────────────── │ francecentral · SDK
│    [frame_%06d.png]  Visual: …  Text on screen: …                                             │ AzureKeyCredential
│                                                                                                 │
│  ┄ generating_docs ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄  │
│    src/generate_docs.py                                                                         │
│    AzureOpenAI(azure_endpoint, api_key, api_version=2025-04-01-preview)                        │
│    model=gpt-4.1  ·  temperature=0.2  ·  max_tokens=8192                                       │
│    system: Diátaxis (language rule · output format · quality rules)  ─────────────────────▶   │ Azure AI Foundry
│    user: transcript + visual context blocks                                                     │ GPT-4.1  50k TPM
│    Markdown: Tutorial · How-to Guide · Reference · Explanation  (auto-language) ◀──────────── │ S0 GlobalStandard
│                                                                                                 │
│  result.md ──▶ Blob  jobs/{id}/result.md  ·  update_job(DONE)  ·  shutil.rmtree(tmp)          │
└──────────────────────────────────────────────────────────┬──────────────────────────────────────┘
                                                           │
               ┌───────────────────────────────────────────┤
               │                                            │
               │ Managed Identity                           │ conn str (loaded from KV at startup)
               ▼                                            ▼
┌──────────────────────────────────────────────┐  ┌────────────────────────────────────────────┐
│  User-Assigned Managed Identity              │  │  Azure Blob Storage  ·  Standard LRS       │
│  id-v2doc-{suffix}-api                       │  │  francecentral  ·  HTTPS only  ·  TLS 1.2  │
└──────────────┬──────────────────┬────────────┘  │  no public container access                │
               │ AcrPull          │ Key Vault       │                                            │
               │ (RBAC)          │ Secrets User    │  container: jobs                           │
               │                  │ (RBAC)          │  ├─ {id}/state.json                       │
               ▼                  ▼                 │  │    status · step · error               │
┌──────────────────────┐  ┌──────────────────────┐ │  │    video_filename · timestamps         │
│  Azure Container     │  │  Azure Key Vault      │ │  ├─ {id}/{video_filename}                │
│  Registry  ·  Basic  │  │  Standard  ·  RBAC    │ │  └─ {id}/result.md                      │
│  acr{suffix}         │  │  francecentral         │ │                                            │
│  Docker image store  │  │  soft-delete: 7 days  │ │  container: video-input  (CLI only)       │
└──────────────────────┘  │                        │ │  container: doc-output   (CLI only)       │
                          │  speech-key             │ └────────────────────────────────────────────┘
                          │  vision-key             │
                          │  openai-key             │
                          │  storage-conn-string    │
                          └──────────────────────────┘
```

### Security model

```
   ┌──────────────────────────┐          ┌──────────────────────────┐
   │  Azure Key Vault         │          │  Azure Container         │
   │  (speech-key)            │          │  Registry                │
   │  (vision-key)            │          │  (Docker image)          │
   │  (openai-key)            │          └──────────┬───────────────┘
   │  (storage-conn)          │                     │  AcrPull role
   └──────────┬───────────────┘                     │  (RBAC)
              │  Key Vault Secrets User role         │
              │  (RBAC)                              │
              └──────────────────┬───────────────────┘
                                 │
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
using Azure's RBAC (`Key Vault Secrets User` role). The same identity holds
the `AcrPull` role on the Container Registry so image pulls require no
admin password.

### CI/CD pipeline

```
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│  GitHub Actions  ·  OIDC auth (no long-lived secrets)                                        │
│  Secrets: AZURE_CLIENT_ID  ·  AZURE_TENANT_ID  ·  AZURE_SUBSCRIPTION_ID                    │
│                                                                                              │
│  deploy-infra.yml  (trigger: push to infra/**)  ──────────────────────────────────────────  │
│    az deployment group create                                                                │
│    --template-file infra/main.bicep  --parameters @infra/main.bicepparam                   │
│    → provisions all resources in one pass:                                                   │
│       SWA · Container Apps · ACR · Speech · Vision · AI Foundry · KV · Blob                │
│                                                                                              │
│  deploy-app.yml  (trigger: push to api/** · src/** · ui/** · Dockerfile)  ────────────────  │
│    ① az acr build ──▶ acr{suffix}.azurecr.io/video2doc-api:{sha} + :latest                 │
│       (cloud build inside Azure — no local Docker daemon required)                           │
│    ② az containerapp update ──▶ new image  acr{suffix}.azurecr.io/video2doc-api:{sha}      │
│    ③ generate ui/config.js    window.API_BASE_URL = https://{aca-fqdn}  (file is gitignored)│
│    ④ Azure/static-web-apps-deploy ──▶ ui/  (secret: AZURE_STATIC_WEB_APPS_API_TOKEN)       │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
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
the file is split into 55-second chunks (the REST API's practical limit for
synchronous calls).

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
