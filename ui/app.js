/**
 * app.js
 * ------
 * Frontend logic for video2doc-ai.
 *
 * Flow:
 *  1. User drops / selects a video file.
 *  2. POST /api/jobs  →  receive job_id.
 *  3. Poll GET /api/jobs/{job_id} every POLL_INTERVAL ms.
 *  4. On each poll, update the step progress UI.
 *  5. When status == "done", fetch /api/jobs/{job_id}/result
 *     and render as Markdown with marked.js.
 *  6. User can download the raw .md file or copy to clipboard.
 *
 * All API calls use relative paths (/api/...).
 * In production, the SWA linked-backend proxies /api/* to the Container App.
 * In local dev, uvicorn serves both the UI and the API on the same origin.
 */

const API_BASE = '';        // always relative — SWA linked backend handles routing
const POLL_INTERVAL = 2000; // ms

// ── DOM refs ──────────────────────────────────────────────────────────────────
const uploadZone     = document.getElementById('upload-zone');
const fileInput      = document.getElementById('file-input');
const selectedFile   = document.getElementById('selected-file');
const fileName       = document.getElementById('file-name');
const fileSize       = document.getElementById('file-size');
const startBtn       = document.getElementById('start-btn');
const progressCard   = document.getElementById('progress-card');
const stepItems      = document.querySelectorAll('.step[data-step]');
const errorMsg       = document.getElementById('error-msg');
const resultCard     = document.getElementById('result-card');
const markdownPreview = document.getElementById('markdown-preview');
const downloadBtn    = document.getElementById('download-btn');
const copyBtn        = document.getElementById('copy-btn');
const newJobBtn      = document.getElementById('new-job-btn');

// ── State ─────────────────────────────────────────────────────────────────────
let selectedVideoFile = null;
let pollTimer         = null;
let rawMarkdown       = '';

// Step order for progress tracking
const STEP_ORDER = [
  'uploading',
  'transcribing',
  'extracting_frames',
  'analyzing_images',
  'generating_docs',
  'done',
];

// ── Drag-and-drop ─────────────────────────────────────────────────────────────
uploadZone.addEventListener('dragover', (e) => {
  e.preventDefault();
  uploadZone.classList.add('drag-over');
});
uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('drag-over'));
uploadZone.addEventListener('drop', (e) => {
  e.preventDefault();
  uploadZone.classList.remove('drag-over');
  const file = e.dataTransfer.files[0];
  if (file) setFile(file);
});
uploadZone.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) setFile(fileInput.files[0]);
});

function setFile(file) {
  selectedVideoFile = file;
  fileName.textContent = file.name;
  fileSize.textContent = formatBytes(file.size);
  selectedFile.style.display = 'flex';
  startBtn.disabled = false;
}

// ── Start pipeline ────────────────────────────────────────────────────────────
startBtn.addEventListener('click', async () => {
  if (!selectedVideoFile) return;

  startBtn.disabled = true;
  errorMsg.style.display = 'none';
  progressCard.style.display = 'block';
  resultCard.style.display   = 'none';
  resetSteps();

  setStepState('uploading', 'active');

  const formData = new FormData();
  formData.append('file', selectedVideoFile);

  let jobId;
  try {
    const res = await fetch(`${API_BASE}/api/jobs`, {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Upload failed (HTTP ${res.status})`);
    }
    const data = await res.json();
    jobId = data.job_id;
  } catch (err) {
    showError(`Upload error: ${err.message}`);
    startBtn.disabled = false;
    return;
  }

  // Start polling
  pollTimer = setInterval(() => pollJob(jobId), POLL_INTERVAL);
});

// ── Poll job status ───────────────────────────────────────────────────────────
async function pollJob(jobId) {
  let data;
  try {
    const res = await fetch(`${API_BASE}/api/jobs/${jobId}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch (err) {
    // Network hiccup – keep polling
    console.warn('[poll] fetch error:', err.message);
    return;
  }

  updateSteps(data.step);

  if (data.status === 'done') {
    clearInterval(pollTimer);
    setStepState('done', 'done');
    await loadResult(jobId);
  } else if (data.status === 'failed') {
    clearInterval(pollTimer);
    markCurrentStepError();
    showError(data.error || 'Pipeline failed. Check logs for details.');
    startBtn.disabled = false;
  }
}

// ── Update step indicators ────────────────────────────────────────────────────
function resetSteps() {
  stepItems.forEach((el) => {
    el.classList.remove('active', 'done', 'error');
    el.classList.add('pending');
    const timeEl = el.querySelector('.step-time');
    if (timeEl) timeEl.textContent = '';
  });
}

function updateSteps(currentStep) {
  if (!currentStep) return;
  const currentIdx = STEP_ORDER.indexOf(currentStep);

  stepItems.forEach((el) => {
    const stepName = el.dataset.step;
    const idx = STEP_ORDER.indexOf(stepName);
    el.classList.remove('pending', 'active', 'done', 'error');

    if (idx < currentIdx)  el.classList.add('done');
    else if (idx === currentIdx) el.classList.add('active');
    else el.classList.add('pending');
  });
}

function setStepState(stepName, state) {
  const el = document.querySelector(`.step[data-step="${stepName}"]`);
  if (!el) return;
  el.classList.remove('pending', 'active', 'done', 'error');
  el.classList.add(state);
}

function markCurrentStepError() {
  const active = document.querySelector('.step.active');
  if (active) {
    active.classList.remove('active');
    active.classList.add('error');
  }
}

// ── Load and display result ───────────────────────────────────────────────────
async function loadResult(jobId) {
  try {
    const res = await fetch(`${API_BASE}/api/jobs/${jobId}/result`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    rawMarkdown = await res.text();
  } catch (err) {
    showError(`Could not load result: ${err.message}`);
    return;
  }

  // Render markdown
  markdownPreview.innerHTML = marked.parse(rawMarkdown);

  // Set download filename
  const baseName = (selectedVideoFile?.name || 'documentation').replace(/\.[^.]+$/, '');
  downloadBtn.dataset.filename = `${baseName}.md`;

  resultCard.style.display = 'block';
  resultCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ── Download ──────────────────────────────────────────────────────────────────
downloadBtn.addEventListener('click', () => {
  const blob = new Blob([rawMarkdown], { type: 'text/markdown' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = downloadBtn.dataset.filename || 'documentation.md';
  a.click();
  URL.revokeObjectURL(url);
});

// ── Copy to clipboard ─────────────────────────────────────────────────────────
copyBtn.addEventListener('click', async () => {
  await navigator.clipboard.writeText(rawMarkdown);
  const original = copyBtn.textContent;
  copyBtn.textContent = 'Copied!';
  setTimeout(() => (copyBtn.textContent = original), 1500);
});

// ── New job ───────────────────────────────────────────────────────────────────
newJobBtn.addEventListener('click', () => {
  selectedVideoFile = null;
  rawMarkdown       = '';
  fileInput.value   = '';
  selectedFile.style.display  = 'none';
  progressCard.style.display  = 'none';
  resultCard.style.display    = 'none';
  errorMsg.style.display      = 'none';
  startBtn.disabled = true;
  resetSteps();
  window.scrollTo({ top: 0, behavior: 'smooth' });
});

// ── Helpers ───────────────────────────────────────────────────────────────────
function showError(msg) {
  errorMsg.textContent = `⚠ ${msg}`;
  errorMsg.style.display = 'block';
}

function formatBytes(bytes) {
  if (bytes < 1024)        return `${bytes} B`;
  if (bytes < 1024 ** 2)   return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3)   return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}
