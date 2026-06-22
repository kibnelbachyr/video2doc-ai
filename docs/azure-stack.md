# Azure Stack — Services and Roles

This page lists every Azure resource provisioned by `infra/main.bicep`, what
it's used for in the pipeline, its current SKU/configuration, and how it
connects to the rest of the stack. For the end-to-end data flow see
[Architecture](architecture.md); for the deploy procedure see
[Deployment](deployment.md); for the full parameter reference see
[Infrastructure](infrastructure.md).

All resources live in one resource group (default `rg-video2doc-ai`),
provisioned by a single Bicep template, in **France Central** (except Static
Web Apps, see below).

---

## Service inventory

| # | Service | Azure resource type | SKU | Role in the solution |
|---|---|---|---|---|
| 1 | **Azure Static Web Apps** | `Microsoft.Web/staticSites` | Free | Hosts the vanilla-JS browser UI (upload form, progress polling, Markdown render) |
| 2 | **Azure Container Apps** | `Microsoft.App/containerApps` + `managedEnvironments` | Consumption (`cpu: 1.0`, `memory: 2Gi`) | Runs the FastAPI backend: REST API, job orchestration, and the 5-step pipeline in a background thread |
| 3 | **Azure Container Registry** | `Microsoft.ContainerRegistry/registries` | Basic | Stores the Docker image built by CI/CD or `az acr build`; pulled by the Container App via Managed Identity |
| 4 | **Azure AI Speech** | `Microsoft.CognitiveServices/accounts` (kind `SpeechServices`) | S0 | Converts the video's extracted audio (WAV) into a timestamped transcript via the REST recognition API |
| 5 | **Azure AI Vision** | `Microsoft.CognitiveServices/accounts` (kind `ComputerVision`) | S1 | Captions and OCRs every extracted frame (Image Analysis 4.0: `CAPTION` + `READ` features) |
| 6 | **Azure AI Foundry (GPT-4.1)** | `Microsoft.CognitiveServices/accounts` (kind `AIServices`) + project + deployment | S0, `GlobalStandard` deployment | Turns the transcript + visual context into structured Diátaxis Markdown documentation |
| 7 | **Azure Blob Storage** | `Microsoft.Storage/storageAccounts` | Standard `Standard_LRS`, hot tier | Persists job state (`jobs/{id}/state.json`), the uploaded video, and the generated `result.md` — makes the API stateless |
| 8 | **Azure Key Vault** | `Microsoft.KeyVault/vaults` | Standard, RBAC-authorized | Stores all four service credentials as secrets, fetched by the Container App at startup via Managed Identity |
| 9 | **User-Assigned Managed Identity** | `Microsoft.ManagedIdentity/userAssignedIdentities` | — | Single identity attached to the Container App; used for both Key Vault secret reads and ACR image pulls — no passwords anywhere |

`ffmpeg` (audio extraction, frame extraction, silence detection) runs as a
local subprocess inside the Container App — it is not a separate Azure
service.

---

## 1. Azure Static Web Apps — frontend hosting

- **What it serves**: `ui/index.html`, `style.css`, `app.js` — a vanilla-JS
  SPA with no framework/build step.
- **Region**: `westeurope` (`swaLocation` param) — closest available SWA
  region to `francecentral`, since SWA has limited region availability.
- **How it talks to the backend**: calls the Container App's public HTTPS
  endpoint directly, using a `window.API_BASE_URL` injected at deploy time
  via a gitignored `config.js` file (no SWA "linked backend" — that feature
  installs an auth sidecar that rejects unauthenticated requests, which
  would break this PoV's open API).
- **Cost**: Free SKU — sufficient for serving static files only.

---

## 2. Azure Container Apps — backend compute

- **Runs**: the FastAPI app (`api/main.py`) packaged in the Docker image
  built from the repo's `Dockerfile` (`python:3.11-slim` + `ffmpeg`).
- **Identity**: the user-assigned Managed Identity (#9) is attached
  directly to the Container App (`identity.type: UserAssigned`).
- **Ingress**: external, port `8000`, CORS currently `allowedOrigins: ['*']`
  (open — see [Production Readiness Plan](production-readiness-plan.md)).
- **Scaling**: `minReplicas: 0`, `maxReplicas: 3`, HTTP scale rule at 10
  concurrent requests per replica. Scale-to-zero means zero compute cost
  when idle, at the cost of a 10–30 s cold start on the first request.
- **Secrets**: four Key Vault references resolved at boot
  (`speech-key`, `vision-key`, `openai-key`, `storage-conn`), exposed to the
  container as environment variables (`AZURE_SPEECH_KEY`, etc.) — never
  written to the image or in plaintext.
- **Other env vars set by the template**: `AZURE_SPEECH_REGION`,
  `SPEECH_LANGUAGE`, `AZURE_VISION_ENDPOINT`, `AZURE_OPENAI_ENDPOINT`,
  `AZURE_OPENAI_DEPLOYMENT=gpt-4.1`, `AZURE_OPENAI_API_VERSION`,
  `FRAMES_PER_MINUTE=12`.
- **First deploy caveat**: the template deploys a placeholder image
  (`mcr.microsoft.com/azuredocs/containerapps-helloworld`) because the ACR
  is empty on first run; the real image lands after the first
  `az acr build` + `az containerapp update` (or CI/CD run).

---

## 3. Azure Container Registry — image storage

- **SKU**: Basic — sufficient for a single image with infrequent pushes.
- **Auth**: `adminUserEnabled: false` — no admin password. The Container
  App pulls images using the Managed Identity's **AcrPull** role
  (`7f951dda-4ed3-4680-a7ca-43fe172d538d`), assigned at the registry scope.

---

## 4. Azure AI Speech — transcription

- **Kind**: `SpeechServices`, **SKU**: S0.
- **Called via**: the REST recognition endpoint
  (`/speech/recognition/conversation/cognitiveservices/v1`), not the Speech
  SDK — the SDK needs an audio platform (ALSA) unavailable in headless
  containers.
- **Input**: ffmpeg-extracted 16 kHz mono WAV, split into ≤55 s chunks at
  the nearest detected silence (`ffmpeg silencedetect`) so no sentence is
  cut mid-word.
- **Output**: per-chunk `NBest[0].Offset` gives each transcript segment a
  precise absolute timestamp — this is what lets the LLM later align
  narration with the matching on-screen frame.
- **Language**: `SPEECH_LANGUAGE` env var (Bicep param `speechLanguage`,
  default `en-US`) — must match the spoken language of the source video.

---

## 5. Azure AI Vision — image analysis

- **Kind**: `ComputerVision`, **SKU**: S1.
- **Called via**: the Image Analysis 4.0 SDK, with two `VisualFeatures` per
  frame: `CAPTION` (one-sentence description) and `READ` (OCR, line by
  line).
- **Input**: PNG frames extracted by ffmpeg at a configurable rate
  (`FRAMES_PER_MINUTE`, default 12 → one frame every 5 s).
- **Output**: each frame's caption + OCR text is formatted into a
  timestamped block injected into the documentation-generation prompt.

---

## 6. Azure AI Foundry (GPT-4.1) — documentation generation

- **Resource kind**: `AIServices` — Microsoft's unified 2025 model-deployment
  resource (replacing the standalone `OpenAI` kind), with
  `allowProjectManagement: true` enabling the ai.azure.com project
  experience. A `video2doc` project is created under the account.
- **Model deployment**: `gpt-4.1`, SKU `GlobalStandard`, capacity
  `openAICapacity` param — currently **400** (thousand TPM), raised from the
  original default of 50 after a real `429 RateLimitError` incident in PoV
  testing (see [Pipeline → retry on rate limiting](pipeline.md#retry-on-rate-limiting)).
- **Called via**: the standard `openai` Python package (`AzureOpenAI`
  client) pointed at the account's `*.cognitiveservices.azure.com` endpoint
  — identical code path to Azure OpenAI Service.
- **Auth**: key-based today (`disableLocalAuth: false`); RBAC/Managed-Identity
  auth is a production hardening item.
- **Data residency note**: `GlobalStandard` may route requests outside
  `francecentral`; `DataZoneStandard` is the SKU to switch to if strict EU
  residency is contractually required.
- **Temperature/limits**: `temperature=0.2`, `max_tokens=8192` — low
  temperature keeps output grounded in the transcript/visual context rather
  than invented.

---

## 7. Azure Blob Storage — job state and artifacts

- **SKU**: `Standard_LRS` (locally redundant — no built-in DR).
- **Containers**: `video-input`, `doc-output` (unused by the current
  job-centric flow, reserved for future use), and `jobs` — the one actually
  used, holding per-job subfolders:
  ```
  jobs/{job_id}/state.json   ← JobState (status, step, error, timestamps)
  jobs/{job_id}/{video_file} ← the uploaded video
  jobs/{job_id}/result.md    ← generated Markdown (after embedding frame images)
  ```
- **Why Blob instead of a database**: keeps infra minimal — no managed DB,
  no connection pool, no migrations. The API reads/writes `state.json` on
  every step transition, which is what lets the FastAPI process be fully
  stateless (scales to zero, survives restarts without losing job data).
- **Public access**: disabled on the account and on every container
  (`publicAccess: 'None'`); all access is via the storage connection string
  secret, itself stored in Key Vault.

---

## 8. Azure Key Vault — secrets

- **SKU**: Standard, `enableRbacAuthorization: true` (no legacy access
  policies), soft-delete enabled (7-day retention).
- **Secrets stored**: `speech-key`, `vision-key`, `openai-key`,
  `storage-connection-string` — one per downstream service, all populated
  at deploy time directly from each resource's `listKeys()` output.
- **Access**: only the Managed Identity (#9) can read secrets, via the
  **Key Vault Secrets User** role (`4633458b-17de-408a-b874-0445c86b69e6`)
  assigned at the vault scope. The Container App resolves these as
  `keyVaultUrl` secret references in its `configuration.secrets` block —
  Azure fetches them at container boot, they're never persisted to the
  image or written to a `.env` file in production.

---

## 9. User-Assigned Managed Identity — the credential glue

One identity, two role assignments, zero passwords:

| Target | Role | Purpose |
|---|---|---|
| Container Registry | `AcrPull` | Pull the API Docker image |
| Key Vault | `Key Vault Secrets User` | Read the four service-key secrets at boot |

This is the only identity in the whole stack; it's attached directly to the
Container App (`identity.type: UserAssigned`), and both the AI Foundry
account and AI Foundry project additionally carry their own
`SystemAssigned` identities (used internally by the AIServices resource
type, not consumed by the application code).

---

## How the pieces connect (request-time)

```
Browser (Static Web App)
   │ POST /api/jobs
   ▼
Container App (FastAPI)  ──Managed Identity──▶  Key Vault (secrets)
   │                      ──Managed Identity──▶  Container Registry (image pull)
   │
   ├─ 1. Azure AI Speech     (transcription)
   ├─ 2. ffmpeg              (frame extraction — local subprocess)
   ├─ 3. Azure AI Vision     (caption + OCR)
   └─ 4. Azure AI Foundry    (GPT-4.1 documentation generation)
            │
            ▼
   Container App writes result ──▶ Azure Blob Storage (jobs/{id}/*)
   │
   ▼
Browser polls GET /api/jobs/{id} and GET /api/jobs/{id}/result
```

The AI services never talk to Blob Storage directly — the Container App is
the sole orchestrator, calling each service in turn and persisting state
itself. This is what keeps the API stateless: any replica can pick up a
poll request because all durable state lives in Blob, not in process memory.

---

## What's intentionally out of scope today

Per [Production Readiness Plan](production-readiness-plan.md): no
authentication in front of the API, CORS open to all origins, AI Foundry
key-based auth (not RBAC), no Blob lifecycle/retention policy, and a single
environment/resource group with no dev/staging/prod separation. These are
deliberate PoV simplifications, not oversights — see that page for the
phased plan to close each gap.
