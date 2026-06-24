# Local Development

This page covers everything needed to run video2doc-ai on your local machine
without deploying to Azure.

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.11+ | [python.org](https://python.org) / `pyenv` |
| ffmpeg | any recent | `brew install ffmpeg` / `apt install ffmpeg` |
| Docker Desktop | any | [docker.com](https://docker.com) (optional, for container testing) |

ffmpeg must be on your `PATH`. Verify with:
```bash
ffmpeg -version
```

---

## Setup

```bash
git clone https://github.com/kibnelbachyr/video2doc-ai.git
cd video2doc-ai

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r api/requirements.txt
```

Copy the environment file template:
```bash
cp .env.example .env
```

---

## Mock mode (no Azure credentials needed)

Setting `MOCK_TRANSCRIPTION=true` and `MOCK_VISION=true` replaces all Azure
AI calls with pre-canned sample data. The pipeline runs end-to-end, reaching
the LLM step with synthetic inputs. This requires `AZURE_OPENAI_*` credentials
unless you also mock the LLM (not currently supported — GPT-4.1 always runs).

To run the full pipeline with **zero Azure credentials** during UI development,
you need mock data for the LLM output too. The simplest approach is to use
real Azure AI Foundry credentials only and mock everything else:

```bash
# .env (minimum for full mock transcription + vision, real LLM)
MOCK_TRANSCRIPTION=true
MOCK_VISION=true
AZURE_OPENAI_ENDPOINT=https://<your_aif_resource>.cognitiveservices.azure.com/
AZURE_OPENAI_KEY=<your_foundry_key>
AZURE_OPENAI_DEPLOYMENT=gpt-4.1
AZURE_OPENAI_API_VERSION=2025-04-01-preview

# Storage is needed to persist job state
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=...
```

### What mock mode does

| Variable | `false` (default) | `true` |
|----------|------------------|--------|
| `MOCK_TRANSCRIPTION` | Calls Azure AI Speech REST API | Returns hard-coded 400-word CRM product transcript |
| `MOCK_VISION` | Calls Azure AI Vision for each frame; extracts frames with ffmpeg | Skips frame extraction; returns 3 hard-coded frame results (dashboard, filters, export) |

When **both** are `true`, job state is stored in a process-level Python dict
instead of Blob Storage — `AZURE_STORAGE_CONNECTION_STRING` is not required.

---

## Running the API

```bash
# With real Azure credentials
uvicorn api.main:app --reload --port 8000

# With mock transcription + vision (Azure Foundry still needed for LLM)
MOCK_TRANSCRIPTION=true MOCK_VISION=true \
  uvicorn api.main:app --reload --port 8000
```

Access points:

| URL | Content |
|-----|---------|
| `http://localhost:8000` | The UI (served by FastAPI StaticFiles) |
| `http://localhost:8000/docs` | Swagger UI (interactive API docs) |
| `http://localhost:8000/redoc` | ReDoc (alternative API docs) |
| `http://localhost:8000/health` | Liveness probe |

The `--reload` flag auto-reloads the server when Python files change.

> **Note:** `config.js` is not generated locally. The UI falls back to
> same-origin API calls (`API_BASE = ''`), so everything works automatically.

---

## Running the CLI

`pipeline.py` runs the same five-step pipeline without any API or web server.
Useful for testing a single video end-to-end from the command line.

```bash
# Full run with all Azure services
python pipeline.py --video path/to/demo.mp4

# Save output to a specific path
python pipeline.py --video demo.mp4 --output docs/output.md

# Use a custom frames directory
python pipeline.py --video demo.mp4 --frames /tmp/frames

# Upload video input and result to Blob Storage (requires AZURE_STORAGE_CONNECTION_STRING)
python pipeline.py --video demo.mp4 --upload

# Mock mode (no Speech or Vision calls)
MOCK_TRANSCRIPTION=true MOCK_VISION=true python pipeline.py --video demo.mp4
```

The CLI writes the generated Markdown to `output/<video_stem>.md` by default
and removes the extracted frames directory when done.

---

## Running in Docker

Build and run the container locally to reproduce the production environment:

```bash
# Build the image
docker build -t video2doc-api .

# Run with your .env file
docker run -p 8000:8000 --env-file .env video2doc-api

# Run in mock mode (no Azure credentials)
docker run -p 8000:8000 \
  -e MOCK_TRANSCRIPTION=true \
  -e MOCK_VISION=true \
  -e AZURE_OPENAI_ENDPOINT=https://... \
  -e AZURE_OPENAI_KEY=... \
  -e AZURE_OPENAI_DEPLOYMENT=gpt-4.1 \
  -e AZURE_OPENAI_API_VERSION=2025-04-01-preview \
  -e AZURE_STORAGE_CONNECTION_STRING=... \
  video2doc-api
```

The container runs as a non-root user (`appuser`, UID 1000) and starts
uvicorn with 2 workers on port 8000.

---

## Project dependencies

### API (`api/requirements.txt`)

| Package | Version | Purpose |
|---------|---------|---------|
| `fastapi` | 0.111.0 | Web framework |
| `uvicorn[standard]` | 0.30.1 | ASGI server |
| `python-multipart` | 0.0.9 | Multipart file upload parsing |
| `aiofiles` | 23.2.1 | Required by FastAPI `StaticFiles` |
| `azure-storage-blob` | 12.19.1 | Blob Storage SDK |
| `azure-ai-vision-imageanalysis` | 1.0.0 | Vision 4.0 Image Analysis SDK |
| `openai` | ≥1.50.0 | Azure AI Foundry / GPT-4.1 client |
| `python-dotenv` | 1.0.1 | `.env` file loading |
| `requests` | 2.31.0 | Speech REST API HTTP calls |

> `openai>=1.50.0` is required. Earlier versions (e.g. 1.30.x) fail with
> `TypeError: Client.__init__() got an unexpected keyword argument 'proxies'`
> when used with `httpx>=0.28`.

### CLI only (`requirements.txt`)

| Package | Version | Purpose |
|---------|---------|---------|
| `azure-storage-blob` | 12.19.1 | Blob Storage SDK (`--upload` flag) |
| `azure-ai-vision-imageanalysis` | 1.0.0 | Vision 4.0 Image Analysis SDK |
| `openai` | ≥1.50.0 | Azure AI Foundry / GPT-4.1 client |
| `python-dotenv` | 1.0.1 | `.env` file loading |
| `requests` | 2.31.0 | Speech REST API HTTP calls |

The CLI skips the web-framework packages (`fastapi`, `uvicorn`,
`python-multipart`, `aiofiles`) since `pipeline.py` runs no server. Both
requirements files pin the same `openai>=1.50.0` floor (see note above) and
share all `src/` modules.

---

## Common issues

### `ffmpeg: command not found`

Install ffmpeg and ensure it is on your PATH:
```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt-get install -y ffmpeg

# Verify
ffmpeg -version
```

### `KeyError: 'AZURE_STORAGE_CONNECTION_STRING'`

The API is running without mock mode and no `.env` has been loaded. Either:
- Create a `.env` file from `.env.example` and fill in your credentials, or
- Run with `MOCK_TRANSCRIPTION=true MOCK_VISION=true` (both must be true for
  in-memory job storage to kick in).

### `TypeError: Client.__init__() got an unexpected keyword argument 'proxies'`

Your installed `openai` package is too old. Upgrade:
```bash
pip install "openai>=1.50.0"
```

### Port 8000 already in use

Find and kill the existing process:
```bash
lsof -ti :8000 | xargs kill -9
```
