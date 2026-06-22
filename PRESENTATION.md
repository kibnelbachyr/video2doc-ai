---
marp: true
theme: default
paginate: true
size: 16:9
---

# video2doc-ai

### From screen recording to structured documentation — automatically

**Proof of Value**

---

## The problem

- Product demos, training sessions, and technical walkthroughs get **recorded constantly** — and then forgotten in a video library
- Turning a video into documentation today means **manual transcription + manual writing**: slow, expensive, inconsistent across authors
- Multilingual teams duplicate the effort per language
- By the time the doc is written, the product has often already changed again

---

## The solution

> Give it **one video file**. Get back **ready-to-publish documentation** — automatically, in the same language as the video.

- Input: a product demo, training, or walkthrough recording
- Output: a complete, structured Markdown document with inline screenshots
- No manual transcription, no manual screenshotting, no translation step

---

## How it works — 5 steps

1. **Upload** — the browser sends the video to the API
2. **Transcribe** — Azure AI Speech converts narration into a timestamped transcript
3. **Extract frames** — key screenshots are sampled from the video
4. **Analyze** — Azure AI Vision captions each frame and reads on-screen text (OCR)
5. **Generate** — Azure AI Foundry (GPT-4.1) writes the documentation, placing the right screenshot next to the right paragraph

All five steps run automatically; the user just uploads and waits.

---

## The key idea: one shared timeline

```
Transcript   [02:15] "...then click Export Wizard..."
Frame        [02:18] frame_000027.png  →  Export dialog on screen
```

Narration and visuals are **aligned by timestamp**, not just concatenated.
The model places each screenshot exactly where the matching narration occurs —
not bundled randomly at the end of a section.

---

## Key capabilities

- **Automatic language detection** — French audio → French docs, English audio → English docs
- **Diátaxis structure** — every output has a Tutorial, How-to Guide, Reference, and Explanation section
- **Audio/visual synchronization** — screenshots placed at the right moment in the narrative
- **Fidelity to source** — exact terminology, button labels, and menu names preserved; nothing invented
- **Self-contained output** — one Markdown file, images embedded inline (no broken links, no external hosting)
- **Resilient pipeline** — automatic retry when an AI service is temporarily throttled

---

## What makes the pipeline "smart"

- **Silence-aware audio chunking** — splits narration at natural pauses, never mid-sentence or mid-word
- **Timestamp-precision alignment** — every transcript line and every frame carries an exact `[MM:SS]` position
- **Tunable visual density** — configurable frame sampling rate, defaults to one frame every 5 seconds for thorough coverage
- **Smart frame selection by the model** — skips near-duplicate or blank/transition frames, distributes illustrations throughout instead of clustering them

---

## Architecture

```
Browser (Static Web App)
   │  upload video / poll status / fetch result
   ▼
FastAPI  (Container App)
   │
   ├── Azure AI Speech    → transcription
   ├── ffmpeg              → frame extraction
   ├── Azure AI Vision    → caption + OCR per frame
   └── Azure AI Foundry   → GPT-4.1 documentation generation
                               │
                               ▼
                      Azure Blob Storage
                      (job state + result)
```

**Stateless API** — all job state lives in Blob Storage, so the backend scales to zero and survives restarts without losing work.

---

## Technical stack

| Layer | Technology |
|---|---|
| Frontend | Vanilla JS SPA — Azure Static Web Apps |
| Backend | FastAPI (Python) — Azure Container Apps |
| Speech-to-text | Azure AI Speech (REST API) |
| Visual analysis | Azure AI Vision 4.0 (caption + OCR) |
| Document generation | Azure AI Foundry — GPT-4.1 |
| Storage | Azure Blob Storage |
| Secrets | Azure Key Vault + Managed Identity |
| Infrastructure as Code | Bicep — single template, one-command deploy |
| CI/CD | GitHub Actions (build, infra, deploy) |

---

## Security & cost model

- **Zero plaintext secrets** — Managed Identity fetches every credential from Key Vault at runtime
- **No admin passwords** — container registry pulls and secret access are both RBAC-based
- **Consumption-based pricing** — the backend scales to zero when idle; you pay per job run, not per hour
- **EU data residency** — all resources default to `francecentral`

---

## Current scope (PoV) → production path

| Today (Proof of Value) | Production upgrade |
|---|---|
| One job at a time per replica | Worker queue, concurrent processing |
| ~10 min practical video length | Azure Batch Transcription API for longer videos |
| Open API, no authentication | Azure AD auth via Static Web Apps |
| Uniform time-based frame sampling | Scene-change / diversity-based key-frame detection |
| Manual AI quota tuning | Provisioned-throughput GPT deployment |

---

## Business value

- Turns **idle video assets** (demos, trainings, recordings) into reusable, structured documentation
- Cuts technical writing time from **hours/days to minutes** per video
- **Consistent structure** across every document, regardless of who recorded the video
- **Multilingual by default** — no separate translation step for French/English content
- **Faithful to the source** — fewer review/correction cycles than generic AI writing tools

---

## Try it

1. Upload a video
2. Watch live progress across the 5-step pipeline in real time
3. Get a publish-ready Markdown document — copy, download, or pull via the API

---

## Next steps

- Pilot with a small batch of real internal training/demo videos
- Validate output quality against the current documentation review process
- Prioritize production hardening items from the upgrade path above based on pilot feedback

---

# Questions?
