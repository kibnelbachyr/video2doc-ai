# video2doc-ai

> **Generate structured, multi-language product documentation from internal videos using Azure AI.**

Give it a video recording of a product demo, training session, or technical walkthrough.
It transcribes the audio, analyses the screen visuals, and produces ready-to-publish
Markdown documentation in the **Diátaxis** format — automatically in the same language
as the video (French or English).

---

## How it works

```
┌─────────────┐     POST /api/jobs      ┌──────────────────────────────────────────┐
│  Browser UI │ ───────────────────────▶│          FastAPI  (Container App)        │
│  (SWA)      │ ◀─── job_id + polling ──│                                          │
└─────────────┘                         │  1. Upload video  → Azure Blob Storage   │
                                        │  2. Transcribe    → Azure AI Speech       │
                                        │  3. Extract frames→ ffmpeg               │
                                        │  4. Analyse frames→ Azure AI Vision      │
                                        │  5. Generate docs → Azure AI Foundry     │
                                        │                      GPT-4.1             │
                                        └──────────────────────────────────────────┘
```

The browser uploads a video file. The API spawns a background thread that runs
the five-step pipeline, updating a job state document in Blob Storage after each step.
The browser polls every 2 seconds and shows live progress; when the job completes it
renders the generated Markdown inline and offers download.

---

## Architecture

```
                    ┌──────────────────────────┐
                    │  Azure Static Web Apps   │
                    │  (React-less SPA / UI)   │
                    └────────────┬─────────────┘
                                 │ POST /api/jobs
                                 │ GET  /api/jobs/{id}
                                 ▼
                    ┌──────────────────────────┐
                    │  Azure Container Apps    │
                    │  FastAPI (api/)          │◀── Managed Identity
                    └────────────┬─────────────┘         │
                                 │                        │
      ┌──────────────────────────┼───────────────┐        │
      ▼                          ▼               ▼        ▼
┌──────────────────┐  ┌─────────────────────┐  ┌──────────────────┐
│  Azure AI Speech │  │  Azure AI Vision    │  │  Azure Key Vault │
│  (transcription) │  │  (caption + OCR)    │  │  (secrets)       │
└──────────────────┘  └─────────────────────┘  └──────────────────┘
          │                    │
          └──────────┬─────────┘
                     ▼
          ┌──────────────────────┐       ┌──────────────────────┐
          │  Azure AI Foundry    │       │  Azure Blob Storage  │
          │  GPT-4.1             │──────▶│  jobs/{id}/state.json│
          └──────────────────────┘       │  jobs/{id}/result.md │
                                         └──────────────────────┘
```

### Azure Services

| Service | SKU | Role |
|---------|-----|------|
| Azure Static Web Apps | Free | Hosts the vanilla-JS browser UI |
| Azure Container Apps | Consumption | Runs the FastAPI backend + pipeline |
| Azure Container Registry | Basic | Stores the Docker image |
| Azure AI Speech | S0 | Converts video audio to text |
| Azure AI Vision 4.0 | S1 | Captions and OCR on extracted frames |
| Azure AI Foundry (GPT-4.1) | S0 GlobalStandard | Generates Diátaxis documentation |
| Azure Blob Storage | Standard LRS | Persists job state + generated Markdown |
| Azure Key Vault | Standard | Stores all service secrets |

**Target region:** `francecentral` for all resources · SWA in `westeurope`.

---

## Project layout

```
video2doc-ai/
├── api/                    ← FastAPI backend
│   ├── main.py             #   App entry point, CORS, static-file mount
│   ├── models.py           #   Pydantic models (JobState, JobStatus, JobStep)
│   ├── job_store.py        #   Blob-backed job persistence
│   ├── pipeline_runner.py  #   Background pipeline thread
│   ├── routers/jobs.py     #   REST endpoints
│   └── requirements.txt
│
├── src/                    ← Pipeline modules (shared by API and CLI)
│   ├── timestamps.py       #   Shared MM:SS formatting for the transcript/frame timeline
│   ├── transcribe.py       #   Azure AI Speech REST API (silence-aware chunking, timestamps)
│   ├── extract_frames.py   #   ffmpeg keyframe extraction (all codecs), timestamped
│   ├── analyze_images.py   #   Azure AI Vision captions + OCR
│   ├── generate_docs.py    #   Azure AI Foundry GPT-4.1 + Diátaxis prompt + frame embedding
│   └── blob_storage.py     #   Azure Blob helpers (CLI use)
│
├── ui/                     ← Static Web App (vanilla JS, no framework)
│   ├── index.html          #   SPA shell (French UI)
│   ├── style.css           #   Styles
│   ├── app.js              #   Upload → poll → render Markdown
│   └── staticwebapp.config.json
│
├── infra/                  ← Azure Bicep IaC
│   ├── main.bicep          #   All resources in one template
│   ├── main.bicepparam     #   Parameter defaults
│   └── deploy.sh           #   One-shot CLI deployment
│
├── .github/workflows/
│   ├── deploy-infra.yml    #   Bicep deploy on infra/ changes
│   └── deploy-app.yml      #   Docker build + SWA deploy on code changes
│
├── pipeline.py             ← Standalone CLI (no API needed)
├── Dockerfile              ← API container (python:3.11-slim + ffmpeg)
└── .env.example            ← Environment variable reference
```

---

## Quick start — local development

```bash
git clone https://github.com/kibnelbachyr/video2doc-ai.git
cd video2doc-ai

python -m venv .venv && source .venv/bin/activate
pip install -r api/requirements.txt

# Run in full mock mode (no Azure credentials required)
MOCK_TRANSCRIPTION=true MOCK_VISION=true \
  uvicorn api.main:app --reload --port 8000

# Open http://localhost:8000
```

---

## Detailed documentation

| Page | Content |
|------|---------|
| [Architecture](docs/architecture.md) | Component design, data flow, technology choices |
| [Pipeline](docs/pipeline.md) | Each of the 5 processing steps explained in depth |
| [REST API](docs/api.md) | All endpoints, request/response schemas, error codes |
| [Frontend](docs/frontend.md) | UI components, JavaScript flow, polling mechanism |
| [Infrastructure](docs/infrastructure.md) | Bicep template, Azure resources, Managed Identity |
| [Local Development](docs/local-dev.md) | Setup, mock mode, CLI usage, Docker |
| [Deployment](docs/deployment.md) | Full Azure deployment walkthrough, CI/CD |
| [Configuration](docs/configuration.md) | All environment variables reference |
| [Production Readiness Plan](docs/production-readiness-plan.md) | Gap analysis, phased rollout, go-live checklist for taking the PoV to production |
