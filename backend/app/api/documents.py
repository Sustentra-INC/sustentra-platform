from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/v1", tags=["documents"])


class CreateDocumentRequest(BaseModel):
    file_name: str
    mime_type: str
    storage_uri: str
    document_role: str
    document_type: str
    uploaded_by: str


@router.post("/engagements/{engagement_id}/documents")
def create_document(engagement_id: str, payload: CreateDocumentRequest) -> dict[str, str]:
    return {
        "document_id": "doc_demo_001",
        "engagement_id": engagement_id,
        "file_name": payload.file_name,
        "mime_type": payload.mime_type,
        "storage_uri": payload.storage_uri,
        "document_role": payload.document_role,
        "document_type": payload.document_type,
        "uploaded_by": payload.uploaded_by,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "processing_status": "queued"
    }


@router.get("/engagements/{engagement_id}/documents")
def list_documents(engagement_id: str) -> dict[str, list[dict[str, str]]]:
    return {
        "engagement_id": engagement_id,
        "items": [
            {
                "document_id": "doc_demo_001",
                "file_name": "sample.pdf",
                "processing_status": "queued"
            }
        ]
    }


@router.get("/documents/{document_id}")
def get_document(document_id: str) -> dict[str, str]:
    return {
        "document_id": document_id,
        "engagement_id": "eng_demo_001",
        "file_name": "sample.pdf",
        "processing_status": "queued"
    }
