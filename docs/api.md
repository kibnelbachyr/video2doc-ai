# REST API Reference

Base URL (local dev): `http://localhost:8000`  
Base URL (production): `https://<container-app-fqdn>.azurecontainerapps.io`

Interactive docs (Swagger UI): `{base_url}/docs`  
Alternative (ReDoc): `{base_url}/redoc`

---

## Endpoints

### `GET /health`

Liveness probe used by Container Apps health checks.

**Response `200 OK`**
```json
{ "status": "ok" }
```

No authentication required. Safe to call frequently.

---

### `POST /api/jobs`

Upload a video file and start the documentation pipeline.

**Request**

Content-Type: `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | binary | Yes | Video file. Allowed extensions: `.mp4`, `.mov`, `.avi`, `.mkv`, `.webm`, `.wmv`. Max 500 MB. |

**Example (curl)**
```bash
curl -X POST https://<api>/api/jobs \
  -F "file=@/path/to/demo.mp4"
```

**Response `202 Accepted`**
```json
{
  "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "pending",
  "message": "Processing started. Poll /api/jobs/{job_id} for progress."
}
```

**Error responses**

| Status | Condition |
|--------|-----------|
| `400` | No filename provided |
| `413` | File exceeds 500 MB |
| `415` | Unsupported file extension |

---

### `GET /api/jobs/{job_id}`

Poll the current status and step of a job.

**Path parameter**

| Parameter | Type | Description |
|-----------|------|-------------|
| `job_id` | UUID string | The ID returned by `POST /api/jobs` |

**Example (curl)**
```bash
curl https://<api>/api/jobs/3fa85f64-5717-4562-b3fc-2c963f66afa6
```

**Response `200 OK`**
```json
{
  "job_id":     "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status":     "processing",
  "step":       "transcribing",
  "step_label": "Transcribing audio",
  "error":      null,
  "created_at": "2025-05-01T10:00:00.000Z",
  "updated_at": "2025-05-01T10:00:15.432Z",
  "result_url": null
}
```

When the job finishes (`status: "done"`), `result_url` is populated:

```json
{
  "job_id":     "3fa85f64-...",
  "status":     "done",
  "step":       "done",
  "step_label": "Done",
  "error":      null,
  "created_at": "2025-05-01T10:00:00.000Z",
  "updated_at": "2025-05-01T10:04:12.100Z",
  "result_url": "/api/jobs/3fa85f64-.../result"
}
```

When a job fails (`status: "failed"`), `error` contains a short description:

```json
{
  "status": "failed",
  "error":  "RuntimeError: ffmpeg audio extraction failed: ...",
  "result_url": null
}
```

**Error responses**

| Status | Condition |
|--------|-----------|
| `404` | Job ID not found |

---

### `GET /api/jobs/{job_id}/result`

Retrieve the generated Markdown document for a completed job.

Returns `text/plain` (raw Markdown string).

**Example (curl)**
```bash
curl https://<api>/api/jobs/3fa85f64-.../result -o documentation.md
```

**Response `200 OK`**

Raw Markdown text. Example excerpt:

```markdown
# ContosoCRM 3.2 — Product Documentation

## Tutorial

This tutorial guides you through the three main features introduced in
ContosoCRM version 3.2: the Dashboard, Smart Filters, and the Export Wizard.

### Step 1: Open the Dashboard
...
```

**Error responses**

| Status | Condition |
|--------|-----------|
| `404` | Job ID not found |
| `409` | Job is still processing (`status != "done"`) |
| `422` | Job failed — error detail included in response |
| `500` | Result blob missing from storage (internal error) |

---

## Job status values

| `status` | Meaning |
|----------|---------|
| `pending` | Job created; video upload to Blob in progress |
| `processing` | Pipeline thread is running; see `step` for current activity |
| `done` | Pipeline complete; result available at `result_url` |
| `failed` | An error occurred; see `error` field for details |

## Job step values

| `step` | `step_label` | Meaning |
|--------|-------------|---------|
| `uploading` | Uploading video | Video bytes being written to Blob Storage |
| `transcribing` | Transcribing audio | ffmpeg WAV extraction + Speech REST API calls |
| `extracting_frames` | Extracting keyframes | ffmpeg PNG extraction |
| `analyzing_images` | Analysing images | Azure AI Vision caption + OCR per frame |
| `generating_docs` | Generating documentation | GPT-4.1 LLM call |
| `done` | Done | Pipeline complete |

---

## Full polling example

```bash
# 1. Start a job
JOB=$(curl -s -X POST https://<api>/api/jobs \
  -F "file=@demo.mp4" | jq -r .job_id)

echo "Job ID: $JOB"

# 2. Poll until done or failed
while true; do
  RESPONSE=$(curl -s "https://<api>/api/jobs/$JOB")
  STATUS=$(echo "$RESPONSE" | jq -r .status)
  STEP=$(echo "$RESPONSE"   | jq -r .step_label)
  echo "$(date '+%H:%M:%S')  $STATUS — $STEP"

  [ "$STATUS" = "done" ]   && break
  [ "$STATUS" = "failed" ] && { echo "Error: $(echo "$RESPONSE" | jq -r .error)"; exit 1; }
  sleep 3
done

# 3. Download result
curl -s "https://<api>/api/jobs/$JOB/result" -o documentation.md
echo "Saved to documentation.md"
```

---

## CORS

The API allows all origins (`*`) in the current PoC configuration. In
production, restrict to the Static Web Apps hostname:

```python
# api/main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://your-swa-hostname.azurestaticapps.net"],
    ...
)
```
