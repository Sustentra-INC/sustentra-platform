import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .bootstrap import configure_runtime_from_env
from .api import (
    assistant,
    documents,
    engagements,
    evidence,
    extraction_results,
    pipeline,
    processing_runs,
    reviews,
)

app = FastAPI(title="Sustentra Evidence Extraction API", version="0.1.0")
runtime_settings = configure_runtime_from_env()

_default_origins = "http://localhost:3000,http://127.0.0.1:3000"
_cors_origins = [
    origin.strip()
    for origin in os.getenv("SUSTENTRA_CORS_ORIGINS", _default_origins).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(engagements.router)
app.include_router(documents.router)
app.include_router(processing_runs.router)
app.include_router(pipeline.router)
app.include_router(extraction_results.router)
app.include_router(evidence.router)
app.include_router(reviews.router)
app.include_router(assistant.router)
