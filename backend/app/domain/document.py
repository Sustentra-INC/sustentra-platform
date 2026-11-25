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
    # Owning organization (SEC-001). None = recorded before org scoping; only a
    # provider_admin can see such records until they are claimed (cli claim-s1-data).
    org_id: str | None = None
    # The batch it was uploaded in (migration 0019), when it was uploaded as one of several files.
    batch_id: str | None = None
    # A random id the browser makes once per file and sends on every attempt to upload it, so a retry
    # after a dropped connection finds this document instead of storing a second copy. None = an
    # older client (or a document made some other way).
    client_upload_id: str | None = None
