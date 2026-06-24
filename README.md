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

## Components

| Component | Description |
|---|---|
| **Backend API** (`api/`) | FastAPI service exposing job creation/status/result endpoints, runs the pipeline in a background thread |
| **Processing pipeline** (`src/`) | Transcription, frame extraction, image analysis, and documentation generation — shared by the API and the CLI |
| **Frontend UI** (`ui/`) | Single-page app (vanilla HTML/CSS/JS, no build step) for upload, progress tracking, and result preview |
| **CLI** (`pipeline.py`) | Standalone command-line entry point to run the same pipeline without the API or a browser |
| **Infrastructure as Code** (`infra/`) | Azure Bicep template provisioning the full environment in one deployment |

---

## Architecture

```
                    ┌──────────────────────────┐
                    │  Azure Static Web Apps   │
                    │  (Vanilla JS SPA)        │
                    └────────────┬─────────────┘
                                 │ POST /api/jobs
                                 │ GET  /api/jobs/{id}
                                 │ GET  /api/jobs/{id}/result
                                 ▼
                    ┌──────────────────────────┐
                    │  Azure Container Apps    │◄── Managed Identity
                    │  FastAPI  (api/)         │
                    └────────────┬─────────────┘         │
                                 │                   ┌────┴──────────────────────┐
                    pipeline (sequential)             ▼                           ▼
                                 │          ┌──────────────────┐  ┌──────────────────────┐
                                 ▼          │  Azure Container │  │  Azure Key Vault     │
          ┌──────────────────────────┐      │  Registry        │  │  (secrets)           │
          │  ① Azure AI Speech      │      │  (AcrPull)       │  │  (KV Secrets User)   │
          │     (transcription)     │      └──────────────────┘  └──────────────────────┘
          └──────────────┬───────────┘
                         │
                         ▼
          ┌──────────────────────────┐
          │  ② ffmpeg                │
          │     (frame extraction)  │
          └──────────────┬───────────┘
                         │
                         ▼
          ┌──────────────────────────┐
          │  ③ Azure AI Vision      │
          │     (caption + OCR)     │
          └──────────────┬───────────┘
                         │
                         ▼
          ┌──────────────────────────┐       ┌──────────────────────────┐
          │  ④ Azure AI Foundry     │       │  Azure Blob Storage      │
          │     GPT-4.1             │──────▶│  jobs/{id}/state.json    │
          └──────────────────────────┘       │  jobs/{id}/{video_file}  │
                                             │  jobs/{id}/result.md     │
                                             └──────────────────────────┘
```

> `state.json` is updated by the Container App after every pipeline step, not only on completion.
> ffmpeg runs as a local subprocess inside the container — it is not an external Azure service.

### Azure services

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

Credentials are never stored in the container image or in plain-text environment
variables. A User-Assigned Managed Identity reads all secrets from Key Vault at
startup and pulls the Docker image from the Container Registry — no passwords involved.

---

## Steps to deploy

Prerequisites: Azure CLI ≥ 2.50, logged in (`az login`) with a subscription selected.

```bash
# 1. Provision all Azure resources (~5 minutes)
./infra/deploy.sh
# Note the API URL, Container App name, ACR login server, and SWA name it prints.

# 2. Build the API image in the cloud and push it to ACR
az acr build \
  --registry <acr-login-server> \
  --image video2doc-api:latest \
  --file Dockerfile .

# 3. Point the Container App at the new image
az containerapp update \
  --name <container-app-name> \
  --resource-group rg-video2doc-ai \
  --image <acr-login-server>/video2doc-api:latest

# 4. Deploy the UI to Static Web Apps
echo "window.API_BASE_URL = 'https://<api-url>';" > ui/config.js
SWA_TOKEN=$(az staticwebapp secrets list --name <swa-name> \
  --resource-group rg-video2doc-ai --query 'properties.apiKey' -o tsv)
npx @azure/static-web-apps-cli deploy ui --deployment-token "$SWA_TOKEN"

# 5. Verify
curl https://<api-url>/health   # expect {"status":"ok"}
```

See [docs/deployment.md](docs/deployment.md) for the full walkthrough, including
re-deployment after code changes and troubleshooting.

---

## More documentation

| Page | Content |
|------|---------|
| [Architecture](docs/architecture.md) | Component design, data flow, technology choices |
| [Pipeline](docs/pipeline.md) | Each of the 5 processing steps explained in depth |
| [REST API](docs/api.md) | All endpoints, request/response schemas, error codes |
| [Frontend](docs/frontend.md) | UI components, JavaScript flow, polling mechanism |
| [Infrastructure](docs/infrastructure.md) | Bicep template, Azure resources, Managed Identity |
| [Local Development](docs/local-dev.md) | Setup, mock mode, CLI usage, Docker |
| [Deployment](docs/deployment.md) | Full Azure deployment walkthrough |
| [Configuration](docs/configuration.md) | All environment variables reference |
