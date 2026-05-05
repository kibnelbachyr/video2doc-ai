# video2doc-ai

> Generate structured product documentation from internal videos using Azure AI.

---

## 1. Architecture Overview

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
          │  Azure OpenAI GPT-4o │──────▶│  Azure Blob Storage  │
          │  (doc generation)    │       │  video-input         │
          └──────────────────────┘       │  doc-output          │
                                         │  jobs/{id}/state.json│
                                         └──────────────────────┘
```

### Azure Services Used

| Service | Tier | Purpose |
|---------|------|---------|
| Azure Static Web Apps | Free | SPA frontend (HTML/CSS/JS) |
| Azure Container Apps | Consumption | FastAPI REST API + pipeline |
| Azure Container Registry | Basic | Docker image storage |
| Azure AI Speech | S0 | Audio transcription |
| Azure AI Vision 4.0 | S1 | Frame captions + OCR |
| Azure OpenAI (GPT-4o) | S0 | Diátaxis doc generation |
| Azure Blob Storage | Standard LRS | Video, job state, Markdown output |
| Azure Key Vault | Standard | Service credentials |
| Azure Application Insights | Pay-as-you-go | Observability |
| Azure Log Analytics | Pay-as-you-go | Container logs |

---

## 2. Project Structure

```
video2doc-ai/
│
├── infra/                          ← Azure Bicep IaC
│   ├── main.bicep                  #   All resources in one template
│   ├── main.bicepparam             #   Parameter defaults
│   └── deploy.sh                  #   One-shot CLI deployment script
│
├── api/                            ← FastAPI backend
│   ├── main.py                     #   App entry point + CORS
│   ├── models.py                   #   Pydantic job state models
│   ├── job_store.py                #   Blob-backed job persistence
│   ├── pipeline_runner.py          #   Background pipeline execution
│   ├── routers/
│   │   └── jobs.py                 #   REST endpoints
│   └── requirements.txt
│
├── src/                            ← Pipeline modules (CLI + API shared)
│   ├── blob_storage.py             #   Azure Blob helpers
│   ├── transcribe.py               #   Azure AI Speech (+ mock)
│   ├── extract_frames.py           #   OpenCV keyframe extraction
│   ├── analyze_images.py           #   Azure AI Vision (+ mock)
│   └── generate_docs.py            #   Azure OpenAI + Diátaxis prompt
│
├── ui/                             ← Static Web App (vanilla JS)
│   ├── index.html                  #   SPA shell
│   ├── style.css                   #   Styles (no framework)
│   ├── app.js                      #   Upload → poll → render Markdown
│   └── staticwebapp.config.json   #   SWA routing config
│
├── .github/
│   └── workflows/
│       ├── deploy-infra.yml        #   Deploys Bicep on infra/ changes
│       └── deploy-app.yml          #   Builds API image + deploys UI
│
├── Dockerfile                      ← API container (project root context)
├── .dockerignore
├── pipeline.py                     ← Standalone CLI (unchanged)
├── requirements.txt                ← CLI-only dependencies
└── .env.example                    ← Environment variable reference
```

---

## 3. Local Development

### 3.1 Prerequisites

- Python 3.11+
- Docker Desktop (optional, for container testing)
- Azure CLI ≥ 2.50 (for deployment)
- An Azure subscription

### 3.2 Install and run API locally

```bash
git clone https://github.com/kibnelbachyr/video2doc-ai.git
cd video2doc-ai

python -m venv .venv && source .venv/bin/activate
pip install -r api/requirements.txt

cp .env.example .env
# Fill in your Azure credentials in .env

# Run API (mock mode – no Azure credentials needed)
MOCK_TRANSCRIPTION=true MOCK_VISION=true \
  uvicorn api.main:app --reload --port 8000
```

### 3.3 Open the UI locally

```bash
# Serve the ui/ folder on a local web server
python -m http.server 3000 --directory ui
# Open http://localhost:3000
# (API is on :8000, CORS allows all origins in dev)
```

Swagger docs are at `http://localhost:8000/docs`.

### 3.4 Run the CLI (no API needed)

```bash
# Full run
python pipeline.py --video demo.mp4

# Mock mode
MOCK_TRANSCRIPTION=true MOCK_VISION=true \
  python pipeline.py --video demo.mp4
```

### 3.5 Run API in Docker locally

```bash
docker build -t video2doc-api .
docker run -p 8000:8000 --env-file .env video2doc-api
```

---

## 4. Azure Deployment

### 4.1 One-time setup – Service Principal for CI/CD

```bash
# Create a service principal with Contributor on the subscription
az ad sp create-for-rbac \
  --name sp-video2doc-ai \
  --role Contributor \
  --scopes /subscriptions/<your-subscription-id> \
  --sdk-auth

# Add federated credential for OIDC (GitHub Actions)
az ad app federated-credential create \
  --id <app-object-id> \
  --parameters '{
    "name": "github-main",
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": "repo:kibnelbachyr/video2doc-ai:ref:refs/heads/main",
    "audiences": ["api://AzureADTokenExchange"]
  }'
```

Add the following to **GitHub → Settings → Secrets and variables**:

| Secret / Variable | Value |
|-------------------|-------|
| Secret: `AZURE_CLIENT_ID` | Service principal app (client) ID |
| Secret: `AZURE_TENANT_ID` | Azure AD tenant ID |
| Secret: `AZURE_SUBSCRIPTION_ID` | Azure subscription ID |
| Secret: `AZURE_STATIC_WEB_APPS_API_TOKEN` | SWA deployment token (step 4.3) |
| Variable: `AZURE_RESOURCE_GROUP` | `rg-video2doc-ai` |
| Variable: `AZURE_LOCATION` | `eastus` |
| Variable: `NAME_PREFIX` | `v2doc` |

### 4.2 Deploy infrastructure

**Option A – GitHub Actions** (recommended)

Push any change to `infra/` on the `main` branch, or trigger the
`Deploy Infrastructure` workflow manually from the Actions tab.

**Option B – Local CLI**

```bash
export RESOURCE_GROUP=rg-video2doc-ai
export LOCATION=eastus
./infra/deploy.sh
```

The script prints all resource names and next steps.

### 4.3 Get the SWA deployment token

```bash
SWA_NAME=$(az staticwebapp list \
  -g rg-video2doc-ai --query '[0].name' -o tsv)

az staticwebapp secrets list \
  --name "$SWA_NAME" \
  --query 'properties.apiKey' \
  --output tsv
```

Copy this value into the `AZURE_STATIC_WEB_APPS_API_TOKEN` GitHub secret.

### 4.4 Deploy the application

Push any change to `api/`, `src/`, `ui/`, or `Dockerfile` on `main`.

The `Deploy Application` workflow will:
1. Build the Docker image with `az acr build` (cloud-side build, no local Docker needed).
2. Update the Container App to the new image.
3. Inject the Container App URL into `ui/index.html`.
4. Deploy the UI to Azure Static Web Apps.

### 4.5 Verify the deployment

```bash
# Health check
curl https://<container-app-fqdn>/health

# Swagger UI
open https://<container-app-fqdn>/docs

# Frontend
open https://<swa-hostname>.azurestaticapps.net
```

---

## 5. API Reference

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/health` | Liveness probe |
| `POST` | `/api/jobs` | Upload video + start pipeline (multipart) |
| `GET`  | `/api/jobs/{job_id}` | Poll job status and current step |
| `GET`  | `/api/jobs/{job_id}/result` | Fetch generated Markdown (plain text) |

### Job status flow

```
pending → processing (transcribing → extracting_frames → analyzing_images → generating_docs) → done
                                                                                              → failed
```

### Example

```bash
# 1. Start a job
JOB=$(curl -s -X POST https://<api>/api/jobs \
  -F "file=@demo.mp4" | jq -r .job_id)

# 2. Poll until done
while true; do
  STATUS=$(curl -s https://<api>/api/jobs/$JOB | jq -r .status)
  echo "Status: $STATUS"
  [ "$STATUS" = "done" ] && break
  [ "$STATUS" = "failed" ] && break
  sleep 3
done

# 3. Download result
curl https://<api>/api/jobs/$JOB/result -o output.md
```

---

## 6. Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `AZURE_STORAGE_CONNECTION_STRING` | Yes | Blob Storage connection string |
| `AZURE_SPEECH_KEY` | Yes* | Azure AI Speech resource key |
| `AZURE_SPEECH_REGION` | Yes* | Speech resource region (e.g. `eastus`) |
| `AZURE_VISION_ENDPOINT` | Yes* | Vision resource endpoint URL |
| `AZURE_VISION_KEY` | Yes* | Vision resource key |
| `AZURE_OPENAI_ENDPOINT` | Yes | Azure OpenAI endpoint URL |
| `AZURE_OPENAI_KEY` | Yes | Azure OpenAI resource key |
| `AZURE_OPENAI_DEPLOYMENT` | No | Model deployment name (default: `gpt-4o`) |
| `AZURE_OPENAI_API_VERSION` | No | API version (default: `2024-02-01`) |
| `MOCK_TRANSCRIPTION` | No | `true` to skip Speech calls in dev |
| `MOCK_VISION` | No | `true` to skip Vision calls in dev |
| `FRAMES_PER_MINUTE` | No | Keyframe rate (default: `1`) |

\* Not required when `MOCK_TRANSCRIPTION=true` / `MOCK_VISION=true`.

In production, all secrets are stored in **Azure Key Vault** and injected into the Container App via Managed Identity — no `.env` file needed.

---

## 7. Roadmap to Production

| Concern | Current (POC) | Production upgrade |
|---------|--------------|-------------------|
| Long videos | 10-min SDK cap | Azure Batch Transcription REST API |
| Scene detection | OpenCV uniform sampling | Azure AI Video Indexer |
| Document slides | Vision captions | Azure AI Document Intelligence |
| Job queue | Background thread | Azure Queue Storage + worker |
| Orchestration | FastAPI background thread | Azure Durable Functions |
| Auth | None | Azure Static Web Apps built-in auth (AAD/B2C) |
| CORS | Allow-all | Restrict to SWA hostname |
| Secrets rotation | Manual | Key Vault with auto-rotation |
| Observability | App Insights basic | Custom dashboards + alerts |
| Multi-language | English only | Speech SDK language detection |
