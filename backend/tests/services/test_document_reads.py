"""MVP-160: the Evidence tree and the recalculation read a fixed number of times, not once per document."""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.services.document_reads import DocumentReads
from backend.app.services.engagement_recalculation_service import EngagementRecalculationService
from backend.app.services.evidence_tree_service import EvidenceTreeService
from backend.tests.services.test_calculation_lines import KC, STL, _gas
from backend.tests.services.test_engagement_recalculation_service import FakeStore


class CountingStore(FakeStore):
    """The three seams with the bulk reads the Postgres stores have, counting every call."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def list_documents(self, engagement_id: str) -> list[dict]:
        self.calls.append("documents")
        return super().list_documents(engagement_id)

    def list_extraction_results_by_documents(self, document_ids: list[str]) -> dict[str, list[dict]]:
        self.calls.append("results")
        return {i: list(self.results.get(i, [])) for i in document_ids}

    def list_by_documents(self, document_ids: list[str]) -> dict[str, list[dict]]:
        self.calls.append("reviews")
        return {i: list(self.reviews.get(i, [])) for i in document_ids}

    def list_extraction_results_by_document(self, document_id: str) -> list[dict]:
        self.calls.append("result")
        return super().list_extraction_results_by_document(document_id)

    def list_by_document(self, document_id: str) -> list[dict]:
        self.calls.append("review")
        return super().list_by_document(document_id)


def _store(documents: int) -> CountingStore:
    store = CountingStore()
    for i in range(documents):
        store.add_document(f"G{i}", "CT-S1-FUELQTY", [_gas(100 + i, plant=("Kansas City Plant", "St Louis Plant")[i % 2])])
    return store


def _own(record: dict) -> bool:
    return True


ENGAGEMENT = {"id": "ENG-1", "org_id": "org-a", "name": "FY", "reporting_period_start": "2025-01-01",
              "reporting_period_end": "2025-12-31", "settings": {"facilities": [KC, STL]}}


@pytest.mark.parametrize("build", [
    lambda s: EvidenceTreeService(s, s, s).tree(ENGAGEMENT, _own, {}),
    lambda s: EngagementRecalculationService(s, s, s).recalculate(ENGAGEMENT, _own, {}),
    lambda s: EngagementRecalculationService(s, s, s).evidence_register("ENG-1", _own),
], ids=["tree", "recalculation", "evidence register"])
def test_the_number_of_reads_is_the_same_for_50_and_500_documents(build: Any) -> None:
    counts = {}
    for documents in (50, 500):
        store = _store(documents)
        build(store)
        counts[documents] = sorted(store.calls)
    assert counts[50] == counts[500]
    assert "result" not in counts[500] and "review" not in counts[500]  # never one document at a time
    assert len(counts[500]) <= 6


def test_a_store_without_bulk_reads_is_read_one_document_at_a_time_as_before() -> None:
    store = FakeStore()  # no bulk methods
    for i in range(3):
        store.add_document(f"G{i}", "CT-S1-FUELQTY", [_gas()])
    tree = EvidenceTreeService(store, store, store).tree(ENGAGEMENT, _own, {})
    assert tree["blocks"]["supporting"]["scopes"]


def test_each_document_gets_only_its_own_results_and_decisions() -> None:
    store = _store(3)
    reads = DocumentReads(store, store, store, "ENG-1", _own)
    seen = {r.document["document_id"]: (r.results, r.reviews) for r in reads}
    assert set(seen) == {"G0", "G1", "G2"}
    for document_id, (results, reviews) in seen.items():
        assert {x["document_id"] for x in results} == {document_id}
        assert reviews and {x["document_id"] for x in reviews} == {document_id}
    assert sorted(store.calls) == ["documents", "results", "reviews"]


def test_what_a_reader_may_not_see_is_never_handed_out() -> None:
    store = _store(2)
    store.add_document("OTHER", "CT-S1-FUELQTY", [_gas()], org_id="org-b")
    reads = DocumentReads(store, store, store, "ENG-1", lambda record: record.get("org_id") == "org-a")
    assert [r.document["document_id"] for r in reads] == ["G0", "G1"]


def test_the_collector_is_paused_only_while_records_are_built_and_comes_back() -> None:
    import gc

    from backend.app.services.document_reads import gc_paused

    assert gc.isenabled()
    with gc_paused():
        assert not gc.isenabled()
        with gc_paused():  # another request at the same time
            assert not gc.isenabled()
        assert not gc.isenabled()  # still one left
    assert gc.isenabled()
    with pytest.raises(RuntimeError):
        with gc_paused():
            raise RuntimeError("a failing request")
    assert gc.isenabled()  # and it is back on after an error


def test_the_grouped_read_refuses_an_unknown_column_and_reads_nothing_for_no_ids() -> None:
    from backend.app.repositories.s1_postgres import S1Table

    table = S1Table("s1_review_decisions")
    assert table.select_grouped("document_id", []) == {}
    with pytest.raises(ValueError):
        table.select_grouped("record; DROP TABLE s1_documents", ["x"])


def test_no_documents_is_no_reads_of_results() -> None:
    store = CountingStore()
    assert list(DocumentReads(store, store, store, "ENG-1", _own)) == []
    assert store.calls == ["documents"]  # nothing to look up: the bulk reads are never asked
