"""A tiny stand-in for the three services the engagement recalculation reads (documents, extraction results
and review decisions), for tests that need the real recalculation and data-quality checks over a few documents.
Every record added is accepted by its reviewer."""

from __future__ import annotations

from typing import Any

from backend.app.services.engagement_recalculation_service import EngagementRecalculationService

ORG = "org-a"


class RecalcStore:
    def __init__(self) -> None:
        self.documents: list[dict] = []
        self.results: dict[str, list[dict]] = {}
        self.reviews: dict[str, list[dict]] = {}

    def add(self, document_id: str, records: list[dict[str, tuple]], canonical_type_id: str = "CT-S2-ELEC", *,
            pages: list[int] | None = None, meters: list[str | None] | None = None) -> None:
        """``records``: one dict per record of field name -> (value, unit). ``pages`` and ``meters`` say where
        each record was read (default: its own page, no meter), as the extractor's source references do."""

        self.documents.append({"document_id": document_id, "engagement_id": "ENG-1", "org_id": ORG,
                               "file_name": f"{document_id}.pdf"})
        items, reviews = [], []
        for index, record in enumerate(records, start=1):
            for name, (value, unit) in record.items():
                candidate_id = f"{document_id}:{index}:{name}"
                items.append({"candidate_id": candidate_id, "field_name": name, "normalized_value": value,
                              "unit": unit, "record_index": index if len(records) > 1 else None,
                              "source_reference": {"document_id": document_id,
                                                   "page_number": pages[index - 1] if pages else index,
                                                   **self._key(index, meters, record)}})
                reviews.append({"candidate_id": candidate_id, "decision": "accepted", "org_id": ORG,
                                "reviewed_value": value, "reviewed_unit": unit})
        self.results[document_id] = [{"document_id": document_id, "org_id": ORG,
                                      "canonical_type_id": canonical_type_id, "items": items}]
        self.reviews[document_id] = reviews

    @staticmethod
    def _key(index: int, meters: list[str | None] | None, record: dict[str, tuple]) -> dict[str, str]:
        meter = meters[index - 1] if meters else None
        period = f"{record.get('service_period_start', (None,))[0]}..{record.get('service_period_end', (None,))[0]}"
        return {"record_key": f"r{index}:{meter}:{period}" if meter else f"r{index}:{period}"}

    # the three service seams the recalculation reads
    def list_documents(self, engagement_id: str) -> list[dict]:
        return [d for d in self.documents if d["engagement_id"] == engagement_id]

    def list_extraction_results_by_document(self, document_id: str) -> list[dict]:
        return self.results.get(document_id, [])

    def list_by_document(self, document_id: str) -> list[dict]:
        return self.reviews.get(document_id, [])


def recalculate(store: RecalcStore, facilities: list[dict[str, Any]] | None = None) -> dict:
    """The recalculation of 2025 for one engagement over the store's documents."""

    engagement = {"id": "ENG-1", "reporting_period_start": "2025-01-01", "reporting_period_end": "2025-12-31",
                  "settings": {"facilities": facilities or []}}
    return EngagementRecalculationService(store, store, store).recalculate(
        engagement, lambda record: record.get("org_id") == ORG)
