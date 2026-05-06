# ─────────────────────────────────────────────────────────────────────────────
#  video2doc-ai  –  API container
#  Build context: project root  (contains both src/ and api/)
#
#  docker build -t video2doc-api .
#  docker run -p 8000:8000 --env-file .env video2doc-api
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim AS base

# ── System dependencies ───────────────────────────────────────────────────────
# ffmpeg      – audio extraction (WAV for Speech SDK) + frame extraction (all codecs incl. AV1)
# libasound2  – ALSA stubs required by Azure AI Speech SDK on headless Linux
# libglib2.0-0 – required by Azure SDK native libs
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg \
      libasound2 \
      libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies ───────────────────────────────────────────────────────
WORKDIR /app
COPY api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# ── Application code ──────────────────────────────────────────────────────────
COPY src/ ./src/
COPY api/ ./api/

# ── Non-root user (security best practice) ───────────────────────────────────
RUN useradd -m -u 1000 appuser && chown -R appuser /app
USER appuser

# ── Runtime ───────────────────────────────────────────────────────────────────
EXPOSE 8000
ENV PYTHONUNBUFFERED=1

# 2 workers: enough for POC; scale replicas instead of workers in Container Apps
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
