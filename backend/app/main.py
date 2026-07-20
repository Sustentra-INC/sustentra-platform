from fastapi import FastAPI

from .api import (
    assistant,
    documents,
    engagements,
    evidence,
    pipeline,
    processing_runs,
    reviews,
)

app = FastAPI(title="Sustentra Evidence Extraction API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(engagements.router)
app.include_router(documents.router)
app.include_router(processing_runs.router)
app.include_router(pipeline.router)
app.include_router(evidence.router)
app.include_router(reviews.router)
app.include_router(assistant.router)
