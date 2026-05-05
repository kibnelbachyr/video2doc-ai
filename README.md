# video2doc-ai

> Generate structured product documentation from internal videos using Azure AI.

---

## 1. Architecture Overview

```
┌─────────────┐     ┌──────────────────────┐     ┌──────────────────────┐
│  Local MP4  │────▶│  Azure Blob Storage  │     │  Azure AI Speech     │
│  (input)    │     │  (video-input)       │     │  (transcription)     │
└─────────────┘     └──────────────────────┘     └──────────┬───────────┘
                                                             │ transcript
       ┌─────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────┐    ┌──────────────────────┐     ┌──────────────────────┐
│  OpenCV      │───▶│  Azure AI Vision     │────▶│  Azure OpenAI        │
│  (keyframes) │    │  (captions + OCR)    │     │  (GPT-4o / Foundry)  │
└──────────────┘    └──────────────────────┘     └──────────┬───────────┘
                                                             │ Markdown
                                                             ▼
                                                  ┌──────────────────────┐
                                                  │  output/<name>.md    │
                                                  │  (+ Blob upload opt.)│
                                                  └──────────────────────┘
```

### Components

| Component | Azure Service | Purpose |
|-----------|--------------|---------|
| Video storage | Azure Blob Storage | Store input video and output Markdown |
| Speech-to-text | Azure AI Speech SDK | Continuous audio transcription |
| Frame extraction | OpenCV (local) | Sample keyframes from video |
| Image analysis | Azure AI Vision 4.0 | Caption + OCR per frame |
| LLM generation | Azure OpenAI (GPT-4o) | Produce Diátaxis-structured Markdown |

---

## 2. Project Structure

```
video2doc-ai/
├── pipeline.py               # Main orchestration script
├── requirements.txt          # Python dependencies
├── .env.example              # Environment variable template
├── .gitignore
│
├── src/
│   ├── __init__.py
│   ├── blob_storage.py       # Upload/download with Azure Blob Storage
│   ├── transcribe.py         # Azure AI Speech transcription (+ mock mode)
│   ├── extract_frames.py     # OpenCV keyframe extraction
│   ├── analyze_images.py     # Azure AI Vision captions + OCR (+ mock mode)
│   └── generate_docs.py      # Azure OpenAI doc generation + Diátaxis prompt
│
├── prompts/
│   └── diataxis_system_prompt.md  # Prompt design reference
│
└── output/                   # Generated Markdown files (git-ignored)
```

---

## 3. Prerequisites

- Python 3.11+
- An Azure subscription with the following resources provisioned:
  - **Azure Storage Account** (Blob)
  - **Azure AI Speech** resource
  - **Azure AI Vision** resource (Image Analysis 4.0)
  - **Azure OpenAI** resource with a `gpt-4o` deployment
- *(Optional)* GStreamer installed on the host for MP4 audio input to Azure Speech SDK
  ([guide](https://aka.ms/csspeech/gstreamer))

---

## 4. Configuration

### 4.1 Copy and fill the `.env` file

```bash
cp .env.example .env
```

Edit `.env` and set the values for your Azure resources:

| Variable | Description |
|----------|-------------|
| `AZURE_STORAGE_CONNECTION_STRING` | Full connection string from the Storage Account |
| `AZURE_SPEECH_KEY` | Key for the Azure AI Speech resource |
| `AZURE_SPEECH_REGION` | Region, e.g. `eastus` |
| `AZURE_VISION_ENDPOINT` | Endpoint URL for Azure AI Vision |
| `AZURE_VISION_KEY` | Key for Azure AI Vision |
| `AZURE_OPENAI_ENDPOINT` | Endpoint URL for Azure OpenAI |
| `AZURE_OPENAI_KEY` | Key for Azure OpenAI |
| `AZURE_OPENAI_DEPLOYMENT` | Model deployment name (default: `gpt-4o`) |
| `MOCK_TRANSCRIPTION` | Set `true` to skip real Speech calls |
| `MOCK_VISION` | Set `true` to skip real Vision calls |
| `FRAMES_PER_MINUTE` | Keyframe extraction rate (default: `1`) |

### 4.2 Running in fully mock mode (no Azure credentials needed)

```bash
MOCK_TRANSCRIPTION=true MOCK_VISION=true python pipeline.py --video sample.mp4
```

---

## 5. Run Instructions

### Step 1 – Clone and install dependencies

```bash
git clone https://github.com/kibnelbachyr/video2doc-ai.git
cd video2doc-ai
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Step 2 – Configure environment

```bash
cp .env.example .env
# Edit .env with your Azure resource credentials
```

### Step 3 – Run the pipeline

```bash
# Basic run (transcript + frames + doc generation)
python pipeline.py --video /path/to/product_demo.mp4

# Specify custom output path
python pipeline.py --video /path/to/product_demo.mp4 --output output/my_doc.md

# Also upload video and output to Blob Storage
python pipeline.py --video /path/to/product_demo.mp4 --upload

# Mock mode – no Azure credentials required
MOCK_TRANSCRIPTION=true MOCK_VISION=true \
  python pipeline.py --video /path/to/product_demo.mp4
```

### Step 4 – View the output

The generated Markdown file is saved to `output/<video_name>.md`.

---

## 6. Example Output Structure

The LLM generates a Markdown file structured as:

```markdown
# ContosoCRM 3.2 – Dashboard, Smart Filters, and Export Wizard

## Tutorial
Step-by-step walkthrough for new users …

## How-to Guide
### How to configure Smart Filters
1. Click **Smart Filters** in the top-right corner …

## Reference
| UI Element | Location | Description |
|------------|----------|-------------|
| `Smart Filters` | Top-right toolbar | … |

## Explanation
The Dashboard was redesigned in 3.2 to provide …
```

---

## 7. Evolution to Production

| Concern | POC approach | Production upgrade |
|---------|-------------|-------------------|
| Long videos | 10-min Speech SDK cap | Azure Batch Transcription REST API (async) |
| Scene detection | OpenCV uniform sampling | Azure AI Video Indexer (shot/scene boundaries, thumbnails) |
| Document slides | Azure AI Vision captions | Azure AI Document Intelligence (layout + table extraction) |
| Orchestration | Single Python script | Azure Functions or Azure Durable Functions |
| Scale | Local execution | Azure Container Apps + queue-based trigger |
| Observability | print() logging | Azure Application Insights + structured logging |
| Auth | API keys in `.env` | Azure Managed Identity + Key Vault references |
| CI/CD | Manual | GitHub Actions → Azure Container Registry → Azure Functions |

---

## 8. Azure Resources – Quick Provision (Azure CLI)

```bash
RG=rg-video2doc
LOCATION=eastus

az group create -n $RG -l $LOCATION

# Storage
az storage account create -n st$(whoami)v2d -g $RG -l $LOCATION --sku Standard_LRS

# Speech
az cognitiveservices account create -n speech-v2d -g $RG \
  --kind SpeechServices --sku S0 -l $LOCATION

# Vision
az cognitiveservices account create -n vision-v2d -g $RG \
  --kind ComputerVision --sku S1 -l $LOCATION

# Azure OpenAI  (requires subscription allowlisting)
az cognitiveservices account create -n aoai-v2d -g $RG \
  --kind OpenAI --sku S0 -l $LOCATION
```
