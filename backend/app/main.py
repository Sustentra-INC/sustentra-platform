from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import (
    assistant,
    audit,
    auth,
    clients,
    documents,
    engagements,
    evidence,
    methodology,
    pipeline,
    processing_runs,
    reviews,
    users,
)

app = FastAPI(title="Sustentra Evidence Extraction API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(clients.router)
app.include_router(audit.router)
app.include_router(engagements.router)
app.include_router(documents.router)
app.include_router(processing_runs.router)
app.include_router(pipeline.router)
app.include_router(evidence.router)
app.include_router(methodology.router)
app.include_router(reviews.router)
app.include_router(assistant.router)
