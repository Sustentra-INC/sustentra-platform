from pydantic import BaseModel


class SourceReference(BaseModel):
    """Traceability anchor for extracted evidence values."""

    source_reference_id: str
    document_id: str
    page_number: int | None = None
    sheet_name: str | None = None
    cell_or_range: str | None = None
    text_snippet: str | None = None
    bounding_box: dict[str, float] | None = None  # normalized 0-1 {x, y, width, height}
    parser_block_ids: list[str] = []
    record_key: str | None = None  # multi-record documents (EXT-001)
