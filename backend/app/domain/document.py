from pydantic import BaseModel


class Document(BaseModel):
    """Document metadata contract used by the pilot APIs."""

    document_id: str
    engagement_id: str
    evidence_id: str | None = None
    file_name: str
    mime_type: str
    storage_uri: str
    document_role: str
    document_type: str | None = None
    uploaded_by: str
    uploaded_at: str
    processing_status: str
