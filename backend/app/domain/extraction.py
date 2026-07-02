from pydantic import BaseModel


class ExtractionCandidate(BaseModel):
    """Candidate value emitted by extraction, pending reviewer decision."""

    candidate_id: str
    evidence_id: str
    document_id: str
    field_name: str
    display_label: str
    raw_value: str | float | int | bool | None = None
    normalized_value: str | float | int | bool | None = None
    unit: str | None = None
    confidence: float
    source_reference: dict
    validation_flags: list[str] = []
