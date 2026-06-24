# Frontend

The user interface is a **single-page application** (SPA) built with vanilla
HTML, CSS, and JavaScript — no framework, no build step, no Node.js dependency.
It is served by **Azure Static Web Apps** in production and by the FastAPI
`StaticFiles` mount at `http://localhost:8000` during local development.

---

## Files

| File | Purpose |
|------|---------|
| `ui/index.html` | HTML shell with all markup; French language |
| `ui/style.css` | All styles (design tokens, layout, components) |
| `ui/app.js` | All interaction logic (upload, polling, render) |
| `ui/staticwebapp.config.json` | SWA routing (all routes → `index.html`) |
| `ui/config.js` | **Gitignored** — generated at deploy time with `window.API_BASE_URL` |

---

## Page structure

```
┌───────────────────────────────────────────────────────┐
│  top-bar          SoftwareOne logo │ 4CAD Group logo  │
├───────────────────────────────────────────────────────┤
│  header           📹 video2doc-ai   [tagline]         │
├───────────────────────────────────────────────────────┤
│                                                       │
│  #upload-card     ⬆ Importer une vidéo               │
│                   [drag-and-drop zone]                │
│                   [Générer la documentation] button   │
│                                                       │
│  #progress-card   ⚙ Traitement en cours              │
│                   ○ Envoi de la vidéo                │
│                   ⟳ Transcription audio (active)     │
│                   ○ Extraction des images clés        │
│                   ○ Analyse des images                │
│                   ○ Génération de la documentation   │
│                   ○ Terminé                          │
│                                                       │
│  #result-card     📄 Documentation générée           │
│                   [Copier] [Télécharger .md]          │
│                   [Markdown rendered inline]          │
│                                                       │
├───────────────────────────────────────────────────────┤
│  footer           Propulsé par Azure AI Speech · …   │
└───────────────────────────────────────────────────────┘
```

The three cards (`#upload-card`, `#progress-card`, `#result-card`) are shown
and hidden by JavaScript as the workflow progresses.

---

## JavaScript flow (`ui/app.js`)

### 1. File selection

The drag-and-drop zone and the hidden `<input type="file">` both call
`setFile(file)`, which stores the `File` object in `selectedVideoFile`,
displays the filename and size, and enables the submit button.

```
user drops/selects file
  → setFile(file)
  → selectedVideoFile = file
  → startBtn.disabled = false
```

### 2. Upload and job creation

On button click:

```
startBtn click
  → show #progress-card
  → setStepState('uploading', 'active')
  → POST /api/jobs  (FormData with video file)
  → receive { job_id }
  → start polling timer  (setInterval, 2000 ms)
```

If the upload fails (network error or HTTP error), the error message is
shown in `#error-msg` and the button is re-enabled.

### 3. Polling

Every 2 seconds `pollJob(jobId)` calls `GET /api/jobs/{job_id}`.

The response `step` field is compared against `STEP_ORDER`:

```javascript
const STEP_ORDER = [
  'uploading', 'transcribing', 'extracting_frames',
  'analyzing_images', 'generating_docs', 'done',
];
```

Steps before the current one get class `done` (✓ green).  
The current step gets class `active` (⟳ spinning, blue background).  
Steps after get class `pending` (○ grey).

```
GET /api/jobs/{id}  →  { status, step }
  if step == 'transcribing' (index 1):
    index 0 (uploading) → done
    index 1 (transcribing) → active
    index 2–5 → pending
```

### 4. Completion

When `status == "done"`:

```
clearInterval(pollTimer)
setStepState('done', 'done')
GET /api/jobs/{id}/result  →  raw Markdown text
markdownPreview.innerHTML = marked.parse(rawMarkdown)
resultCard.style.display = 'block'
resultCard.scrollIntoView(...)
```

When `status == "failed"`:

```
clearInterval(pollTimer)
markCurrentStepError()   ← changes active step to ✕ red
showError(data.error)    ← shows #error-msg
startBtn.disabled = false
```

### 5. Download and copy

**Download:** Creates a `Blob` from `rawMarkdown`, constructs an `<a>` with
`download` attribute, triggers a click, then revokes the object URL.

**Copy:** Uses `navigator.clipboard.writeText(rawMarkdown)`. The button
briefly shows "Copied!" for 1.5 seconds as visual feedback.

### 6. New job

The "Nouvelle vidéo" button resets all state: clears `selectedVideoFile`,
hides `#progress-card` and `#result-card`, resets all step indicators to
`pending`, and scrolls back to top.

---

## API base URL strategy

The frontend needs to know where the API is. In local development, both
the UI and the API run on the same origin (`http://localhost:8000`), so
relative paths (`/api/jobs`) work without any configuration.

In production, the UI is hosted on a different domain (Static Web Apps)
from the API (Container Apps). The solution uses a **gitignored `config.js`**
file generated at deploy time:

```javascript
// ui/config.js  (generated, never committed)
window.API_BASE_URL = 'https://ca-v2doc-abc123-api.francecentral.azurecontainerapps.io';
```

`index.html` loads it with an `onerror` fallback:

```html
<script src="config.js" onerror="window.API_BASE_URL=''"></script>
```

`app.js` reads it:

```javascript
const API_BASE = (window.API_BASE_URL || '').replace(/\/$/, '');
```

If `config.js` is absent (local dev), `API_BASE` is `''` and all paths are
relative — the browser sends requests to the same origin where `uvicorn` serves
both the UI and the API.

---

## Markdown rendering

The result is rendered using **marked.js** (loaded from a CDN):

```html
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
```

```javascript
markdownPreview.innerHTML = marked.parse(rawMarkdown);
```

The `#markdown-preview` div has custom CSS for headings, tables, code blocks,
and blockquotes styled to match the Azure design language (blues, greys).

---

## Logos (top bar)

Both logos are **inline SVG** directly in `index.html`, requiring no image files
or external requests:

- **SoftwareOne** — dark circle with "software / one" wordmark
- **4CAD Group** — orange bold "4", dark "CAD", grey "Group" text

The top bar sits above the Azure-blue header bar and uses a white background
with a bottom border to visually separate it from the page.

---

## Design system

All colours and spacing are CSS custom properties defined in `:root`:

| Token | Value | Used for |
|-------|-------|---------|
| `--azure-blue` | `#0078d4` | Header, buttons, links |
| `--azure-dark` | `#005a9e` | Button hover, H1 in preview |
| `--azure-light` | `#eff6fc` | Active step background, upload hover |
| `--success` | `#107c10` | Done step checkmark |
| `--error` | `#d13438` | Failed step, error message |
| `--neutral-60` | `#8a8886` | Captions, secondary text |
| `--neutral-90` | `#323130` | Body text |
