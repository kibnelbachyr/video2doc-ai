# Deployment Guide

This guide covers deploying video2doc-ai to Azure from scratch using the CLI,
and optionally automating subsequent deploys with GitHub Actions.

---

## Prerequisites

```bash
# Azure CLI ≥ 2.50
az version

# Log in
az login

# Set your subscription
az account set --subscription <your-subscription-id>

# Verify
az account show
```

---

## Step 1 — Deploy infrastructure

The `infra/deploy.sh` script creates the resource group and deploys every
Azure resource in one shot (~5 minutes).

```bash
# Optional: override defaults
export RESOURCE_GROUP=rg-video2doc-ai
export LOCATION=francecentral
export NAME_PREFIX=v2doc

./infra/deploy.sh
```

The script prints a summary when done. **Copy these output values** — you
need them in the steps below:

| Output | Example |
|--------|---------|
| `API URL` | `https://ca-v2doc-abc123-api.francecentral.azurecontainerapps.io` |
| `UI URL` | `https://swa-v2doc-abc123-ui.azurestaticapps.net` |
| `ACR` | `acrv2docabc123.azurecr.io` |
| `Container App` | `ca-v2doc-abc123-api` |
| `Key Vault` | `kv-v2doc-abc123` |
| `Storage` | `stv2docabc123` |
| `AI Foundry` | `https://aif-v2doc-abc123.cognitiveservices.azure.com/` |

---

## Step 2 — Build and push the API image

No local Docker daemon is required — ACR builds the image in the cloud.

```bash
ACR=acrv2docabc123.azurecr.io   # from deploy.sh output (full login server)

az acr build \
  --registry "$ACR" \
  --image video2doc-api:latest \
  --file Dockerfile \
  .
```

This uploads the build context (project root) to ACR and builds the image
using the cloud build agent. The `Dockerfile` copies `src/` and `api/`,
installs Python dependencies, and installs `ffmpeg`.

> Build takes ~3–5 minutes on first run (downloading base image and packages).
> Subsequent builds are faster due to layer caching.

---

## Step 3 — Update the Container App to use the new image

```bash
CONTAINER_APP=ca-v2doc-abc123-api
RESOURCE_GROUP=rg-video2doc-ai

az containerapp update \
  --name "$CONTAINER_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --image "$ACR/video2doc-api:latest"
```

The Container App pulls the new image using the Managed Identity's `AcrPull`
role — no password required. The update triggers a rolling restart.

---

## Step 4 — Deploy the UI

The UI is a folder of static files. Deployment requires a one-time
`config.js` file containing the API URL (never committed to git).

```bash
RESOURCE_GROUP=rg-video2doc-ai
API_URL=https://ca-v2doc-abc123-api.francecentral.azurecontainerapps.io

# 1. Generate config.js (gitignored)
echo "window.API_BASE_URL = '${API_URL}';" > ui/config.js

# 2. Get SWA name and deployment token
SWA_NAME=$(az staticwebapp list \
  --resource-group "$RESOURCE_GROUP" \
  --query '[0].name' --output tsv)

SWA_TOKEN=$(az staticwebapp secrets list \
  --name "$SWA_NAME" \
  --query 'properties.apiKey' --output tsv)

# 3. Deploy (config.js is included as part of ui/)
npx @azure/static-web-apps-cli deploy ui \
  --deployment-token "$SWA_TOKEN"
```

`config.js` is listed in `.gitignore`. It is safe to regenerate and overwrite
on every deployment.

---

## Step 5 — Verify

```bash
API_URL=https://ca-v2doc-abc123-api.francecentral.azurecontainerapps.io

# API health check
curl "$API_URL/health"
# Expected: {"status":"ok"}

# Open the UI
open https://swa-v2doc-abc123-ui.azurestaticapps.net
```

> The first request after idle takes 10–30 s due to Container App scale-to-zero
> cold start. Subsequent requests are fast.

---

## Re-deploying after code changes

| What changed | Commands to run |
|---|---|
| `api/`, `src/`, `Dockerfile` | Steps 2 + 3 (rebuild image, update Container App) |
| `ui/` only | Step 4 (re-deploy SWA) |
| `infra/` | Re-run `./infra/deploy.sh` (idempotent) |

---

## Viewing Container App logs

```bash
CONTAINER_APP=ca-v2doc-abc123-api
RESOURCE_GROUP=rg-video2doc-ai

# Follow live log stream
az containerapp logs show \
  --name "$CONTAINER_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --follow

# Filter to a specific step prefix
az containerapp logs show \
  --name "$CONTAINER_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --follow | grep '\[speech\]'
```

Log prefixes: `[pipeline]`, `[speech]`, `[frames]`, `[vision]`, `[llm]`.

---

## CI/CD with GitHub Actions (optional)

Two workflows are included in `.github/workflows/`:

| Workflow | Trigger | Action |
|----------|---------|--------|
| `deploy-infra.yml` | Push to `main` with changes in `infra/` | Runs `az deployment group create` |
| `deploy-app.yml` | Push to `main` with changes in `api/`, `src/`, `ui/`, or `Dockerfile` | Builds ACR image, updates Container App, deploys SWA |

### Setup

Create a service principal:

```bash
az ad sp create-for-rbac \
  --name sp-video2doc-ai \
  --role Contributor \
  --scopes /subscriptions/<your-subscription-id> \
  --json-auth
```

Add the following to **GitHub → Settings → Secrets and variables**:

| Type | Name | Value |
|------|------|-------|
| Secret | `AZURE_CLIENT_ID` | Service principal app (client) ID |
| Secret | `AZURE_TENANT_ID` | Azure AD tenant ID |
| Secret | `AZURE_SUBSCRIPTION_ID` | Azure subscription ID |
| Secret | `AZURE_STATIC_WEB_APPS_API_TOKEN` | SWA deployment token (from step 4) |
| Variable | `AZURE_RESOURCE_GROUP` | `rg-video2doc-ai` |
| Variable | `AZURE_LOCATION` | `francecentral` |
| Variable | `NAME_PREFIX` | `v2doc` |

Once set, pushing to `main` triggers the appropriate workflow automatically.

---

## Troubleshooting

### Container App shows placeholder (helloworld) page

The Bicep template deploys a placeholder image on first run. Run steps 2 + 3
to build and deploy the real image.

### `az acr build` fails with UNAUTHORIZED

The ACR name must be the **full login server** (e.g. `acrv2docabc123.azurecr.io`),
not just the registry name (`acrv2docabc123`). Use the `acrLoginServer` output
from `deploy.sh`.

### `az containerapp update` fails with UNAUTHORIZED

Same issue — use the full ACR login server in the `--image` flag:
```bash
--image acrv2docabc123.azurecr.io/video2doc-api:latest
```

### UI shows `net::ERR_CONNECTION_REFUSED` or CORS error

The `config.js` file was not generated before deploying the UI, or was
generated with an incorrect API URL. Regenerate and redeploy the UI (step 4).

### Documentation generation fails with `RateLimitError: 429`

The GPT-4.1 deployment's tokens-per-minute quota (`openAICapacity` in
`infra/main.bicep`, default `400`K) has been exceeded — usually because
`FRAMES_PER_MINUTE` produces a large visual context, or several jobs ran
concurrently. The pipeline already retries automatically (15/30/45/60 s
backoff, 5 attempts) before failing the job, so an isolated `429` should
self-heal. If it fails repeatedly, raise the deployment's capacity without a
redeploy:

```bash
RG=rg-video2doc-ai
AIF=$(az cognitiveservices account list --resource-group "$RG" --query "[?kind=='AIServices'].name" -o tsv)

az cognitiveservices account deployment update \
  --name "$AIF" \
  --resource-group "$RG" \
  --deployment-name gpt-4.1 \
  --sku-capacity 400
```

Check regional headroom first with `az cognitiveservices usage list
--location francecentral`, and update `openAICapacity` in
`infra/main.bicepparam` to match so a future infra redeploy doesn't reset it.
See [Infrastructure](infrastructure.md#adjusting-capacity-without-a-redeploy)
for details.

### Job stays in `pending` forever

The Container App may be running the placeholder image instead of the real one.
Check by calling `/health` — if it returns the helloworld HTML instead of JSON,
you need to deploy the real image (steps 2 + 3).

Also check for errors in the log stream:
```bash
az containerapp logs show --name "$CONTAINER_APP" --resource-group "$RESOURCE_GROUP"
```
