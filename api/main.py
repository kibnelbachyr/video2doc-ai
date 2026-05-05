"""
api/main.py
-----------
FastAPI application entry point for video2doc-ai.

Run locally:
  uvicorn api.main:app --reload --port 8000

Endpoints:
  GET  /health             – liveness probe
  POST /api/jobs           – upload video + start pipeline
  GET  /api/jobs/{id}      – poll job status
  GET  /api/jobs/{id}/result – fetch generated Markdown
"""

from dotenv import load_dotenv

# Load .env before any module that reads os.environ at import time
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers.jobs import router as jobs_router

app = FastAPI(
    title="video2doc-ai API",
    description="Generate structured documentation from internal videos using Azure AI.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # tightened to SWA hostname in production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_router, prefix="/api", tags=["jobs"])


@app.get("/health", tags=["ops"])
def health_check():
    """Liveness probe – used by Container Apps health probes."""
    return {"status": "ok"}
