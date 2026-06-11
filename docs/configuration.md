# Configuration Reference

All configuration is done through environment variables. In local development
they are loaded from a `.env` file. In production they are injected by Azure
Container Apps from Key Vault secrets via the Managed Identity.

---

## Environment variables

### Azure Blob Storage

| Variable | Required | Example | Description |
|----------|----------|---------|-------------|
| `AZURE_STORAGE_CONNECTION_STRING` | Yes* | `DefaultEndpointsProtocol=https;AccountName=...` | Full connection string for the Storage Account. Used for job state, video blobs, and result blobs. |

\* Not required when `MOCK_TRANSCRIPTION=true AND MOCK_VISION=true` (both together
trigger in-memory storage mode, bypassing Blob Storage entirely).

---

### Azure AI Speech

| Variable | Required | Example | Description |
|----------|----------|---------|-------------|
| `AZURE_SPEECH_KEY` | Yes* | `abc123...` | Primary key of the Azure AI Speech resource. |
| `AZURE_SPEECH_REGION` | Yes* | `francecentral` | Region of the Speech resource. Used to construct the REST endpoint URL: `https://{region}.stt.speech.microsoft.com/...` |

\* Not required when `MOCK_TRANSCRIPTION=true`.

---

### Azure AI Vision

| Variable | Required | Example | Description |
|----------|----------|---------|-------------|
| `AZURE_VISION_ENDPOINT` | Yes* | `https://vision-v2doc-abc123.cognitiveservices.azure.com/` | Endpoint URL of the Azure AI Vision resource. |
| `AZURE_VISION_KEY` | Yes* | `abc123...` | Primary key of the Vision resource. |

\* Not required when `MOCK_VISION=true`.

---

### Azure AI Foundry (GPT-4.1)

| Variable | Required | Default | Example | Description |
|----------|----------|---------|---------|-------------|
| `AZURE_OPENAI_ENDPOINT` | Yes | — | `https://aif-v2doc-abc123.cognitiveservices.azure.com/` | Endpoint of the AIServices account. Note: ends with `.cognitiveservices.azure.com/`, not `.openai.azure.com/`. |
| `AZURE_OPENAI_KEY` | Yes | — | `abc123...` | Primary key of the AIServices account. |
| `AZURE_OPENAI_DEPLOYMENT` | No | `gpt-4.1` | `gpt-4.1` | Name of the model deployment inside Azure AI Foundry. Must match the deployment name in `main.bicep`. |
| `AZURE_OPENAI_API_VERSION` | No | `2025-04-01-preview` | `2025-04-01-preview` | Azure OpenAI API version. Required for the GPT-4.1 model. |

---

### Pipeline behaviour

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MOCK_TRANSCRIPTION` | No | `false` | Set to `true` to skip all Azure AI Speech calls and return a hard-coded transcript. Useful during development. |
| `MOCK_VISION` | No | `false` | Set to `true` to skip ffmpeg frame extraction and Azure AI Vision calls, returning hard-coded frame analysis results. |
| `SCENE_THRESHOLD` | No | `0.2` | Sensitivity of ffmpeg's scene-change detection (`select='gt(scene,X)'`) used to pick key frames, in addition to the first frame which is always kept. Lower values select more frames (more sensitive to small changes); higher values select fewer, more distinct frames. |
| `MAX_FRAMES` | No | `12` | Maximum number of key frames kept per video, evenly spread across the detected set. Bounds Vision API cost and the size of the generated document. |
| `FRAMES_PER_MINUTE` | No | `1` | Last-resort uniform sampling rate (frames/minute), used only on the rare occasion the first frame + scene-change detection yields nothing at all (e.g. an unreadable video stream). The sampling interval is clamped to the video's duration so short videos still yield a frame. |
| `FRAME_EMBED_MAX_WIDTH` | No | `640` | Max width (pixels) for key frames embedded inline in the generated Markdown. Frames are downscaled to this width (never upscaled) before base64 encoding; Vision analysis still runs on the full-resolution originals. |

---

## Mock mode combinations

| `MOCK_TRANSCRIPTION` | `MOCK_VISION` | Behaviour |
|---------------------|--------------|-----------|
| `false` | `false` | Full real pipeline — all Azure services called |
| `true` | `false` | Mock transcript; real frame extraction + Vision |
| `false` | `true` | Real Speech transcription; mock frames + Vision |
| `true` | `true` | **Full mock** — no Azure AI calls, in-memory job storage (no Storage Account needed) |

In full mock mode (`true`+`true`), the only Azure credentials needed are
`AZURE_OPENAI_*` (the LLM is always called with real data).

---

## Production environment (Container App)

In production, secrets are stored in Key Vault and injected automatically
by Container Apps. The Bicep template maps them:

```bicep
env: [
  { name: 'AZURE_SPEECH_KEY',              secretRef: 'speech-key'   }
  { name: 'AZURE_SPEECH_REGION',           value: location            }
  { name: 'AZURE_VISION_ENDPOINT',         value: visionService.properties.endpoint }
  { name: 'AZURE_VISION_KEY',              secretRef: 'vision-key'   }
  { name: 'AZURE_OPENAI_ENDPOINT',         value: aiFoundry.properties.endpoint }
  { name: 'AZURE_OPENAI_KEY',              secretRef: 'openai-key'   }
  { name: 'AZURE_OPENAI_DEPLOYMENT',       value: 'gpt-4.1'          }
  { name: 'AZURE_OPENAI_API_VERSION',      value: '2025-04-01-preview' }
  { name: 'AZURE_STORAGE_CONNECTION_STRING', secretRef: 'storage-conn' }
  { name: 'FRAMES_PER_MINUTE',             value: '2'                }
  { name: 'MOCK_TRANSCRIPTION',            value: 'false'            }
  { name: 'MOCK_VISION',                   value: 'false'            }
]
```

`secretRef` values are resolved at runtime by the Container Apps platform
from the Key Vault references defined in the `configuration.secrets` block.
No credentials ever appear in plain text in the Bicep template or the
Container App configuration UI.

---

## `.env` file (local development)

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

`.env` is listed in `.gitignore` and must never be committed. All variables
in `.env.example` correspond directly to the table above.

Example minimal `.env` for local development with mock AI + real LLM:

```dotenv
MOCK_TRANSCRIPTION=true
MOCK_VISION=true

AZURE_OPENAI_ENDPOINT=https://aif-v2doc-abc123.cognitiveservices.azure.com/
AZURE_OPENAI_KEY=<your_foundry_key>
AZURE_OPENAI_DEPLOYMENT=gpt-4.1
AZURE_OPENAI_API_VERSION=2025-04-01-preview
```

When both mocks are `true`, `AZURE_STORAGE_CONNECTION_STRING` is not required
because job state is stored in memory.
